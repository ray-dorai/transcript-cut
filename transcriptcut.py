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
from pathlib import Path

import whisper

# Constants
WHISPER_MODEL = "small"
PADDING_BEFORE = 0.1  # default seconds before each segment
PADDING_AFTER = 0.1   # default seconds after each segment
GPU_WHISPER = False  # --gpu-whisper flag
GPU_ENCODE = False   # --gpu-encode flag
PADDING_SYNTAX = re.compile(r'\[([+-]?\d*\.?\d+),\s*([+-]?\d*\.?\d+)\]')  # matches [0.2,0.3] or [0.2, 0.3]

def normalize(text):
    """Remove punctuation, lowercase, standardize spaces"""
    text = text.lower()
    text = re.sub(r'[.,!?;:\"\'\(\)\[\]{}]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_transcript(video_path):
    """Pass 1: Extract audio, transcribe, save editable text and timing data"""
    video_path = Path(video_path).resolve()
    base_name = video_path.stem
    
    # Extract audio for whisper
    audio_path = f"{base_name}_audio.wav"
    print(f"Extracting audio from {video_path}...")
    subprocess.run([
        'ffmpeg', '-i', str(video_path),
        '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1',
        audio_path, '-y'
    ], check=True, capture_output=True)
    
    # Transcribe with whisper
    print(f"Transcribing with whisper model '{WHISPER_MODEL}'...")
    device = "cuda" if GPU_WHISPER else "cpu"
    model = whisper.load_model(WHISPER_MODEL, device=device)
    result = model.transcribe(audio_path, word_timestamps=True)
    
    # Extract word-level timestamps
    words = []
    for segment in result["segments"]:
        for word_data in segment.get("words", []):
            words.append({
                "word": word_data["word"].strip(),
                "start": word_data["start"],
                "end": word_data["end"]
            })

    # Save timing data
    timing_file = f"{base_name}_timing.json"
    with open(timing_file, "w") as f:
        json.dump(words, f, indent=2)

    # Save editable transcript (one segment per line)
    edit_file = f"{base_name}_edited.txt"
    segments = [seg["text"].strip() for seg in result["segments"]]
    with open(edit_file, "w") as f:
        f.write('\n'.join(segments))
    
    # Clean up audio file
    os.remove(audio_path)
    
    print(f"\n✓ Transcript extracted: {len(segments)} segments, {len(words)} words")
    print(f"  Edit this file: {edit_file}")
    print(f"  Then run: python {sys.argv[0]} render {video_path} {edit_file}")
    print(f"\nTip: Delete lines to remove, reorder as needed.")
    print(f"  Add padding with [before,after] syntax: 'some words [0.5,0.2]'")
    
    return edit_file, timing_file

def parse_edited_text(edited_text, default_before=PADDING_BEFORE, default_after=PADDING_AFTER):
    """
    Parse edited text with optional per-line padding markers.
    Format: "word word word [0.2,0.3]" means 0.2s before, 0.3s after
    """
    lines = edited_text.strip().split('\n')
    parsed_segments = []
    
    for line in lines:
        if not line.strip():
            continue
            
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
    Match edited text to timestamps.
    Matches phrases contiguously. Each line searches full timing array
    to support reordering.
    """
    all_segments = []

    # Build normalized lookup once
    timing_lookup = [(normalize(w["word"]), w) for w in word_timings]

    for segment_info in parsed_segments:
        edited_tokens = normalize(segment_info['text']).split()

        # Search entire timing array for each line (enables reordering)
        matched, _ = find_contiguous_phrase(tokens=edited_tokens, timing_lookup=timing_lookup, start_from=0)

        if matched:
            merged = {
                'word': ' '.join(s['word'] for s in matched),
                'start': max(0, matched[0]['start'] - segment_info['padding_before']),
                'end': matched[-1]['end'] + segment_info['padding_after'],
                'raw_start': matched[0]['start'],
                'raw_end': matched[-1]['end'],
                'padding_before': segment_info['padding_before'],
                'padding_after': segment_info['padding_after']
            }
            all_segments.append(merged)

    return all_segments


def render_video(video_path, edited_text_file, output_path=None, 
                 default_padding_before=PADDING_BEFORE, 
                 default_padding_after=PADDING_AFTER):
    """Pass 2: Reassemble video based on edited transcript"""
    video_path = Path(video_path).resolve()
    base_name = video_path.stem
    
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
    
    # Extract segments and build concat list
    temp_dir = Path(f"{base_name}_temp")
    temp_dir.mkdir(exist_ok=True)
    
    concat_file = temp_dir / "concat.txt"
    segment_files = []
    
    for i, seg in enumerate(segments):
        seg_file = temp_dir / f"seg_{i:04d}.mp4"
        segment_files.append(seg_file)
        
        # Extract segment with padding (-ss after -i for frame-accurate cuts)
        duration = seg["end"] - seg["start"]
        if GPU_ENCODE:
            codec, preset = 'h264_nvenc', 'fast'
        else:
            codec, preset = 'libx264', 'ultrafast'
        subprocess.run([
            'ffmpeg', '-i', str(video_path),
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
        'ffmpeg', '-f', 'concat', '-safe', '0',
        '-i', str(concat_file), '-c', 'copy', str(output_path), '-y'
    ], check=True, capture_output=True)
    
    # Generate and burn in captions
    print("Adding captions...")
    srt_file = temp_dir / "captions.srt"
    current_time = 0.0
    with open(srt_file, "w") as f:
        for i, seg in enumerate(segments, 1):
            segment_duration = seg["end"] - seg["start"]
            speech_duration = seg["raw_end"] - seg["raw_start"]

            # Speech starts after padding_before within each segment
            caption_start = current_time + seg["padding_before"]
            caption_end = caption_start + speech_duration

            f.write(f"{i}\n{format_srt_time(caption_start)} --> {format_srt_time(caption_end)}\n{seg['word']}\n\n")

            current_time += segment_duration
    
    # Burn in subtitles (escape path for ffmpeg filter syntax)
    final_output = f"{base_name}_final.mp4"
    escaped_srt = str(srt_file).replace('\\', '\\\\').replace(':', '\\:').replace("'", "\\'")
    subprocess.run([
        'ffmpeg', '-i', str(output_path),
        '-vf', f"subtitles={escaped_srt}:force_style='Fontsize=24'",
        '-c:a', 'copy', str(final_output), '-y'
    ], check=True, capture_output=True)
    
    # Clean up
    os.remove(output_path)
    for seg_file in segment_files:
        seg_file.unlink()
    concat_file.unlink()
    srt_file.unlink()
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
    # Parse GPU flags early
    if "--gpu" in sys.argv:
        GPU_WHISPER = GPU_ENCODE = True
        sys.argv.remove("--gpu")
    if "--gpu-whisper" in sys.argv:
        GPU_WHISPER = True
        sys.argv.remove("--gpu-whisper")
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
        print("  --gpu                     Use GPU for both whisper and encoding")
        print("  --gpu-whisper             Use CUDA for whisper transcription")
        print("  --gpu-encode              Use NVENC for video encoding")
        print("  --padding SECONDS         Default padding for all cuts")
        print("  --padding-before SECONDS  Default padding before cuts")
        print("  --padding-after SECONDS   Default padding after cuts")
        print("\nPer-line padding in edited.txt:")
        print("  'some words [0.5,0.2]'  = 0.5s before, 0.2s after this line")
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
        
        render_video(video_path, edited_file, None, padding_before, padding_after)
    
    else:
        print(f"Unknown command: {command}")
        print("Use 'extract' or 'render'")
        sys.exit(1)
