#!/usr/bin/env python3
"""Builds composition/index.html for the Token by Token methodology introduction (revision 2).

Everything that is data comes from the validated package: scene timing from the spec, footage timing from the
capture manifest, narration timing from the narration manifest, RMS from the preview mix. Every camera state of
every footage window is checked against the crop plan (the rectangles the capture audited for forbidden text);
the build fails if a window could show anything outside them.

Run with an interpreter that has numpy:  <python> build_composition.py
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
SPEC = json.loads((REPO / "video/specs/methodology-intro.v2.json").read_text(encoding="utf-8"))
CROP = json.loads((REPO / "video/specs/methodology-intro.v2.crop-plan.json").read_text(encoding="utf-8"))
CAP = json.loads((HERE / "capture/capture-manifest.json").read_text(encoding="utf-8"))
NAR = json.loads((HERE / "audio/narration/narration-manifest.json").read_text(encoding="utf-8"))

DURATION = SPEC["duration_seconds"]
SC = {s["id"]: s for s in SPEC["scenes"]}
START = {k: v["start_seconds"] for k, v in SC.items()}
DUR = {k: v["duration_seconds"] for k, v in SC.items()}
LEAD = {s["id"]: s["actions"][0]["end_ms"] / 1000 for s in CAP["scenes"]}
ACTIONS = {s["id"]: {a["id"]: a for a in s["actions"]} for s in CAP["scenes"]}
VIDEO_OFFSET = 0.036   # recorded video runs this far ahead of the action clock (measured from the route-change cuts)
STRIP_X, STRIP_W = 40, 1000
BEAT = 0.5

js: list[str] = []          # timeline statements
checks: list[str] = []      # containment report


def T(scene: str, rel: float) -> float:
    return round(START[scene] + rel, 3)


def clip_time(scene: str, action: str, edge: str = "start") -> float:
    """Scene-relative time (== clip time) at which a captured action starts or ends."""
    ms = ACTIONS[scene][action][f"{edge}_ms"]
    return round((ms - LEAD[scene] * 1000) / 1000 - VIDEO_OFFSET, 3)


def rect_of(scene: str, name: str) -> dict:
    for segment in CROP["scenes"][scene]:
        for rect in segment["rects"]:
            if rect["name"] == name:
                return rect
    raise KeyError(name)


def smoothstep(u: float) -> float:
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


class Strip:
    """A framed window onto the recorded page: camera state = (x0, y0, zoom) in viewport pixels."""

    def __init__(self, n: int, scene: str, top: int, height: int):
        self.n, self.scene, self.top, self.height = n, scene, top, height

    def region(self, x0, y0, z, height=None):
        return x0, y0, STRIP_W / z, (height or self.height) / z

    def verify(self, rect_name, x0, y0, z, height=None, label=""):
        rect = rect_of(self.scene, rect_name)
        rx, ry, rw, rh = self.region(x0, y0, z, height)
        ok = rx >= rect["x"] - 1e-6 and ry >= rect["y"] - 1e-6 and rx + rw <= rect["x"] + rect["w"] + 1e-6 and ry + rh <= rect["y"] + rect["h"] + 1e-6
        checks.append(f"{'OK ' if ok else 'BAD'} {self.scene} {label or rect_name}: region x={rx:.0f}..{rx + rw:.0f} y={ry:.0f}..{ry + rh:.0f} in {rect_name} "
                      f"x={rect['x']}..{rect['x'] + rect['w']} y={rect['y']}..{rect['y'] + rect['h']}")
        if not ok:
            raise SystemExit("crop containment failed:\n" + "\n".join(checks[-1:]))

    def tf(self, x0, y0, z):
        return f"x:{-x0 * z:.1f},y:{-y0 * z:.1f},scale:{z:.4f}"

    def set(self, t, rect_name, x0, y0, z, height=None):
        self.verify(rect_name, x0, y0, z, height)
        js.append(f'tl.set("#p{self.n}",{{{self.tf(x0, y0, z)},transformOrigin:"0 0"}},{t});')
        if height:
            js.append(f'tl.set("#st{self.n}",{{height:{height}}},{t});')

    def glide(self, t, d, rect_name, a, b, ease="power2.inOut"):
        """Pan/zoom between two states inside the same rectangle; every intermediate state is checked."""
        for u in np.linspace(0, 1, 41):
            x0, y0, z = (a[i] + (b[i] - a[i]) * u for i in range(3))
            self.verify_quiet(rect_name, x0, y0, z)
        self.verify(rect_name, *a, label="glide start")
        self.verify(rect_name, *b, label="glide end")
        js.append(f'tl.to("#p{self.n}",{{{self.tf(*b)},duration:{d},ease:"{ease}"}},{t});')

    def verify_quiet(self, rect_name, x0, y0, z):
        rect = rect_of(self.scene, rect_name)
        rx, ry, rw, rh = self.region(x0, y0, z)
        if not (rx >= rect["x"] - 1e-6 and ry >= rect["y"] - 1e-6 and rx + rw <= rect["x"] + rect["w"] + 1e-6 and ry + rh <= rect["y"] + rect["h"] + 1e-6):
            raise SystemExit(f"crop containment failed mid-glide in {self.scene}/{rect_name} at ({x0:.0f},{y0:.0f},{z:.3f})")

    def cut(self, jump_start: float, jump_end: float, rect_name, x0, y0, z, height):
        """Covered cut for a route change: opaque before the page jumps, reopened only after the unaudited gap."""
        close_at, open_at = round(jump_start - 0.20, 3), round(jump_end + 0.04, 3)
        js.append(f'tl.fromTo("#cv{self.n}",{{scaleX:0,transformOrigin:"0 50%"}},{{scaleX:1,duration:0.16,ease:"power2.in"}},{T(self.scene, close_at)});')
        self.set(T(self.scene, round(jump_start - 0.03, 3)), rect_name, x0, y0, z, height)
        js.append(f'tl.fromTo("#cv{self.n}",{{scaleX:1,transformOrigin:"100% 50%"}},{{scaleX:0,duration:0.22,ease:"power2.out",immediateRender:false}},{T(self.scene, open_at)});')


def up(sel, t, d=0.55, y=34):
    js.append(f'tl.fromTo("{sel}",{{opacity:0,y:{y}}},{{opacity:1,y:0,duration:{d},ease:"power3.out"}},{t});')


def xin(sel, t, d=0.5, x=-40):
    js.append(f'tl.fromTo("{sel}",{{opacity:0,x:{x}}},{{opacity:1,x:0,duration:{d},ease:"expo.out"}},{t});')


DIM = 0.55


def rows_in(scene: str, prefix: str, count: int, big: bool = False) -> None:
    """All rows are present (dimmed) from the start of the scene; each lights up on its narration cue."""
    for i in range(count):
        sel = f"#{prefix}-b{i}" if big else f"#{prefix}-r{i}"
        js.append(f'tl.fromTo("{sel}",{{opacity:0,x:-30}},{{opacity:{DIM},x:0,duration:0.45,ease:"expo.out"}},{T(scene, round(0.5 + 0.07 * i, 3))});')


def light(sel, t):
    js.append(f'tl.to("{sel}",{{opacity:1,duration:0.3,ease:"power2.out"}},{t});')


def on_row(sel_row, sel_mark, t):
    js.append(f'tl.to("{sel_mark}",{{backgroundColor:"#79d8df",borderColor:"#79d8df",duration:0.25,ease:"power2.out"}},{t});')
    js.append(f'tl.to("{sel_row} .lb",{{color:"#eef1ec",duration:0.25}},{t});')
    light(sel_row, t)


# ---- RMS of the supplied mix (subtle glow on the brand scenes) ---------------------------------------------------
def rms_series(wav: Path, hz: int = 10) -> list[float]:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-ac", "1", "-ar", "8000", "-f", "f32le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype="<f4")
    hop = 8000 // hz
    n = len(x) // hop
    r = np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(1))
    r = r / max(1e-9, np.percentile(r, 98))
    return [round(float(min(1.0, v)), 2) for v in r]


RMS = rms_series(HERE / "audio/preview/preview-mix.wav")

# ---- html pieces -------------------------------------------------------------------------------------------------
LOCK = '<img src="assets/brand/token-by-token.svg" alt="Token by Token logo"><span><span>Token</span> <span class="by">By</span> <span>Token</span></span>'
HEADER_LOCK = '<img src="assets/brand/token-by-token.svg" alt="Token by Token logo"><span><span data-layout-allow-occlusion>Token</span> <span class="by" data-layout-allow-occlusion>By</span> <span data-layout-allow-occlusion>Token</span></span>'


def list_rows(prefix: str, items: list[str], top: int, step: int, height: int, size: int, cls: str = "row") -> str:
    out = []
    for i, label in enumerate(items):
        out.append(f'<div id="{prefix}-r{i}" class="{cls}" style="top:{top + i * step}px;height:{height}px"><span class="ix">{i + 1:02d}</span>'
                   f'<span class="lb" style="font-size:{size}px">{label}</span><span id="{prefix}-k{i}" class="ck"></span></div>')
    return "\n    ".join(out)


def strip_html(n: int, scene: str, top: int, height: int, z_index: int) -> str:
    return (f'<div id="w{n}" class="stripwrap" style="z-index:{z_index}"><div id="st{n}" class="strip" style="top:{top}px;height:{height}px">'
            f'<div id="z{n}" class="zoom" data-layout-allow-overflow><div id="p{n}" class="pan" data-layout-allow-overflow>'
            f'<video id="v{n}" data-start="{START[scene]}" data-duration="{round(DUR[scene] + 0.6, 3)}" data-track-index="{10 + n}" src="assets/clips/{scene}.mp4" muted playsinline></video>'
            f'</div></div><div id="cv{n}" class="cover"></div></div></div>')


# phrase timings: seconds into each narration clip (silence detection), shifted by the 0.3 s scene lead
LEAD_S = SPEC["audio"]["scene_lead_seconds"]
PH = {
    "s01-what": {"headline": 1.0, "quote": 2.85},
    "s02-why": [1.5, 2.45, 3.4, 4.2, 5.25, 6.05],      # system, workload, scenario, metric rules, validity gates, evidence boundary
    "s03-workloads": [1.15, 3.0, 4.9, 7.2, 8.8, 10.4],  # chat, agentic, timing, issue-fix, replay, tool-agent-user
    "s04-load": [1.0, 3.9, 5.9, 6.9, 7.7],              # corpus, order, gaps, context depth, output policy
    "s05-measure": [1.9, 2.98, 3.95, 5.3],              # waiting, token timing, output and validity, engine and GPU
    "s06-evidence": [0.0, 1.25, 2.98, 4.6],             # four rules
}


def at(scene: str, offset: float, early: float = 0.12) -> float:
    return T(scene, round(LEAD_S + offset - early, 3))


css = """
@font-face{font-family:"Oswald Variable";font-style:normal;font-weight:200 700;src:url("assets/fonts/oswald-latin-wght-normal.woff2") format("woff2");unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}
@font-face{font-family:"Oswald Variable";font-style:normal;font-weight:200 700;src:url("assets/fonts/oswald-latin-ext-wght-normal.woff2") format("woff2");unicode-range:U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF}
:root{--paper:#0e1112;--panel:#171c1d;--ink:#eef1ec;--copy:#c3cac7;--muted:#9aa4a1;--line:#283133;--line-strong:#4a5659;--better:#4bdcaf;--worse:#ff7a4d;--neutral:#f0ba4b;--chapter:#d4c26a;--chapter-nav:#79d8df}
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1080px;height:1350px;background:var(--paper);overflow:hidden}
#root{position:relative;width:1080px;height:1350px;background:var(--paper);color:var(--ink);font-family:"Oswald Variable",sans-serif;overflow:hidden}
.abs{position:absolute}
.nw{white-space:nowrap}
.lockup{display:flex;align-items:center;gap:calc(var(--fs) * .5);font:600 var(--fs)/1 "Oswald Variable",sans-serif;letter-spacing:.055em;text-transform:uppercase;color:var(--ink);white-space:nowrap}
.lockup img{width:calc(var(--fs) * 1.3333);height:calc(var(--fs) * 1.3333);display:block}
.lockup .by{color:var(--worse)}
.disp{font-family:"Oswald Variable",sans-serif;font-weight:600;text-transform:uppercase;line-height:.95;letter-spacing:.005em}
.label{font-weight:500;text-transform:uppercase;letter-spacing:.16em}
.accent{color:var(--chapter-nav)}
.clip{position:absolute;left:0;top:0;width:1080px;height:1350px;background:var(--paper)}
.glow{position:absolute;left:-200px;top:260px;width:1480px;height:1000px;background:radial-gradient(closest-side,rgba(121,216,223,.20),rgba(121,216,223,0));opacity:.3}
#hdr{position:absolute;left:0;top:0;width:1080px;height:100px;background:var(--paper);border-bottom:1px solid var(--line)}
.ticks{position:absolute;left:40px;top:93px;width:1000px;height:5px;display:flex;gap:8px}
.ticks i{display:block;flex:1;height:5px;background:var(--line);transform-origin:50% 100%}
.row{position:absolute;left:56px;width:968px;border-top:1px solid var(--line)}
.row .ix{position:absolute;left:0;top:50%;transform:translateY(-50%);font-weight:500;font-size:32px;letter-spacing:.1em;color:var(--muted)}
.row .lb{position:absolute;left:92px;top:50%;transform:translateY(-52%);font-weight:600;text-transform:uppercase;line-height:1.05;letter-spacing:.01em;color:var(--copy);white-space:nowrap}
.row .ck{position:absolute;right:0;top:50%;width:30px;height:30px;margin-top:-15px;border:3px solid var(--line-strong);background:transparent}
.row .opt{color:var(--neutral)}
.row.ctx .ck{border-style:dashed}
.big{position:absolute;left:56px;width:968px;border-top:1px solid var(--line);padding-top:22px}
.big .lb{font-weight:600;text-transform:uppercase;line-height:1.02;letter-spacing:.008em;color:var(--ink);white-space:nowrap}
.stripwrap{position:absolute;left:0;top:0;width:1080px;height:1350px;pointer-events:none}
.strip{position:absolute;left:40px;width:1000px;overflow:hidden;background:var(--panel);border:2px solid var(--line-strong)}
.zoom{position:absolute;left:0;top:0;width:1000px;height:100%}
.pan{position:absolute;left:0;top:0;width:1440px;height:1800px;transform-origin:0 0}
.pan video{position:absolute;left:0;top:0;width:1440px;height:1800px}
.cover{position:absolute;left:0;top:0;width:100%;height:100%;background:var(--paper);border-right:6px solid var(--chapter-nav);transform:scaleX(0);transform-origin:0 50%}
.note{position:absolute;left:56px;font-weight:500;font-size:36px;letter-spacing:.04em;text-transform:uppercase;color:var(--copy);padding-left:20px;border-left:6px solid var(--neutral);white-space:nowrap}
#edge{position:absolute;left:0;top:0;width:6px;height:1350px;background:var(--chapter-nav);z-index:120;opacity:0}
"""


def headline(sel_id: str, text: str, size: int, top: int = 124, extra: str = "") -> str:
    return f'<div id="{sel_id}" class="abs disp nw" style="left:56px;top:{top}px;font-size:{size}px;{extra}">{text}</div>'


body: list[str] = []

# ===== S01 what =====
body.append(f'''
  <div id="sc1" class="clip" data-start="0" data-duration="{DUR["s01-what"]}" data-track-index="1" style="z-index:10">
    <div id="g1" class="glow"></div>
    <div id="s1-lock" class="abs lockup" style="--fs:60px;left:72px;top:170px">{LOCK}</div>
    <div id="s1-desc" class="abs label accent nw" style="left:72px;top:296px;font-size:30px">Inference Lab</div>
    <div id="s1-rule" class="abs" style="left:72px;top:372px;width:936px;height:1px;background:var(--line-strong)"></div>
    <div id="s1-h1" class="abs disp nw" style="left:72px;top:452px;font-size:176px;line-height:.92">An open</div>
    <div id="s1-h2" class="abs disp nw accent" style="left:72px;top:620px;font-size:176px;line-height:.92">inference</div>
    <div id="s1-h3" class="abs disp nw" style="left:72px;top:788px;font-size:176px;line-height:.92">lab.</div>
    <div id="s1-q" class="abs" style="left:72px;top:1086px;font-weight:500;font-size:54px;letter-spacing:.02em;text-transform:uppercase;color:var(--ink);padding-left:22px;border-left:6px solid var(--chapter-nav);white-space:nowrap">Every token is a measurement.</div>
  </div>''')

# ===== S02 why =====
why = ["System", "Workload", "Scenario", "Metric rules", "Validity gates", "Evidence boundary"]
body.append(f'''
  <div id="sc2" class="clip" data-start="{START["s02-why"]}" data-duration="{DUR["s02-why"]}" data-track-index="2" style="z-index:21">
    {headline("s2-h", "Declared <span class='accent'>first</span>", 118, 124)}
    {list_rows("s2", why, 292, 118, 118, 68)}
  </div>
  {strip_html(2, "s02-why", 1066, 190, 22)}''')

# ===== S03 workloads =====
fam = ["Real chat conversations", "Agentic coding histories", "Tool gaps and think time",
       "<span class='opt'>Optional</span> issue-fix tasks", "<span class='opt'>Optional</span> synthetic agent replay", "<span class='opt'>Optional</span> tool-agent-user sessions"]
body.append(f'''
  <div id="sc3" class="clip" data-start="{START["s03-workloads"]}" data-duration="{DUR["s03-workloads"]}" data-track-index="3" style="z-index:31">
    {headline("s3-h", "What enters the <span class='accent'>lab</span>", 88, 122)}
    {list_rows("s3", fam, 252, 86, 82, 50)}
    <div id="s3-note" class="note" style="top:790px">Not every source feeds every study</div>
  </div>
  {strip_html(3, "s03-workloads", 862, 440, 32)}''')

# ===== S04 load =====
load = ["Exact-token or versioned corpus", "Ordered conversations", "Recorded or modeled gaps", "Declared context depth", "Declared output policy"]
body.append(f'''
  <div id="sc4" class="clip" data-start="{START["s04-load"]}" data-duration="{DUR["s04-load"]}" data-track-index="4" style="z-index:41">
    {headline("s4-h", "Representative <span class='accent'>load</span>", 92, 122)}
    {list_rows("s4", load, 262, 108, 104, 48)}
  </div>
  {strip_html(4, "s04-load", 940, 320, 42)}''')

# ===== S05 measure =====
meas = ["Visible waiting", "Token timing", "Output and validity", "Engine and GPU context"]
body.append(f'''
  <div id="sc5" class="clip" data-start="{START["s05-measure"]}" data-duration="{DUR["s05-measure"]}" data-track-index="5" style="z-index:51">
    {headline("s5-h", "What is <span class='accent'>measured</span>", 92, 122)}
    {list_rows("s5", meas, 268, 148, 140, 68).replace('id="s5-r3" class="row"', 'id="s5-r3" class="row ctx"')}
  </div>
  {strip_html(5, "s05-measure", 1000, 175, 52)}''')

# ===== S06 evidence =====
rules = ["Work before speed.", "Validity before capacity.", "Observed, not inferred.", "Unequal work blocks ranking."]
big = "\n    ".join(f'<div id="s6-b{i}" class="big" style="top:{268 + i * 154}px;height:140px"><div class="lb" style="font-size:66px">{r}</div></div>' for i, r in enumerate(rules))
body.append(f'''
  <div id="sc6" class="clip" data-start="{START["s06-evidence"]}" data-duration="{DUR["s06-evidence"]}" data-track-index="6" style="z-index:61">
    {headline("s6-h", "Evidence <span class='accent'>boundaries</span>", 92, 122)}
    {big}
  </div>
  {strip_html(6, "s06-evidence", 966, 250, 62)}''')

# ===== header =====
body.append(f'''
  <div id="hdr-clip" class="clip" data-start="{START["s02-why"]}" data-duration="{round(START["s07-close"] - START["s02-why"] + 0.6, 3)}" data-track-index="9" data-layout-allow-occlusion style="z-index:90;pointer-events:none;height:100px;background:transparent">
    <div id="hdr" data-layout-allow-occlusion>
      <div id="h-lock" class="abs lockup" data-layout-allow-occlusion style="--fs:30px;left:40px;top:34px">{HEADER_LOCK}</div>
      <div id="h-desc" class="abs label nw" data-layout-allow-occlusion style="right:40px;top:36px;font-size:22px;color:var(--muted)">Inference Lab</div>
      <div class="ticks">{"".join(f'<i id="tk{i}"></i>' for i in range(7))}</div>
    </div>
  </div>''')

# ===== S07 close =====
body.append(f'''
  <div id="sc7" class="clip" data-start="{START["s07-close"]}" data-duration="{DUR["s07-close"]}" data-track-index="7" style="z-index:100">
    <div id="g7" class="glow"></div>
    <div id="s7-lock" class="abs lockup" style="--fs:60px;left:72px;top:190px">{LOCK}</div>
    <div id="s7-desc" class="abs label accent nw" style="left:72px;top:316px;font-size:30px">Inference Lab</div>
    <div id="s7-rule" class="abs" style="left:72px;top:392px;width:936px;height:1px;background:var(--line-strong)"></div>
    <div id="s7-q" class="abs disp" style="left:72px;top:470px;width:936px;font-size:126px;line-height:.98">Every <span class="accent">token</span> is a measurement.</div>
    <div id="s7-url" class="abs" style="left:72px;top:1090px;font-weight:500;font-size:46px;letter-spacing:.02em;color:var(--ink);padding-left:22px;border-left:6px solid var(--chapter-nav)">github.com/KVSDURGASURESH/token-by-token</div>
  </div>
  <div id="edge"></div>''')

# ---- timeline ---------------------------------------------------------------------------------------------------
js.append('var rms=%s;' % json.dumps(RMS, separators=(",", ":")))
js.append('for(var i=0;i<rms.length;i++){if(i<56)tl.to("#g1",{opacity:0.22+0.30*rms[i],duration:0.1,ease:"none"},i*0.1);if(i>=500)tl.to("#g7",{opacity:0.22+0.30*rms[i],duration:0.1,ease:"none"},i*0.1);}')

# S01
xin("#s1-lock", 0.2, 0.7, -60)
up("#s1-desc", 0.55, 0.5, 14)
js.append('tl.fromTo("#s1-rule",{scaleX:0,transformOrigin:"0 50%"},{scaleX:1,duration:0.8,ease:"power2.inOut"},0.7);')
h = LEAD_S + PH["s01-what"]["headline"]
up("#s1-h1", round(h - 0.1, 2), 0.6)         # beat-locked: lands with "open inference lab"
up("#s1-h2", round(h + 0.45, 2), 0.6)
up("#s1-h3", round(h + 1.0, 2), 0.6)
up("#s1-q", at("s01-what", PH["s01-what"]["quote"], 0.25), 0.7, 28)

# transitions: wipe each scene in over the outgoing one; an accent edge sweeps with it (beat-locked to the scene boundary)
WIPE_FROM, WIPE_TO = '{clipPath:"inset(0% 100% 0% 0%)"}', '{clipPath:"inset(0% 0% 0% 0%)",duration:0.5,ease:"power3.inOut"}'
scene_nodes = {"s02-why": (2, ["#sc2", "#w2"]), "s03-workloads": (3, ["#sc3", "#w3"]), "s04-load": (4, ["#sc4", "#w4"]),
               "s05-measure": (5, ["#sc5", "#w5"]), "s06-evidence": (6, ["#sc6", "#w6"]), "s07-close": (7, ["#sc7"])}
for sid, (n, nodes) in scene_nodes.items():
    sel = json.dumps(nodes)
    js.append(f'tl.set({sel},{WIPE_FROM},0);')
    b = START[sid]
    js.append(f'tl.fromTo({sel},{WIPE_FROM},{WIPE_TO},{b});')
    js.append(f'/* beat-locked: wipe on the scene boundary {b}s (beat {int(b / BEAT)}) with the section lift */')
    js.append(f'tl.set("#edge",{{opacity:1,x:-6}},{b});tl.to("#edge",{{x:1080,duration:0.5,ease:"power3.inOut"}},{b});tl.set("#edge",{{opacity:0}},{round(b + 0.5, 3)});')
js.append(f'tl.fromTo("#hdr",{{opacity:0}},{{opacity:1,duration:0.45,ease:"sine.inOut"}},{START["s02-why"]});')

# progress ticks: scene i is "on" from its start; the active tick breathes on the beat (kept very small)
order = ["s01-what", "s02-why", "s03-workloads", "s04-load", "s05-measure", "s06-evidence", "s07-close"]
for i, sid in enumerate(order[:-1]):
    js.append(f'tl.set("#tk{i}",{{backgroundColor:"#79d8df"}},{max(START[sid], START["s02-why"])});')
js.append(f'tl.set("#tk6",{{backgroundColor:"#79d8df"}},{START["s07-close"]});')
for sid, i in zip(order[1:-1], range(1, 6)):
    b = START[sid]
    while b < START[order[i + 1]] - 1e-6:
        js.append(f'tl.fromTo("#tk{i}",{{scaleY:1}},{{scaleY:1.9,duration:0.07,yoyo:true,repeat:1,ease:"sine.inOut",immediateRender:false}},{round(b + 0.5, 3)});')
        b += BEAT

# S02 why: checklist ticks with the narration; strip shows the page header
s = Strip(2, "s02-why", 1066, 190)
s.set(0, "page-header", 340, 142, 1.25)
up("#s2-h", T("s02-why", 0.35), 0.6)
rows_in("s02-why", "s2", len(why))
for i, off in enumerate(PH["s02-why"]):
    t = at("s02-why", off, 0.25)
    on_row(f"#s2-r{i}", f"#s2-k{i}", round(t + 0.35, 3))
js.append(f'tl.fromTo("#st2",{{opacity:0}},{{opacity:1,duration:0.5,ease:"sine.out"}},{T("s02-why", 0.5)});')

# S03 workloads: rows lit with the narration; the camera follows each family's real card as the page scrolls
s = Strip(3, "s03-workloads", 862, 440)
cards = [("wildchat", 4008), ("nebius", 3661), ("trace", 4181), ("swe", 4608), ("kilo", 4781), ("tau", 4975)]
t0 = clip_time("s03-workloads", "wl-scroll-cards", "start")
t1 = t0 + 6.0
S0, S1 = 3256, 3745


def scroll_at(t):
    return S0 + (S1 - S0) * smoothstep((t - t0) / 6.0)


def card_cam(page_y, t):
    return 340 + 6, max(372, page_y - scroll_at(t) - 22)


s.set(0, "source-cards", 346, 372, 1.0)
rows_in("s03-workloads", "s3", len(fam))
last = (346, 372, 1.0)
cues = [round(LEAD_S + off - 0.2, 3) for off in PH["s03-workloads"]]
for i, t_rel in enumerate(cues):
    on_row(f"#s3-r{i}", f"#s3-k{i}", T("s03-workloads", round(t_rel + 0.3, 3)))
    end = cues[i + 1] if i + 1 < len(cues) else DUR["s03-workloads"] - 0.4
    x0, y0 = card_cam(cards[i][1], t_rel + 0.55)
    y0 = min(y0, 1800 - 440)
    s.glide(T("s03-workloads", t_rel), 0.55, "source-cards", last, (x0, y0, 1.0))
    last = (x0, y0, 1.0)
    # follow the card while the real page scrolls underneath the camera
    tt = round(t_rel + 0.55, 3)
    while tt + 0.25 < end - 1e-6:
        nxt = round(tt + 0.25, 3)
        nx, ny = card_cam(cards[i][1], nxt)
        ny = min(ny, 1800 - 440)
        s.glide(T("s03-workloads", tt), 0.25, "source-cards", last, (nx, ny, 1.0), ease="none")
        last = (nx, ny, 1.0)
        tt = nxt
up("#s3-h", T("s03-workloads", 0.35), 0.6)
up("#s3-note", T("s03-workloads", 10.9), 0.5, 20)
js.append(f'tl.fromTo("#st3",{{opacity:0}},{{opacity:1,duration:0.5,ease:"sine.out"}},{T("s03-workloads", 0.5)});')

# S04 load
s = Strip(4, "s04-load", 940, 320)
s.set(0, "steps-2-3", 346, 290, 1.25)
up("#s4-h", T("s04-load", 0.35), 0.6)
rows_in("s04-load", "s4", len(load))
for i, off in enumerate(PH["s04-load"]):
    t = at("s04-load", off, 0.3)
    on_row(f"#s4-r{i}", f"#s4-k{i}", round(t + 0.35, 3))
cut_t = round(LEAD_S + PH["s04-load"][1] - 0.5, 3)      # as "in order" lands: route stays, the camera moves to the replay step
js.append(f'tl.fromTo("#cv4",{{scaleX:0,transformOrigin:"0 50%"}},{{scaleX:1,duration:0.16,ease:"power2.in"}},{T("s04-load", cut_t - 0.16)});')
s.set(T("s04-load", cut_t + 0.02), "steps-5-6", 346, 648, 1.25, 320)
js.append(f'tl.fromTo("#cv4",{{scaleX:1,transformOrigin:"100% 50%"}},{{scaleX:0,duration:0.22,ease:"power2.out",immediateRender:false}},{T("s04-load", cut_t + 0.06)});')
js.append(f'tl.fromTo("#st4",{{opacity:0}},{{opacity:1,duration:0.5,ease:"sine.out"}},{T("s04-load", 0.5)});')

# S05 measure
s = Strip(5, "s05-measure", 1000, 175)
s.set(0, "steps-5-6", 346, 772, 1.25, 175)
up("#s5-h", T("s05-measure", 0.35), 0.6)
rows_in("s05-measure", "s5", len(meas))
for i, off in enumerate(PH["s05-measure"]):
    t = at("s05-measure", off, 0.3)
    on_row(f"#s5-r{i}", f"#s5-k{i}", round(t + 0.35, 3))
j0, j1 = clip_time("s05-measure", "ms-goto-definitions", "start"), clip_time("s05-measure", "ms-goto-definitions", "end")
s.cut(j0, j1, "definitions-rows", 340, 100, 1.0, 138)
js.append(f'tl.fromTo("#st5",{{opacity:0}},{{opacity:1,duration:0.5,ease:"sine.out"}},{T("s05-measure", 0.5)});')

# S06 evidence
s = Strip(6, "s06-evidence", 966, 250)
Z6 = 1.95
s.set(0, "rules", 342, 150, Z6)
up("#s6-h", T("s06-evidence", 0.35), 0.6)
rows_in("s06-evidence", "s6", len(rules), big=True)
for i, off in enumerate(PH["s06-evidence"]):
    light(f"#s6-b{i}", at("s06-evidence", off, 0.25))
s.glide(T("s06-evidence", round(LEAD_S + PH["s06-evidence"][1] - 0.45, 3)), 0.5, "rules", (342, 150, Z6), (846, 150, Z6))
s.glide(T("s06-evidence", round(LEAD_S + PH["s06-evidence"][2] - 0.45, 3)), 0.5, "rules", (846, 150, Z6), (342, 232, Z6))
j0, j1 = clip_time("s06-evidence", "ev-goto-states", "start"), clip_time("s06-evidence", "ev-goto-states", "end")
s.cut(j0, j1, "state-rows", 546, 282, 1.4, 250)
js.append(f'tl.fromTo("#st6",{{opacity:0}},{{opacity:1,duration:0.5,ease:"sine.out"}},{T("s06-evidence", 0.5)});')

# S07 close
xin("#s7-lock", T("s07-close", 0.3), 0.7, -60)
up("#s7-desc", T("s07-close", 0.6), 0.5, 14)
js.append(f'tl.fromTo("#s7-rule",{{scaleX:0,transformOrigin:"0 50%"}},{{scaleX:1,duration:0.8,ease:"power2.inOut"}},{T("s07-close", 0.7)});')
up("#s7-q", T("s07-close", 0.9), 0.8, 40)
up("#s7-url", T("s07-close", 2.0), 0.6, 24)
js.append(f'tl.to("#sc7",{{opacity:0,duration:0.5,ease:"power1.in"}},{round(DURATION - 0.5, 3)});')

html = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Token by Token — an introduction to the lab and its methodology</title>
<style>{css}</style>
</head>
<body>
<div id="root" data-composition-id="root" data-width="1080" data-height="1350" data-start="0" data-duration="{DURATION}">
{"".join(body)}

  <!-- audio: one pre-mixed, ducked, loudness-normalized track (temporary UNAPPROVED preview music bed) -->
  <audio id="mix" data-start="0" data-duration="{DURATION}" data-track-index="20" data-volume="1" src="assets/audio/preview-mix.wav"></audio>

  <script src="assets/vendor/gsap.min.js"></script>
  <script>
  (function () {{
    var tl = gsap.timeline({{ paused: true }});
    {chr(10).join("    " + line for line in js if line)}
    window.__timelines = window.__timelines || {{}};
    window.__timelines["root"] = tl;
  }})();
  </script>
</div>
</body>
</html>
'''
(HERE / "composition").mkdir(exist_ok=True)
(HERE / "composition/index.html").write_text(html, encoding="utf-8")
(HERE / "composition-crop-check.txt").write_text("\n".join(checks) + "\n", encoding="utf-8")
print(f"wrote composition/index.html ({len(html)} bytes); {len(checks)} crop-containment checks passed")
