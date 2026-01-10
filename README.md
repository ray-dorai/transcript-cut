# Edit Video with Text

 Delete words to delete video. Reorder words to reorder video. 

## Installation

```bash
pip install -r requirements.txt
```

Requires:
- Python 3.8+
- ffmpeg (tested with 4.4.2+)
- ~1GB for whisper model download (first run only)

## Usage

### Step 1: Extract Transcript
```bash
python transcriptcut.py extract video.mp4
```

This creates:
- `video_edited.txt` - Edit this file!
- `video_timing.json` - Timestamp data (don't edit)

### Step 2: Edit the Text

Open `video_edited.txt` in any text editor. Delete words, reorder them, whatever you want.

### Step 3: Render Your Edit
```bash
python transcriptcut.py render video.mp4 video_edited.txt
```

Creates `video_final.mp4` with your edits.

## Padding Control (Optional)

### Global Padding

Add padding to all cuts:
```bash
# 0.2 seconds on both sides of every cut
python transcriptcut.py render video.mp4 edited.txt --padding 0.2

# Different before/after
python transcriptcut.py render video.mp4 edited.txt --padding-before 0.1 --padding-after 0.3
```

### Per-Line Padding

Add `[before,after]` at the end of any line in your edited text:

```
Hello and welcome to the show
Today we're talking about [0.5,0.2]
artificial intelligence [-0.1,0.3]
and its impact on society [0,0]
```

This means:
- Line 1: Default padding (0.1s each side)
- Line 2: 0.5s before, 0.2s after (longer lead-in)
- Line 3: -0.1s before (tight cut), 0.3s after
- Line 4: No padding (sharp cut both ends)

## Features

- **Automatic silence speedup**: Speeds up silences 4x within kept segments
- **Burned-in captions**: Adds subtitles automatically (helps when audio gets choppy)
- **Simple alignment**: Just finds your edited words in order - no complex algorithms
- **Line-based editing**: Put different segments on different lines for cleaner cuts

## How It Works

1. **Whisper** transcribes the video with word-level timestamps
2. You edit the plain text transcript
3. The script matches your edited words back to their timestamps
4. **ffmpeg** extracts and concatenates the matching segments
5. Captions are generated and burned in

The key insight: editing video is really just editing text if you have good timestamps.

## Examples

### Remove filler words
Original: "So, um, basically, uh, what I'm saying is, you know, we need to, like, focus"
Edited: "What I'm saying is we need to focus"

### Reorder for clarity
Original: "The solution, which I'll explain, is simple, though it took years to develop"
Edited: "It took years to develop. The solution is simple"

### Create a highlight reel
Just keep the best lines from a long video:
```
This changes everything [0.5,0.5]
The implications are staggering [0.3,0.3]
We've never seen anything like it [0.2,0.5]
```

## Tips

- **Use newlines** to separate logical segments - this creates cleaner cuts
- **Add padding** when cuts feel too abrupt
- **Negative padding** (`[-0.1,0]`) creates punchy, tight edits
- **Keep punctuation** in your edits - it helps maintain natural flow

## Limitations

- Only works with speech (not music or sound effects)
- Can't add words that weren't spoken
- Quality depends on Whisper's transcription accuracy
- Captions may not perfectly sync with heavily edited segments

## Files

- `transcriptcut.py` - The entire tool (300 lines)
- `requirements.txt` - Just needs whisper
- `README.md` - This file

That's it. No frameworks, no databases, no GUI. Just text editing.
