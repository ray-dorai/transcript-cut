#!/usr/bin/env bash
# Double-click this in Finder. It opens Terminal in the bundle's folder and
# shows the README so the user knows what to type.
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
clear
cat README.txt
echo
echo "----------------------------------------------------------------------"
echo "You are in: $HERE"
echo "Drag your video file into this window, then press Enter to run extract."
echo "Or type a command yourself. Type 'exit' to close."
echo "----------------------------------------------------------------------"
echo
exec bash
