#!/usr/bin/env bash
# Build a self-contained TranscriptCut bundle for Linux x86_64.
# Output: dist/TranscriptCut-Linux-x86_64/
#
# Components:
#   - whisper-cli  (built in manylinux2014 container, glibc 2.17 floor)
#   - ffmpeg, ffprobe  (johnvansickle.com static builds, musl)
#   - python/  (python-build-standalone, musl, fully relocatable)
#   - models/ggml-small.bin
#   - transcriptcut.py  (the script, stdlib only)
#   - transcriptcut  (tiny wrapper that invokes ./python/bin/python3 transcriptcut.py)
#   - TranscriptCut.sh  (double-clickable launcher)
#   - README.txt
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$REPO_ROOT/dist/TranscriptCut-Linux-x86_64"
STAGING="$REPO_ROOT/dist/staging"
IMAGE="quay.io/pypa/manylinux2014_x86_64"

# Pin versions so builds are reproducible.
PBS_TAG="20260510"
PBS_FILE="cpython-3.11.15+${PBS_TAG}-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${PBS_FILE}"

FFMPEG_URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin"

command -v podman >/dev/null || { echo "ERROR: podman not installed. Run: sudo apt install podman"; exit 1; }
command -v curl >/dev/null   || { echo "ERROR: curl not installed."; exit 1; }
command -v tar >/dev/null    || { echo "ERROR: tar not installed."; exit 1; }

rm -rf "$OUT"
mkdir -p "$OUT/bin" "$OUT/models" "$STAGING"

echo "==> (1/5) Building whisper-cli in manylinux2014 container"
podman run --rm -v "$REPO_ROOT:/src:Z" -w /src "$IMAGE" \
    bash /src/build/in-container-linux.sh
mv "$STAGING/whisper-cli" "$OUT/bin/whisper-cli"

echo "==> (2/5) Fetching python-build-standalone"
if [ ! -f "$STAGING/$PBS_FILE" ]; then
    curl -L -o "$STAGING/$PBS_FILE" "$PBS_URL"
fi
tar -xzf "$STAGING/$PBS_FILE" -C "$OUT"
# python-build-standalone extracts as ./python — that's the layout we want.

echo "==> (3/5) Fetching static ffmpeg/ffprobe"
if [ ! -f "$STAGING/ffmpeg-static.tar.xz" ]; then
    curl -L -o "$STAGING/ffmpeg-static.tar.xz" "$FFMPEG_URL"
fi
tar -xJf "$STAGING/ffmpeg-static.tar.xz" -C "$STAGING"
FFDIR=$(ls -d "$STAGING"/ffmpeg-*-amd64-static | tail -1)
cp "$FFDIR/ffmpeg" "$FFDIR/ffprobe" "$OUT/bin/"
chmod +x "$OUT/bin/ffmpeg" "$OUT/bin/ffprobe"

echo "==> (4/5) Fetching ggml-small.bin"
if [ ! -f "$STAGING/ggml-small.bin" ]; then
    curl -L -o "$STAGING/ggml-small.bin" "$MODEL_URL"
fi
cp "$STAGING/ggml-small.bin" "$OUT/models/ggml-small.bin"

echo "==> (5/5) Assembling bundle"
cp "$REPO_ROOT/transcriptcut.py" "$OUT/transcriptcut.py"
cp "$REPO_ROOT/build/wrapper-linux.sh"  "$OUT/transcriptcut"
cp "$REPO_ROOT/build/launcher-linux.sh" "$OUT/TranscriptCut.sh"
cp "$REPO_ROOT/build/README-bundle.txt" "$OUT/README.txt"
chmod +x "$OUT/transcriptcut" "$OUT/TranscriptCut.sh" "$OUT/bin"/*

echo
echo "==> Bundle ready: $OUT"
du -sh "$OUT" "$OUT"/* 2>/dev/null | sort -h
