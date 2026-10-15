#!/usr/bin/env bash
# build.sh — Render build script
set -e

echo "==> Installing Python dependencies"
pip install --upgrade pip
pip install -r requirements.txt

echo "==> Installing ffmpeg via apt"
apt-get update -qq
apt-get install -y --no-install-recommends ffmpeg

echo "==> Build complete"
ffmpeg -version | head -1
yt-dlp --version
