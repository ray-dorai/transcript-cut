#!/usr/bin/env bash
# Builds a macOS bundle. Designed to run on a GitHub Actions macos-13 (Intel)
# or macos-14 (ARM) runner, but works locally on any Mac too.
# Sets MACOSX_DEPLOYMENT_TARGET=10.13 so the output runs on macOS 10.13+.
set -euo pipefail

ARCH="${1:?usage: build-macos.sh <x86_64|arm64>}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$REPO_ROOT/dist/TranscriptCut-macOS-$ARCH"
WORK="$(mktemp -d)"

export MACOSX_DEPLOYMENT_TARGET=10.13
rm -rf "$OUT"
mkdir -p "$OUT/bin" "$OUT/models"

# --- whisper.cpp ---------------------------------------------------------
echo "==> Building whisper.cpp for $ARCH"
cd "$WORK"
git clone --depth 1 --branch v1.8.4 https://github.com/ggml-org/whisper.cpp.git
cd whisper.cpp
cmake -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=OFF \
    -DGGML_NATIVE=OFF \
    -DGGML_METAL=OFF \
    -DWHISPER_BUILD_EXAMPLES=ON \
    -DWHISPER_BUILD_TESTS=OFF \
    -DCMAKE_OSX_ARCHITECTURES="$ARCH" \
    -DCMAKE_OSX_DEPLOYMENT_TARGET=10.13
cmake --build build -j --target whisper-cli
cp build/bin/whisper-cli "$OUT/bin/whisper-cli"
strip "$OUT/bin/whisper-cli" || true

# --- ffmpeg / ffprobe ----------------------------------------------------
# evermeet.cx ships static, deployment-target=10.13 builds for Intel.
# For arm64 we pull from osxexperts.net which provides arm64 static builds.
echo "==> Fetching static ffmpeg/ffprobe"
cd "$WORK"
if [ "$ARCH" = "x86_64" ]; then
    curl -L -o ffmpeg.zip https://evermeet.cx/ffmpeg/getrelease/zip
    curl -L -o ffprobe.zip https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip
    unzip -q ffmpeg.zip
    unzip -q ffprobe.zip
else
    # arm64 static builds — osxexperts.net mirrors evermeet's process for arm64.
    curl -L -o ffmpeg.zip "https://www.osxexperts.net/ffmpeg71arm.zip"
    curl -L -o ffprobe.zip "https://www.osxexperts.net/ffprobe71arm.zip"
    unzip -q ffmpeg.zip
    unzip -q ffprobe.zip
fi
mv ffmpeg "$OUT/bin/ffmpeg"
mv ffprobe "$OUT/bin/ffprobe"
chmod +x "$OUT/bin/ffmpeg" "$OUT/bin/ffprobe"
# Strip quarantine attribute the curl may have left.
xattr -dr com.apple.quarantine "$OUT/bin" 2>/dev/null || true

# --- model ---------------------------------------------------------------
echo "==> Fetching ggml-small.bin"
curl -L -o "$OUT/models/ggml-small.bin" \
    https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin

# --- python app ----------------------------------------------------------
echo "==> PyInstaller bundle"
python3 -m pip install --quiet --upgrade pip pyinstaller
cd "$REPO_ROOT"
python3 -m PyInstaller --onefile --name transcriptcut \
    --target-arch "$ARCH" \
    --distpath "$WORK/pyi-dist" --workpath "$WORK/pyi-work" \
    --specpath "$WORK/pyi-spec" \
    transcriptcut.py
cp "$WORK/pyi-dist/transcriptcut" "$OUT/transcriptcut"
chmod +x "$OUT/transcriptcut"

# --- launcher + readme ---------------------------------------------------
cp "$REPO_ROOT/build/launcher-macos.command" "$OUT/TranscriptCut.command"
chmod +x "$OUT/TranscriptCut.command"
cp "$REPO_ROOT/build/README-bundle.txt" "$OUT/README.txt"

echo "==> Done: $OUT"
du -sh "$OUT"
