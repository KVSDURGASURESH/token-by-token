#!/usr/bin/env python3
"""Versioned local video preparation, Claude handoff, rerender and technical QA."""
import argparse
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[3]
SKILL = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((SKILL/'references/production-contract.json').read_text())
ENV = {**os.environ, 'HYPERFRAMES_NO_TELEMETRY':'1', 'DO_NOT_TRACK':'1', 'DISABLE_TELEMETRY':'1', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC':'1', 'PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD':'1'}

def run(argv, cwd=ROOT, capture=True):
    return subprocess.run(list(map(str, argv)), cwd=cwd, env=ENV, check=True, text=True, capture_output=capture)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2)+'\n')

def pointer(obj, ref):
    for part in ref.strip('/').split('/'):
        part = part.replace('~1','/').replace('~0','~')
        obj = obj[int(part)] if isinstance(obj,list) else obj[part]
    return obj

def validate(spec):
    assert spec['version']==2, 'unsupported spec version'
    assert re.fullmatch(r'[a-z0-9-]+',spec['slug']), 'unsafe slug'
    assert [spec[k] for k in ('width','height','fps')]==[1080,1350,30], 'delivery drift'
    assert spec['music_offset']==20 and spec['qr_hold_seconds']>=3, 'signature/end-card drift'
    qr_url=urlparse(spec['qr_url'])
    assert qr_url.scheme=='https' and qr_url.hostname=='tokenbytoken.org' and not qr_url.username, 'QR must use the owner portal'
    assert not re.search(r'\b(?:an open|an) inference lab\b',json.dumps(spec),re.I), 'descriptor drift'
    known=set()
    for claim in spec['claims']:
        source=claim['source']
        assert source.startswith('dashboard/src/data/') or source=='dashboard/src/PublicSite.tsx', 'claims require public dashboard sources'
        path=(ROOT/source).resolve()
        assert ROOT in path.parents and path.is_file(), 'unsafe/missing claim source'
        if 'pointer' in claim:
            assert pointer(json.loads(path.read_text()),claim['pointer'])==claim['value'], f"stale claim: {claim['id']}"
        else:
            assert claim['excerpt'] in path.read_text(), f"missing excerpt: {claim['id']}"
        assert claim['id'] not in known, 'duplicate claim'
        known.add(claim['id'])
    t=0
    for scene in spec['scenes']:
        assert abs(scene['start']-t)<0.001 and scene['duration']>0, 'noncontiguous timeline'
        assert set(scene['claims'])<=known, 'untraced scene claim'
        t+=scene['duration']
    assert abs(t-spec['duration'])<0.001, 'duration sum mismatch'
    for shot in spec['captures']:
        assert shot['route'].startswith('#') and 'theme=dark' in shot['route'], 'capture must be local/dark'
        assert shot.get('travel',0)>=0 and shot['duration']>0, 'upward/empty capture'
    for kind in ('logo','font'):
        path=ROOT/CONTRACT['brand'][kind]
        assert sha(path)==CONTRACT['brand'][kind+'_sha256'], f'{kind} brand drift'
    return True

def hyperframes(args):
    if args.hyperframes: return Path(args.hyperframes).resolve()
    found=shutil.which('hyperframes')
    options=[Path(found)] if found else sorted((Path.home()/'.npm/_npx').glob('*/node_modules/.bin/hyperframes'))
    assert options, 'Hyperframes not installed; provide --hyperframes (no downloads)'
    return options[-1]

def prepare(args,spec,out):
    assert not (out/'inputs/manifest.json').exists(), 'output already prepared; use a new revision'
    music=Path(args.music or Path.home()/'Downloads'/CONTRACT['audio']['music_file_name']).resolve()
    assert music.is_file() and sha(music)==CONTRACT['audio']['music_sha256'], 'wrong/missing signature audio'
    for d in ('inputs','composition/assets/brand','composition/assets/fonts','composition/assets/clips','composition/assets/audio','composition/assets/vendor','preview','work'):
        (out/d).mkdir(parents=True,exist_ok=True)
    write(out/'inputs/spec.json',spec)
    write(out/'inputs/production-contract.json',CONTRACT)
    sources={c['source'] for c in spec['claims']} | {'dashboard/src/PublicSite.tsx','dashboard/src/public-site.css'}
    fingerprints={p:sha(ROOT/p) for p in sorted(sources)}
    for p in sources:
        dest=out/'inputs/public-sources'/p
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/p,dest)
    for kind,dest in [('logo','brand/token-by-token.svg'),('font','fonts/oswald-latin-wght-normal.woff2')]:
        shutil.copy2(ROOT/CONTRACT['brand'][kind],out/'composition/assets'/dest)
    font_ext=ROOT/CONTRACT['brand']['font'].replace('latin-wght','latin-ext-wght')
    shutil.copy2(font_ext,out/'composition/assets/fonts/oswald-latin-ext-wght-normal.woff2')
    ref=ROOT/CONTRACT['reference_composition']
    shutil.copy2(ref,out/'inputs/approved-methodology-reference.html')
    shutil.copy2(ref.parent/'assets/vendor/gsap.min.js',out/'composition/assets/vendor/gsap.min.js')
    plugin=Path.home()/'.claude/plugins/cache/brag/brag/0.4.0/skills/brag'
    assert plugin.exists(), 'installed Brag skill is missing'
    shutil.copytree(plugin,out/'brag-skill',ignore=shutil.ignore_patterns('assets','scripts','__pycache__'),dirs_exist_ok=True)
    shutil.copy2(SKILL/'references/editorial-direction.v5.md',out/'inputs/editorial-rules.md')
    qr_lib=os.environ.get('TBT_QR_LIBRARY')
    if qr_lib: sys.path.insert(0,qr_lib)
    else:
        candidates=list(ROOT.glob('docs/publication-drafts/*-methodology-video/revision-5/work/qr-lib'))
        if candidates: sys.path.insert(0,str(candidates[0]))
    try:
        qrcode=importlib.import_module('qrcode'); svg=importlib.import_module('qrcode.image.svg')
    except ImportError as exc: raise RuntimeError('Install qrcode==8.2 locally or set TBT_QR_LIBRARY') from exc
    qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=10,border=4)
    qr.add_data(spec['qr_url']); qr.make(fit=True)
    qr.make_image(image_factory=svg.SvgPathFillImage).save(out/'composition/assets/brand/dashboard-qr.svg')
    run(['ffmpeg','-v','error','-y','-ss','20','-i',music,'-t',spec['duration'],'-ar','48000','-ac','2',out/'composition/assets/audio/signature-music.wav'])
    (out/'cue-analysis/assets/music').mkdir(parents=True,exist_ok=True)
    shutil.copy2(out/'composition/assets/audio/signature-music.wav',out/'cue-analysis/assets/music/signature-music.wav')
    (out/'cue-analysis/index.html').write_text(f'<div data-composition-id="root" data-width="1080" data-height="1350" data-duration="{spec["duration"]}"><audio id="music" data-timeline-role="music" data-start="0" data-duration="{spec["duration"]}" src="assets/music/signature-music.wav"></audio></div>')
    manifest={'version':2,'spec_sha256':sha(out/'inputs/spec.json'),'sources':fingerprints,'music_sha256':sha(music),'music_offset':20,'brand':CONTRACT['brand'],'hyperframes':str(hyperframes(args))}
    write(out/'inputs/manifest.json',manifest)
    write(out/'not-published.json',{'published':False,'uploaded':False,'status':'local-preview','music_rights':CONTRACT['audio']['rights'],'portal_verified':False,'owner_review':'pending'})
    prompt=f'''Use the staged Claude Brag skill: read brag-skill/SKILL.md and follow its dispatch (slim.md is staged too). Read inputs/spec.json, inputs/production-contract.json, inputs/editorial-rules.md, inputs/approved-methodology-reference.html and the public source snapshots. The owner asked to create this episode now; do not stop for another plan approval. Work only inside this output directory. No web tools, network fetch, publication, upload, deployment or commit.
Create a premium episode film using the approved methodology identity and animation language. The spec overrides Brag's default duration/format. Exact SVG/font/wordmark; The Inference Lab; dark palette; no screenshot boxes or white separator rules; labels identify each engine; facts and numbers are bound to public source claims. Cover only this episode, not a recap of other episodes or upcoming plans. Use the actual captured clips under composition/assets/clips with fixed camera framing. Scroll direction always downward and no decorative drift, oscillation or zoom breathing. Animate type and measurement reveals tastefully. Do not rebuild dashboard controls. A real configuration unfold and prominent subject dashboard action in the penultimate scene are required.
Narration is already prepared on the scene timeline and ducked into composition/assets/audio/preview-mix.wav. Use that one mix, unchanged. Music is the owner-selected TOO EZ source from 00:20. Use cue-analysis beat metadata when present for accents, while keeping all text readable and narration authoritative. No added music/SFX. End with spec.closing_quote, exact brand, both URLs and the supplied QR: >=260px and >=3s stationary, unobstructed hold. Portal availability and music rights remain unverified; this is local owner review only.
Create composition/index.html, brag-plan.md and share-copy.txt. Keep every source scene within its spec window. Use local GSAP/fonts already staged. Run the installed {hyperframes(args)} check with transition/cue samples; fix errors. Render preview/{spec['slug']}.mp4 at 1080x1350 30fps, {spec['duration']}s. Generate preview/poster.jpg, preview/contact-sheet.jpg and short review clips for the real interactions; inspect them. Run FFprobe/full decode/loudness and write preview/REVIEW-NOTES.md honestly. No npx, package install, external descriptions or publishing. Use only local Hyperframes/FFmpeg commands, telemetry disabled. State exactly which checks passed and any residual issue.'''
    (out/'CLAUDE-TASK.md').write_text(prompt)
    print('Prepared',out)

def check_inputs(out):
    manifest=json.loads((out/'inputs/manifest.json').read_text())
    assert sha(out/'inputs/spec.json')==manifest['spec_sha256'], 'prepared spec changed'
    for source,fingerprint in manifest['sources'].items():
        assert sha(ROOT/source)==fingerprint, f'public source changed: {source}; prepare new revision'
    return manifest

def capture(args,spec,out):
    check_inputs(out)
    run([ROOT/'dashboard/node_modules/.bin/vite','build','--outDir',out/'work/dashboard'],cwd=ROOT/'dashboard')
    run(['node',SKILL/'scripts/capture.mjs','--out',out],capture=False)

def audio(args,spec,out):
    check_inputs(out)
    run([sys.executable,SKILL/'scripts/audio.py','--out',out,*(['--tts-python',args.tts_python] if args.tts_python else [])],capture=False)
    try: run([hyperframes(args),'beats',out/'cue-analysis'])
    except subprocess.CalledProcessError as exc:
        print('Beat analysis unavailable; use musical pulse and document this:',exc,file=sys.stderr)

def compose(args,spec,out):
    check_inputs(out)
    hf=hyperframes(args)
    allow=f'Read,Write,Edit,Glob,Grep,Skill,Bash({hf} check *),Bash({hf} render *),Bash({hf} snapshot *),Bash({hf} --help),Bash(ffmpeg *),Bash(ffprobe *),Bash(mkdir *),Bash(cp *),Bash(shasum *)'
    argv=['claude','--restricted','-p','--tools','Read,Write,Edit,Glob,Grep,Skill,Bash','--permission-mode','acceptEdits','--permission-prompts','none','--allowedTools',allow,'--disallowedTools','WebFetch,WebSearch']
    result=subprocess.run(argv,input=(out/'CLAUDE-TASK.md').read_text(),cwd=out,env=ENV,text=True,capture_output=True)
    (out/'work/claude-result.txt').write_text(result.stdout)
    print(result.stdout)
    if result.returncode: raise RuntimeError(result.stderr or result.stdout)

def measure(path):
    result=run(['ffmpeg','-hide_banner','-nostats','-i',path,'-vn','-af','ebur128=peak=true','-f','null','-']).stderr
    summary=result[result.rfind('Summary:'):]
    return {'lufs':float(re.search(r'I:\s+(-?[\d.]+) LUFS',summary)[1]),'true_peak_dbtp':float(re.search(r'True peak:\s+Peak:\s+(-?[\d.]+)',summary)[1])}

def verify(args,spec,out):
    check_inputs(out)
    video=out/'preview'/f"{spec['slug']}.mp4"
    probe=json.loads(run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',video]).stdout)
    v=next(s for s in probe['streams'] if s['codec_type']=='video')
    a=next(s for s in probe['streams'] if s['codec_type']=='audio')
    assert [v['width'],v['height'],v['codec_name'],a['codec_name']]==[1080,1350,'h264','aac'], 'codec/geometry mismatch'
    assert v['avg_frame_rate']==v['r_frame_rate']=='30/1', 'frame rate mismatch'
    assert int(v['nb_frames'])==round(spec['duration']*30), 'frame count mismatch'
    assert abs(float(probe['format']['duration'])-spec['duration'])<0.05, 'duration mismatch'
    run(['ffmpeg','-v','error','-xerror','-i',video,'-f','null','-'])
    sound=measure(video)
    assert abs(sound['lufs']+16)<=0.6 and sound['true_peak_dbtp']<=-1.5, 'audio outside contract'
    for name in ('poster.jpg','contact-sheet.jpg','REVIEW-NOTES.md'):
        assert (out/'preview'/name).exists(), f'missing review artifact: {name}'
    assert json.loads((out/'not-published.json').read_text())['published'] is False
    qr_frame=out/'preview/qr-verification.png'
    run(['ffmpeg','-v','error','-y','-ss',str(spec['duration']-.2),'-i',video,'-frames:v','1',qr_frame])
    if sys.platform=='darwin' and shutil.which('swift'):
        run(['swift','-module-cache-path','/private/tmp/tbt-video-swift-cache',SKILL/'scripts/decode_qr.swift',qr_frame,spec['qr_url']])
        qr_status='decoded from final rendered frame'
    else:
        qr_status='independent decoder required on this platform'
    report={'ok':True,'video_sha256':sha(video),'probe':probe,'audio':sound,'qr':qr_status,'visual_review':'See REVIEW-NOTES.md; independently inspect animated clips','published':False}
    write(out/'preview/qa-report.json',report)
    print(json.dumps({'ok':True,'video':str(video),'audio':sound},indent=2))

def rerender(args,spec,out):
    check_inputs(out)
    run([hyperframes(args),'check',out/'composition','--at-transitions'],capture=False)
    run([hyperframes(args),'render',out/'composition','--fps','30','--quality','delivery','--video-frame-format','png','--output',out/'preview'/f"{spec['slug']}.mp4"],capture=False)
    verify(args,spec,out)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('stage',choices=['validate','prepare','capture','audio','compose','verify','rerender','run'])
    p.add_argument('--spec',required=True,type=Path); p.add_argument('--out',type=Path)
    p.add_argument('--music'); p.add_argument('--tts-python'); p.add_argument('--hyperframes')
    args=p.parse_args(); spec=json.loads(args.spec.read_text()); validate(spec)
    if args.stage=='validate': print('Spec and public claims valid'); return
    assert args.out, '--out required'
    out=args.out.resolve()
    assert ROOT/'docs/publication-drafts' in out.parents, 'output must be an isolated publication-drafts revision'
    if args.stage=='run':
        for stage in (prepare,capture,audio,compose,verify): stage(args,spec,out)
    else: globals()[args.stage](args,spec,out)

if __name__=='__main__':
    try: main()
    except (AssertionError,RuntimeError,subprocess.CalledProcessError) as exc:
        print('STOP:',exc,file=sys.stderr); sys.exit(1)
