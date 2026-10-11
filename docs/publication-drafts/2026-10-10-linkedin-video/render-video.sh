#!/usr/bin/env bash
set -euo pipefail

video_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$video_dir"

node render.mjs

say -v Samantha -r 154 -f narration.txt -o narration.aiff

ffmpeg -hide_banner -loglevel error -y \
  -loop 1 -t 5.4 -i scene-0.png \
  -loop 1 -t 5.4 -i scene-1.png \
  -loop 1 -t 5.4 -i scene-2.png \
  -loop 1 -t 5.4 -i scene-3.png \
  -loop 1 -t 5.4 -i scene-4.png \
  -loop 1 -t 5.4 -i scene-5.png \
  -loop 1 -t 5.4 -i scene-6.png \
  -i narration.aiff \
  -filter_complex "\
    [0:v]fps=30,scale=1120:1400,crop=1080:1350:x='20+6*t/5.4':y='25+3*t/5.4',setsar=1[v0]; \
    [1:v]fps=30,scale=1120:1400,crop=1080:1350:x='20-5*t/5.4':y='25+3*t/5.4',setsar=1[v1]; \
    [2:v]fps=30,scale=1120:1400,crop=1080:1350:x='20+5*t/5.4':y='25-3*t/5.4',setsar=1[v2]; \
    [3:v]fps=30,scale=1120:1400,crop=1080:1350:x='20-4*t/5.4':y='25-2*t/5.4',setsar=1[v3]; \
    [4:v]fps=30,scale=1120:1400,crop=1080:1350:x='20+4*t/5.4':y='25+2*t/5.4',setsar=1[v4]; \
    [5:v]fps=30,scale=1120:1400,crop=1080:1350:x='20-5*t/5.4':y='25+2*t/5.4',setsar=1[v5]; \
    [6:v]fps=30,scale=1120:1400,crop=1080:1350:x='20+5*t/5.4':y='25-2*t/5.4',setsar=1[v6]; \
    [v0][v1]xfade=transition=fade:duration=0.4:offset=5.0[x1]; \
    [x1][v2]xfade=transition=fade:duration=0.4:offset=10.0[x2]; \
    [x2][v3]xfade=transition=fade:duration=0.4:offset=15.0[x3]; \
    [x3][v4]xfade=transition=fade:duration=0.4:offset=20.0[x4]; \
    [x4][v5]xfade=transition=fade:duration=0.4:offset=25.0[x5]; \
    [x5][v6]xfade=transition=fade:duration=0.4:offset=30.0,format=yuv420p[v]; \
    [7:a]adelay=350|350,apad=pad_dur=36,atrim=0:35,afade=t=in:st=0:d=0.25,afade=t=out:st=34:d=1,aresample=48000[a]" \
  -map "[v]" -map "[a]" -t 35 \
  -c:v libx264 -preset slow -crf 17 -profile:v high -level 4.2 \
  -c:a aac -b:a 192k -movflags +faststart \
  token-by-token-linkedin-1080x1350.mp4

ffprobe -v error -show_entries format=duration,size,bit_rate:stream=index,codec_name,codec_type,width,height,r_frame_rate,sample_rate,channels \
  -of json token-by-token-linkedin-1080x1350.mp4 > verification.json

ffmpeg -hide_banner -loglevel error -y -i token-by-token-linkedin-1080x1350.mp4 \
  -vf "fps=1/5,scale=270:338,tile=4x2:padding=10:margin=10:color=#11151a" \
  -frames:v 1 contact-sheet.png
