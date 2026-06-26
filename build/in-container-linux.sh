#!/usr/bin/env bash
# Runs inside quay.io/pypa/manylinux2014_x86_64 (glibc 2.17).
# Sole job: build whisper-cli with a generic x86-64 target, drop it at
# /src/dist/staging/whisper-cli for the host script to consume.
set -euo pipefail

STAGING=/src/dist/staging
mkdir -p "$STAGING"

WORK=$(mktemp -d)
cd "$WORK"
git clone --depth 1 --branch v1.8.4 https://github.com/ggml-org/whisper.cpp.git
cd whisper.cpp
cmake -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=OFF \
    -DGGML_NATIVE=OFF \
    -DGGML_BACKEND_DL=OFF \
    -DWHISPER_BUILD_EXAMPLES=ON \
    -DWHISPER_BUILD_TESTS=OFF \
    -DCMAKE_C_FLAGS="-march=x86-64 -mtune=generic" \
    -DCMAKE_CXX_FLAGS="-march=x86-64 -mtune=generic"
cmake --build build -j --target whisper-cli

cp build/bin/whisper-cli "$STAGING/whisper-cli"
strip "$STAGING/whisper-cli"

# Sanity: dump glibc requirements so we can verify the floor.
echo "==> glibc symbol versions required by whisper-cli:"
objdump -T "$STAGING/whisper-cli" 2>/dev/null | grep GLIBC_ | awk '{print $NF}' | sort -V | uniq | tail -5
