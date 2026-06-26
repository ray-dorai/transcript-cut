#!/usr/bin/env bash
# Tiny dispatcher so the user can type:
#     ./transcriptcut extract video.mp4
#     ./transcriptcut render video.mp4 video_edited.txt
# It just hands off to the bundled Python interpreter.
HERE="$(cd "$(dirname "$0")" && pwd)"
exec "$HERE/python/bin/python3" "$HERE/transcriptcut.py" "$@"
