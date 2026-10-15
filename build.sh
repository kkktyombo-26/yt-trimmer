#!/usr/bin/env bash
set -e

echo "==> Installing Python dependencies"
pip install --upgrade pip
pip install -r requirements.txt

echo "==> Installing Node.js via nodeenv"
pip install nodeenv
nodeenv --node=20.19.0 "$HOME/.node" --prebuilt
export PATH="$HOME/.node/bin:$PATH"
node --version

echo "==> Verifying ffmpeg (bundled via imageio-ffmpeg)"
python -c "import imageio_ffmpeg; print('ffmpeg:', imageio_ffmpeg.get_ffmpeg_exe())"

echo "==> Build complete"
yt-dlp --version