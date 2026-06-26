#!/usr/bin/env python3
"""
Transcript-based video editing: edit words, get video.
Two passes: extract (get transcript) -> render (reassemble from edited text)
Supports per-line padding control with [before,after] syntax.
"""

import os
import sys
import json
import subprocess
import re
import shutil
import tempfile
from pathlib import Path

PADDING_BEFORE = 0.1
PADDING_AFTER = 0.1
GPU_ENCODE = False
PADDING_SYNTAX = re.compile(r'\[([+-]?\d*\.?\d+),\s*([+-]?\d*\.?\d+)\]')
SOURCE_SYNTAX = re.compile(r'^\[([a-zA-Z0-9_-]+)\]\s*')
SENTENCE_END = re.compile(r'[.!?]["\')\]]?$')
AUDIO_EXTS = {'.mp3', '.m4a', '.aac', '.wav', '.flac', '.ogg', '.opus'}

# Resolve bundled binaries from a sibling bin/ dir (USB layout), else $PATH.
# Layout in the bundle:
#   <root>/transcriptcut            (or transcriptcut.py during dev)
#   <root>/bin/whisper-cli
#   <root>/bin/ffmpeg
#   <root>/bin/ffprobe
#   <root>/models/ggml-small.bin
def _bundle_root():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

def _resolve(name):
    candidate = _bundle_root() / 'bin' / name
    if candidate.exists():
        return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    sys.exit(f"ERROR: required binary '{name}' not found in {_bundle_root()/'bin'} or $PATH")

def _resolve_model():
    candidate = _bundle_root() / 'models' / 'ggml-small.bin'
    if candidate.exists():
        return str(candidate)
    env = os.environ.get('WHISPER_MODEL_PATH')
    if env and Path(env).exists():
        return env
    sys.exit(f"ERROR: model not found at {candidate}. Set WHISPER_MODEL_PATH or place it there.")

def normalize(text):
    """Remove punctuation, lowercase, standardize spaces"""
    text = text.lower()
    text = re.sub(r'[.,!?;:\"\'\(\)\[\]{}]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_transcript(video_path):
    """Pass 1: Extract audio, transcribe with whisper.cpp, save editable text and timing data"""
    video_path = Path(video_path).resolve()
    base_name = video_path.stem

    ffmpeg = _resolve('ffmpeg')
    whisper_cli = _resolve('whisper-cli')
    model_path = _resolve_model()

    audio_path = f"{base_name}_audio.wav"
    print(f"Extracting audio from {video_path}...")
    subprocess.run([
        ffmpeg, '-i', str(video_path),
        '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1',
        audio_path, '-y'
    ], check=True, capture_output=True)

    # whisper.cpp emits JSON next to a path we choose. Use a tempfile to keep things tidy.
    print("Transcribing with whisper.cpp...")
    with tempfile.TemporaryDirectory() as td:
        out_prefix = str(Path(td) / "out")
        subprocess.run([
            whisper_cli, '-m', model_path, '-f', audio_path,
            '-ml', '1', '-sow', '-oj', '-of', out_prefix, '--no-prints',
        ], check=True)
        with open(out_prefix + '.json', 'r') as f:
            data = json.load(f)

    # Each transcription[] entry is one word (due to -ml 1 -sow). Build word list.
    words = []
    for entry in data.get('transcription', []):
        text = entry.get('text', '').strip()
        if not text:
            continue
        off = entry['offsets']
        words.append({
            'word': text,
            'start': off['from'] / 1000.0,
            'end': off['to'] / 1000.0,
        })

    timing_file = f"{base_name}_timing.json"
    with open(timing_file, "w") as f:
        json.dump(words, f, indent=2)

    # Rebuild sentence-ish segments for the editable transcript by splitting on terminal punctuation.
    segments = []
    current = []
    for w in words:
        current.append(w['word'])
        if SENTENCE_END.search(w['word']):
            segments.append(' '.join(current))
            current = []
    if current:
        segments.append(' '.join(current))

    edit_file = f"{base_name}_edited.txt"
    with open(edit_file, "w") as f:
        f.write('\n'.join(segments))

    os.remove(audio_path)

    print(f"\n✓ Transcript extracted: {len(segments)} segments, {len(words)} words")
    print(f"  Edit this file: {edit_file}")
    print(f"  Then run: python {sys.argv[0]} render {video_path} {edit_file}")
    print(f"\nTip: Delete lines to remove, reorder as needed.")
    print(f"  Add padding with [before,after] syntax: 'some words [0.5,0.2]'")
    
    return edit_file, timing_file

def parse_edited_text(edited_text, default_before=PADDING_BEFORE, default_after=PADDING_AFTER):
    """
    Parse edited text with optional per-line padding and source markers.
    Format: "[source] word word word [0.2,0.3]"
    """
    lines = edited_text.strip().split('\n')
    parsed_segments = []

    for line in lines:
        if not line.strip():
            continue

        # Check for source marker at start of line
        source = None
        source_match = SOURCE_SYNTAX.match(line)
        if source_match:
            source = source_match.group(1)
            line = line[source_match.end():]

        # Check for padding marker at end of line
        padding_match = PADDING_SYNTAX.search(line)

        if padding_match:
            # Extract padding values
            padding_before = float(padding_match.group(1))
            padding_after = float(padding_match.group(2))
            # Remove padding marker from text
            text = line[:padding_match.start()].strip()
        else:
            # Use defaults
            padding_before = default_before
            padding_after = default_after
            text = line.strip()

        if text:  # Only if there's actual content
            parsed_segments.append({
                'text': text,
                'source': source,
                'padding_before': padding_before,
                'padding_after': padding_after
            })

    return parsed_segments

def find_contiguous_phrase(tokens, timing_lookup, start_from=0):
    """Find tokens appearing consecutively in timing data."""
    for start_idx in range(start_from, len(timing_lookup)):
        # Check if first token matches
        if timing_lookup[start_idx][0] != tokens[0]:
            continue

        # Try to match remaining tokens consecutively
        matched = [timing_lookup[start_idx][1]]
        timing_idx = start_idx + 1
        token_idx = 1

        while token_idx < len(tokens) and timing_idx < len(timing_lookup):
            norm_word, timing_data = timing_lookup[timing_idx]
            if norm_word == tokens[token_idx]:
                matched.append(timing_data)
                token_idx += 1
            timing_idx += 1
            # Allow skipping 1-2 filler words, but not big gaps
            if timing_idx - start_idx > len(tokens) + 2:
                break

        if len(matched) == len(tokens):
            return matched, timing_idx

    return None, start_from


def align_transcripts_with_padding(parsed_segments, word_timings):
    """
    Match edited text to timestamps. Prefer a forward search from the previous
    match's position (so repeated phrases like "Good." line up sequentially);
    fall back to a global search if not found (so user reordering still works).
    """
    all_segments = []
    timing_lookup = [(normalize(w["word"]), w) for w in word_timings]
    cursor = 0  # index into timing_lookup where the previous match ended

    for segment_info in parsed_segments:
        edited_tokens = normalize(segment_info['text']).split()

        matched, next_cursor = find_contiguous_phrase(
            tokens=edited_tokens, timing_lookup=timing_lookup, start_from=cursor)
        if not matched:
            matched, next_cursor = find_contiguous_phrase(
                tokens=edited_tokens, timing_lookup=timing_lookup, start_from=0)

        if matched:
            cursor = next_cursor
            merged = {
                'word': ' '.join(s['word'] for s in matched),
                'words': matched,  # Keep individual word timings for phrase-by-phrase subtitles
                'start': max(0, matched[0]['start'] - segment_info['padding_before']),
                'end': matched[-1]['end'] + segment_info['padding_after'],
                'raw_start': matched[0]['start'],
                'raw_end': matched[-1]['end'],
                'padding_before': segment_info['padding_before'],
                'padding_after': segment_info['padding_after'],
                'source': segment_info.get('source')
            }
            all_segments.append(merged)

    return all_segments


def _render_audio(audio_path, segments, ffmpeg, ffprobe, sources, question_pause,
                  question_min_words, word_timings):
    """Audio-only render path: cut, optionally insert silence after questions, concat."""
    base_name = audio_path.stem
    temp_dir = Path(f"{base_name}_temp")
    temp_dir.mkdir(exist_ok=True)

    probe = subprocess.run([
        ffprobe, '-v', 'error', '-select_streams', 'a:0',
        '-show_entries', 'stream=sample_rate,channels',
        '-of', 'csv=p=0', str(audio_path)
    ], capture_output=True, text=True, check=True)
    parts = [p for p in probe.stdout.strip().split(',') if p]
    sample_rate, channels = parts[0], parts[1]
    layout = 'stereo' if channels == '2' else 'mono'

    parts = []
    inserted = 0
    for i, seg in enumerate(segments):
        seg_src = sources.get(seg.get('source')) if seg.get('source') else None
        src = seg_src or audio_path
        duration = seg['end'] - seg['start']
        out = temp_dir / f"seg_{i:04d}.mp3"
        subprocess.run([
            ffmpeg, '-i', str(src),
            '-ss', str(seg['start']), '-t', str(duration),
            '-c:a', 'libmp3lame', '-b:a', '192k',
            '-ar', sample_rate, '-ac', channels,
            str(out), '-y'
        ], check=True, capture_output=True)
        parts.append(out)

        word_count = len(seg['word'].split())
        is_teacher_question = (seg['word'].rstrip().endswith('?')
                               and word_count >= question_min_words)
        if question_pause > 0 and is_teacher_question:
            sil = temp_dir / f"sil_{i:04d}.mp3"
            subprocess.run([
                ffmpeg,
                '-f', 'lavfi',
                '-i', f'anullsrc=channel_layout={layout}:sample_rate={sample_rate}',
                '-t', str(question_pause),
                '-c:a', 'libmp3lame', '-b:a', '192k',
                str(sil), '-y'
            ], check=True, capture_output=True)
            parts.append(sil)
            inserted += 1

    concat_file = temp_dir / 'concat.txt'
    with open(concat_file, 'w') as f:
        for p in parts:
            f.write(f"file '{p.absolute()}'\n")

    final_output = f"{base_name}_final.mp3"
    print(f"Assembling final audio ({inserted} question-pauses inserted)...")
    subprocess.run([
        ffmpeg, '-f', 'concat', '-safe', '0',
        '-i', str(concat_file), '-c', 'copy', final_output, '-y'
    ], check=True, capture_output=True)

    for p in parts:
        p.unlink()
    concat_file.unlink()
    temp_dir.rmdir()

    original_duration = word_timings[-1]['end'] if word_timings else 0
    new_duration = sum(s['end'] - s['start'] for s in segments) + inserted * question_pause
    print(f"\n✓ Audio rendered: {final_output}")
    print(f"  Original: {original_duration:.1f}s   New: {new_duration:.1f}s")
    return final_output


def render_video(video_path, edited_text_file, output_path=None,
                 default_padding_before=PADDING_BEFORE,
                 default_padding_after=PADDING_AFTER,
                 captions=True,
                 sources=None,
                 question_pause=0.0,
                 question_min_words=5):
    """Pass 2: Reassemble video (or audio) based on edited transcript"""
    video_path = Path(video_path).resolve()
    sources = sources or {}
    base_name = video_path.stem
    ffmpeg = _resolve('ffmpeg')
    ffprobe = _resolve('ffprobe')
    
    # Load edited text
    with open(edited_text_file, "r") as f:
        edited_text = f.read().strip()
    
    # Load original timing data
    timing_file = f"{base_name}_timing.json"
    if not Path(timing_file).exists():
        print(f"ERROR: Run extract first to generate {timing_file}")
        sys.exit(1)
    
    with open(timing_file, "r") as f:
        word_timings = json.load(f)
    
    # Parse edited text with padding markers
    print("Parsing edited text and padding markers...")
    parsed_segments = parse_edited_text(edited_text, default_padding_before, default_padding_after)
    
    # Align edited text to timestamps
    print("Matching edited text to timestamps...")
    segments = align_transcripts_with_padding(parsed_segments, word_timings)
    
    if not segments:
        print("ERROR: No matching segments found!")
        sys.exit(1)
    
    print(f"Keeping {len(segments)} segments")

    if video_path.suffix.lower() in AUDIO_EXTS:
        return _render_audio(video_path, segments, ffmpeg, ffprobe,
                             sources, question_pause, question_min_words, word_timings)

    # Extract segments and build concat list
    temp_dir = Path(f"{base_name}_temp")
    temp_dir.mkdir(exist_ok=True)
    
    concat_file = temp_dir / "concat.txt"
    segment_files = []
    
    for i, seg in enumerate(segments):
        seg_file = temp_dir / f"seg_{i:04d}.mp4"
        segment_files.append(seg_file)

        # Pick source file for this segment
        seg_source = seg.get('source')
        if seg_source and seg_source in sources:
            src_path = sources[seg_source]
        else:
            src_path = video_path

        # Extract segment with padding (-ss after -i for frame-accurate cuts)
        duration = seg["end"] - seg["start"]
        if GPU_ENCODE:
            codec, preset = 'h264_nvenc', 'fast'
        else:
            codec, preset = 'libx264', 'ultrafast'
        subprocess.run([
            ffmpeg, '-i', str(src_path),
            '-ss', str(seg["start"]), '-t', str(duration),
            '-c:v', codec, '-preset', preset,
            '-c:a', 'aac', str(seg_file), '-y'
        ], check=True, capture_output=True)
    
    # Write concat list
    with open(concat_file, "w") as f:
        for seg_file in segment_files:
            f.write(f"file '{seg_file.absolute()}'\n")
    
    # Concatenate segments
    if not output_path:
        output_path = f"{base_name}_output.mp4"

    print("Assembling final video...")
    subprocess.run([
        ffmpeg, '-f', 'concat', '-safe', '0',
        '-i', str(concat_file), '-c', 'copy', str(output_path), '-y'
    ], check=True, capture_output=True)
    
    final_output = f"{base_name}_final.mp4"

    if not captions:
        # No captions - just use concatenated output
        os.rename(output_path, final_output)
    else:
        # Generate and burn in captions (phrase-by-phrase for better pacing)
        print("Adding captions...")
        srt_file = temp_dir / "captions.srt"
        current_time = 0.0
        srt_index = 1
        WORDS_PER_PHRASE = 5

        with open(srt_file, "w") as f:
            for seg in segments:
                segment_duration = seg["end"] - seg["start"]
                seg_start_time = current_time + seg["padding_before"]
                words = seg.get('words', [])

                # Chunk words into phrases
                for i in range(0, len(words), WORDS_PER_PHRASE):
                    chunk = words[i:i + WORDS_PER_PHRASE]
                    phrase_text = ' '.join(w['word'] for w in chunk)

                    # Timing relative to segment start
                    phrase_start = seg_start_time + (chunk[0]['start'] - seg['raw_start'])
                    phrase_end = seg_start_time + (chunk[-1]['end'] - seg['raw_start'])

                    f.write(f"{srt_index}\n{format_srt_time(phrase_start)} --> {format_srt_time(phrase_end)}\n{phrase_text}\n\n")
                    srt_index += 1

                current_time += segment_duration

        # Get video dimensions and rotation for scaling subtitles
        probe = subprocess.run([
            ffprobe, '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height', '-of', 'csv=p=0',
            str(output_path)
        ], capture_output=True, text=True)
        width, height = map(int, probe.stdout.strip().split(','))

        # Check for rotation metadata (phone videos)
        rot_probe = subprocess.run([
            ffprobe, '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream_tags=rotate', '-of', 'csv=p=0',
            str(output_path)
        ], capture_output=True, text=True)
        rotation = int(rot_probe.stdout.strip()) if rot_probe.stdout.strip() else 0
        if rotation in (90, 270):
            width, height = height, width  # Swap for rotated video

        # Font as % of height, accounting for ASS scaling (scales with width, not height)
        target_pct = 0.03 if height > width else 0.05  # 3% for vertical, 5% for horizontal
        font_size = max(8, int(target_pct * 384 * height / width))
        escaped_srt = str(srt_file).replace('\\', '\\\\').replace(':', '\\:').replace("'", "\\'")
        subprocess.run([
            ffmpeg, '-i', str(output_path),
            '-vf', f"subtitles={escaped_srt}:force_style='Fontsize={font_size}'",
            '-c:a', 'copy', str(final_output), '-y'
        ], check=True, capture_output=True)

        os.remove(output_path)
        srt_file.unlink()

    # Clean up
    for seg_file in segment_files:
        seg_file.unlink()
    concat_file.unlink()
    temp_dir.rmdir()
    
    # Calculate stats
    original_duration = word_timings[-1]["end"] if word_timings else 0
    new_duration = sum(s["end"] - s["start"] for s in segments)
    
    print(f"\n✓ Video rendered: {final_output}")
    print(f"  Original: {original_duration:.1f}s")
    print(f"  New: {new_duration:.1f}s ({100*new_duration/original_duration:.0f}% kept)")
    
    return final_output

def format_srt_time(seconds):
    """Convert seconds to SRT format: 00:00:00,000"""
    hours = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{mins:02d}:{secs:06.3f}".replace(".", ",")

if __name__ == "__main__":
    if "--gpu-encode" in sys.argv:
        GPU_ENCODE = True
        sys.argv.remove("--gpu-encode")

    if len(sys.argv) < 3:
        print("Transcript-based video editing")
        print("\nUsage:")
        print(f"  {sys.argv[0]} extract VIDEO.mp4")
        print(f"    -> Creates VIDEO_edited.txt and VIDEO_timing.json")
        print(f"  {sys.argv[0]} render VIDEO.mp4 VIDEO_edited.txt [options]")
        print(f"    -> Creates VIDEO_final.mp4")
        print("\nOptions:")
        print("  --gpu-encode              Use NVENC for video encoding (Linux + NVIDIA only)")
        print("  --padding SECONDS         Default padding for all cuts")
        print("  --padding-before SECONDS  Default padding before cuts")
        print("  --padding-after SECONDS   Default padding after cuts")
        print("  --source NAME:PATH        Add named source for multi-source editing")
        print("  --question-pause SECONDS  Insert N seconds of silence after each question")
        print("                            (only for audio inputs; questions = lines ending '?')")
        print("  --question-min-words N    Min word count for a '?' line to count as a question")
        print("                            (default 5; filters out short student check-backs)")
        print("\nPer-line syntax in edited.txt:")
        print("  '[src] words [0.5,0.2]' = use source 'src', with padding")
        print("  '[ex] some words'       = pull from --source ex:file.aac")
        print("  'other words [-0.1,0]'  = tight cut before, no padding after")
        sys.exit(1)
    
    command = sys.argv[1]

    if command == "extract":
        video_path = sys.argv[2]
        extract_transcript(video_path)
    
    elif command == "render":
        video_path = sys.argv[2]
        edited_file = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else None
        
        # If no edited file specified, guess the name
        if not edited_file:
            base_name = Path(video_path).stem
            edited_file = f"{base_name}_edited.txt"
        
        # Parse padding options
        padding_before = PADDING_BEFORE
        padding_after = PADDING_AFTER
        
        if "--padding" in sys.argv:
            idx = sys.argv.index("--padding")
            padding_before = padding_after = float(sys.argv[idx + 1])
        
        if "--padding-before" in sys.argv:
            idx = sys.argv.index("--padding-before")
            padding_before = float(sys.argv[idx + 1])
        
        if "--padding-after" in sys.argv:
            idx = sys.argv.index("--padding-after")
            padding_after = float(sys.argv[idx + 1])

        captions = "--no-captions" not in sys.argv

        question_pause = 0.0
        question_min_words = 5
        if "--question-pause" in sys.argv:
            idx = sys.argv.index("--question-pause")
            question_pause = float(sys.argv[idx + 1])
        if "--question-min-words" in sys.argv:
            idx = sys.argv.index("--question-min-words")
            question_min_words = int(sys.argv[idx + 1])

        # Parse --source name:path options
        sources = {}
        i = 0
        while i < len(sys.argv):
            if sys.argv[i] == "--source" and i + 1 < len(sys.argv):
                name, path = sys.argv[i + 1].split(":", 1)
                sources[name] = Path(path).resolve()
                i += 2
            else:
                i += 1

        render_video(video_path, edited_file, None, padding_before, padding_after,
                     captions, sources, question_pause, question_min_words)
    
    else:
        print(f"Unknown command: {command}")
        print("Use 'extract' or 'render'")
        sys.exit(1)
