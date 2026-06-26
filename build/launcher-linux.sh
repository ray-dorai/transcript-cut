#!/usr/bin/env bash
# Double-clickable launcher: opens a terminal in this bundle's directory so the
# user can run the two simple commands shown in README.txt.
# Many file managers honor the +x bit on .sh files; if double-click runs it in
# a terminal already, great. If it tries to "open" it as text, the user can
# also run it from a terminal manually.
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

# Try to spawn a terminal if we don't have one. Otherwise just print help.
if [ -t 0 ] && [ -t 1 ]; then
    : # already in a terminal
elif command -v x-terminal-emulator >/dev/null; then
    exec x-terminal-emulator -e bash -c "cd '$HERE' && bash"
elif command -v gnome-terminal >/dev/null; then
    exec gnome-terminal --working-directory="$HERE"
elif command -v konsole >/dev/null; then
    exec konsole --workdir "$HERE"
elif command -v xterm >/dev/null; then
    exec xterm -e bash -c "cd '$HERE' && bash"
fi

cat README.txt
echo
echo "You are in: $HERE"
echo "Type a command and press Enter. Type 'exit' to close."
exec bash
