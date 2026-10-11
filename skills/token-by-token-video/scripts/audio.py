#!/usr/bin/env python3
"""Local Kokoro narration and vocal-safe signature mix, with measured stem margin."""
import argparse
from array import array
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from pipeline import ROOT, ENV, run, measure, write, sha

def mono(path):
    result=subprocess.run(['ffmpeg','-v','error','-i',str(path),'-ac','1','-ar','16000','-f','s16le','-'],check=True,capture_output=True)
    values=array('h'); values.frombytes(result.stdout); return values

def margin(voice,bed):
    a,b=mono(voice),mono(bed); values=[]; since=0
    for start in range(0,min(len(a),len(b))-1600,1600):
        def db(x):
            rms=math.sqrt(sum(float(v)*v for v in x)/1600)/32768
            return 20*math.log10(max(rms,1e-6))
        speech,music=db(a[start:start+1600]),db(b[start:start+1600])
        since=since+1 if speech>-45 else 0
        if since>=3: values.append(speech-music)
    assert values, 'no active speech'
    return sum(values)/len(values)

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True,type=Path);p.add_argument('--tts-python');args=p.parse_args()
    out=args.out.resolve();spec=json.loads((out/'inputs/spec.json').read_text());lock=json.loads((out/'inputs/production-contract.json').read_text())
    candidates=[Path(args.tts_python)] if args.tts_python else list(ROOT.glob('brag-output-*/.tts-venv/bin/python'))+[ROOT.parent/'OJAS/.venv/bin/python']
    python=next((p for p in candidates if p.exists() and subprocess.run([str(p),'-c','import kokoro_onnx,soundfile'],capture_output=True).returncode==0),None)
    assert python, 'Kokoro Python missing; provide --tts-python'
    tts=Path.home()/'.cache/hyperframes/tts';assert (tts/'models/kokoro-v1.0.onnx').is_file(), 'local Kokoro model missing'
    work=out/'work/audio';work.mkdir(parents=True,exist_ok=True)
    segments=[]
    for scene in spec['scenes']:
        wav=work/(scene['id']+'.wav');speed=lock['audio']['speed']
        for attempt in range(4):
            run([python,tts/'synth-v3.py',tts/'models/kokoro-v1.0.onnx',tts/'voices/voices-v1.0.bin',scene['narration'],lock['audio']['voice'],speed,wav,'en-us'])
            duration=float(run(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',wav]).stdout)
            if duration<=scene['duration']-.45:break
            speed=round(speed+.06,2)
        assert duration<=scene['duration']-.45, f"Narration overflow {scene['id']}; shorten script"
        segments.append({'id':scene['id'],'path':str(wav),'start':scene['start']+.25,'duration':duration,'speed':speed,'sha256':sha(wav)})
    inputs=[];filters=[]
    for i,s in enumerate(segments):
        inputs+=['-i',s['path']];filters.append(f'[{i}:a]aresample=48000,aformat=channel_layouts=mono,adelay={round(s["start"]*1000)}:all=1[s{i}]')
    filters.append(''.join(f'[s{i}]' for i in range(len(segments)))+f'amix=inputs={len(segments)}:normalize=0,apad=whole_dur={spec["duration"]},atrim=0:{spec["duration"]}[nar]')
    narration=work/'narration.wav';run(['ffmpeg','-v','error','-y',*inputs,'-filter_complex',';'.join(filters),'-map','[nar]','-ar','48000','-c:a','pcm_s24le',narration])
    voice=work/'voice-stem.wav';bed=work/'music-stem.wav';mix=work/'raw-mix.wav'
    extra=0
    for attempt in range(4):
        graph=f'[0:a]aresample=48000,aformat=channel_layouts=stereo,volume=6.5dB,asplit=3[v][sc][vo];[1:a]aresample=48000,aformat=channel_layouts=stereo,volume={-10.7-extra}dB,afade=t=in:st=0:d=0.4,afade=t=out:st={spec["duration"]-1}:d=1[b];[b][sc]sidechaincompress=threshold=0.02:ratio=10:attack=175:release=575:makeup=1[d];[d]asplit=2[dm][do];[v][dm]amix=inputs=2:normalize=0:duration=longest,atrim=0:{spec["duration"]}[mix]'
        run(['ffmpeg','-v','error','-y','-i',narration,'-i',out/'composition/assets/audio/signature-music.wav','-filter_complex',graph,'-map','[mix]','-c:a','pcm_s24le',mix,'-map','[vo]','-c:a','pcm_s24le',voice,'-map','[do]','-c:a','pcm_s24le',bed])
        headroom=margin(voice,bed)
        if 16<=headroom<=18:break
        extra+=17.5-headroom
    assert 16<=headroom<=18, 'music/narration balance outside 16–18 dB target'
    measured=measure(mix);gain=-16-measured['lufs']
    destination=out/'composition/assets/audio/preview-mix.wav'
    run(['ffmpeg','-v','error','-y','-i',mix,'-af',f'volume={gain}dB,alimiter=limit=0.7943:attack=5:release=60:level=0','-ar','48000','-ac','2','-c:a','pcm_s24le',destination])
    final=measure(destination)
    assert abs(final['lufs']+16)<=.6 and final['true_peak_dbtp']<=-1.5, 'audio loudness/peak failed'
    write(out/'inputs/audio-manifest.json',{'voice':'af_heart','segments':segments,'mix':final,'speech_margin_db':headroom,'music_offset':20,'music_extra_attenuation_db':extra,'mix_sha256':sha(destination),'rights':'unverified'})
    print(json.dumps({'mix':final,'speech_margin_db':round(headroom,2)},indent=2))

if __name__=='__main__':main()
