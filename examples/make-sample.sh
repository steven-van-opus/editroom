#!/bin/sh
set -eu
samples="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
output="${1:-sample-source.mp4}"

ffmpeg -hide_banner -loglevel error -nostdin -n \
  -loop 1 -framerate 30 -t 2.6 -i "$samples/stage-1.webp" \
  -loop 1 -framerate 30 -t 2.9 -i "$samples/stage-2.webp" \
  -loop 1 -framerate 30 -t 2.5 -i "$samples/stage-3.webp" \
  -f lavfi -i 'sine=frequency=330:sample_rate=48000:duration=8' \
  -filter_complex '[0:v][1:v][2:v]concat=n=3:v=1:a=0[video]' \
  -map '[video]' -map 3:a -af 'volume=0.12' \
  -c:v libx264 -pix_fmt yuv420p -c:a aac -movflags +faststart "$output"
