TranscriptCut — edit video by editing its transcript
=====================================================

Everything you need is already in this folder. No installation required.

USAGE
-----

1. Copy your video (e.g. myvideo.mp4) into THIS folder.

2. Open a terminal in this folder, then run:

       ./transcriptcut extract myvideo.mp4

   This produces myvideo_edited.txt — the transcript, one sentence per line.

3. Open myvideo_edited.txt in any text editor. Delete the lines you don't
   want. Reorder lines to rearrange. Save.

4. Run:

       ./transcriptcut render myvideo.mp4 myvideo_edited.txt

   You'll get myvideo_final.mp4 with captions burned in.

PER-LINE OPTIONS in the edited.txt
----------------------------------

    some words [0.3,0.2]    add 0.3s padding before, 0.2s after this segment
    [b-roll] some words     pull this segment from a named --source

COMMAND-LINE OPTIONS
--------------------

    --padding SECONDS         default padding around every cut
    --padding-before SECONDS  default padding before only
    --padding-after SECONDS   default padding after only
    --no-captions             skip burned-in captions
    --source NAME:PATH        register an alternate source file

TROUBLESHOOTING
---------------

- "Permission denied" on first run: in a terminal here, run
      chmod +x transcriptcut TranscriptCut.sh bin/*
- First extract takes a while (the model is ~466 MB; it's local, not
  downloading — whisper is just slow on CPU). Subsequent extracts on the
  same video reuse the timing file.
