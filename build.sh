#!/usr/bin/env bash
set -e

echo "==> Installing system dependencies"
apt-get update -qq
apt-get install -y --no-install-recommends ffmpeg curl ca-certificates

echo "==> Installing Node.js 20 (LTS)"
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs
node --version

echo "==> Installing Python dependencies"
pip install --upgrade pip
pip install -r requirements.txt

echo "==> Build complete"
ffmpeg -version | head -1
yt-dlp --version