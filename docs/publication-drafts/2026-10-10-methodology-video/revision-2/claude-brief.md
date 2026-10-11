# Claude Code /brag Composition Brief — Token by Token — an introduction to the lab and its methodology

Status: preview only; handoff status is not published (see not-published.json). Local rendering only; no network, hosting, deployment, sharing or social posting.

## Objective
Compose the 54.5s Token by Token methodology/premise video from the validated package below.
Brand and footage are fixed inputs: **compose — do not reinterpret.** Do not invent claims, measurements, URLs,
screenshots, dashboard controls, logos or fonts. Do not recreate the dashboard; use only the recorded footage.

## Output (hard requirements)
- Composition directory: `composition/` (this brief's directory). Render to `preview/methodology-preview.mp4`.
- 1080x1350, 30 fps, H.264 + AAC, 54.5s (48–55s allowed). Dark theme only.
- Poster baked as frame 0; poster `preview/poster.jpg`.

## Brand authority (non-negotiable)
- Logo: `assets/brand/token-by-token.svg` (byte copy of `assets/token-by-token.svg`). No other mark, no recolour.
- Lockup (match the dashboard `.tbt-brand` proportionally when scaled): text `TOKEN BY TOKEN`, Oswald Variable 600,
  uppercase, letter-spacing .055em, mark = 1.333x the type size, gap = 0.5x the type size (32px mark / 12px gap at the
  dashboard's 24px type); scale type, mark and gap by the same factor. `BY` is `#ff7a4d`; `TOKEN` words in `#eef1ec`.
- Typeface: `Oswald Variable` only — load `assets/fonts/oswald-latin-wght-normal.woff2` (+ `-latin-ext-`) with
  `@font-face { font-family: "Oswald Variable"; font-weight: 200 700; }`. No substitute display face.
- Dark palette:
  - paper: #0e1112
  - panel: #171c1d
  - ink: #eef1ec
  - copy: #c3cac7
  - muted: #9aa4a1
  - line: #283133
  - line-strong: #4a5659
  - better: #4bdcaf
  - worse: #ff7a4d
  - neutral: #f0ba4b
  - chapter: #d4c26a
  - chapter-nav: #79d8df
- Product name in prose: "Token by Token". Descriptor: "Inference Lab".
- State colours express evidence state, never engine identity.

## Footage
Real recorded dashboard clips are in `assets/clips/`. Framing is yours **inside the crop plan below**; you may zoom toward the active content (about 1.25–2x keeps dashboard text legible on a phone). Never alter
the page content. Videos must be muted, top-level timed elements (not inside a timed div); audio is separate.

## Crop plan (hard boundary)
The capture audited every recorded frame: text matching `episode` never overlaps these viewport rectangles.
Show only content inside the rectangle of the segment you are in (never the sticky site bar at the top, the left rail, or anything outside the rectangle).
Cut between segments under a cover (a wipe or flash): the instant a route changes the page jumps.
- s02-why after `wh-goto`: `page-header` x=340 y=140 w=1032 h=244 (viewport px of the 1440x1800 clip)
- s03-workloads after `wl-goto`: `source-cards` x=340 y=372 w=1032 h=1428 (viewport px of the 1440x1800 clip)
- s04-load after `ld-goto`: `steps-2-3` x=340 y=288 w=1032 h=260 (viewport px of the 1440x1800 clip)
- s04-load after `ld-goto`: `steps-5-6` x=340 y=640 w=1032 h=306 (viewport px of the 1440x1800 clip)
- s05-measure after `ms-goto`: `steps-5-6` x=340 y=640 w=1032 h=306 (viewport px of the 1440x1800 clip)
- s05-measure after `ms-goto-definitions`: `definitions-rows` x=340 y=100 w=1032 h=138 (viewport px of the 1440x1800 clip)
- s06-evidence after `ev-goto`: `rules` x=340 y=80 w=1032 h=314 (viewport px of the 1440x1800 clip)
- s06-evidence after `ev-goto-states`: `state-rows` x=340 y=280 w=1032 h=182 (viewport px of the 1440x1800 clip)


## Scenes
| id | time | kind | title |
|---|---|---|---|
| s01-what | 0–5s | brand | What Token by Token is |
| s02-why | 5–12.5s | dashboard | Why the methodology exists |
| s03-workloads | 12.5–25s | dashboard | The workload spectrum |
| s04-load | 25–34s | dashboard | How representative load behaves |
| s05-measure | 34–43s | dashboard | What the measurement lens sees |
| s06-evidence | 43–50s | dashboard | Where the evidence stops |
| s07-close | 50–54.5s | end-card | Brand close |

### s01-what — What Token by Token is (0s, 5s)
- Narration (Kokoro, already generated; do not rewrite): "Token by Token is an open inference lab, where every token is a measurement."
- On-screen copy, verbatim: ["TOKEN BY TOKEN", "Inference Lab", "An open inference lab", "Every token is a measurement."]
- Claim trace: c-open-lab, c-quote
- Footage: none — brand scene.
- Narration spans 0.3–4.716s.

### s02-why — Why the methodology exists (5s, 7.5s)
- Narration (Kokoro, already generated; do not rewrite): "Numbers mean little until the system, workload, scenario, metric rules, validity gates and evidence boundary are declared."
- On-screen copy, verbatim: ["Declared first", "System", "Workload", "Scenario", "Metric rules", "Validity gates", "Evidence boundary"]
- Claim trace: c-declared-items, c-disclosure-pattern
- Footage: `assets/clips/s02-why.mp4` (1440x1800, 30 fps, real recording of #methodology?theme=dark); start at scene start, play 1:1, no speed changes.
- Narration spans 5.3–12.276s.

### s03-workloads — The workload spectrum (12.5s, 12.5s)
- Narration (Kokoro, already generated; do not rewrite): "What enters the lab? Real chat conversations. Agentic coding with tools. Tool gaps and human think time. Optional issue-fix tasks, synthetic agent replay and tool-agent-user sessions."
- On-screen copy, verbatim: ["What enters the lab", "Real chat conversations", "Agentic coding histories", "Tool gaps and think time", "Optional issue-fix tasks", "Optional synthetic agent replay", "Optional tool-agent-user sessions", "Not every source feeds every study"]
- Claim trace: c-wl-chat, c-wl-agentic, c-wl-timing, c-wl-issuefix, c-wl-replay, c-optional-replay, c-wl-tau, c-optional-tau, c-not-every-study
- Footage: `assets/clips/s03-workloads.mp4` (1440x1800, 30 fps, real recording of #methodology?theme=dark&ch=sources); start at scene start, play 1:1, no speed changes.
- Narration spans 12.8–24.661s.

### s04-load — How representative load behaves (25s, 9s)
- Narration (Kokoro, already generated; do not rewrite): "Each run replays an exact-token or versioned corpus in order, with recorded or modeled gaps, declared context depth and output policy."
- On-screen copy, verbatim: ["Representative load", "Exact-token or versioned corpus", "Ordered conversations", "Recorded or modeled gaps", "Declared context depth", "Declared output policy"]
- Claim trace: c-wl-corpora, c-load-order, c-context-depth, c-output-policy
- Footage: `assets/clips/s04-load.mp4` (1440x1800, 30 fps, real recording of #methodology?theme=dark&ch=process); start at scene start, play 1:1, no speed changes.
- Narration spans 25.3–33.62s.

### s05-measure — What the measurement lens sees (34s, 9s)
- Narration (Kokoro, already generated; do not rewrite): "Measurement follows the user: visible waiting, token timing, output and validity, plus engine and GPU context where definitions match."
- On-screen copy, verbatim: ["What is measured", "Visible waiting", "Token timing", "Output and validity", "Engine and GPU context"]
- Claim trace: c-client-visible, c-engine-gpu-context
- Footage: `assets/clips/s05-measure.mp4` (1440x1800, 30 fps, real recording of #methodology?theme=dark&ch=process); start at scene start, play 1:1, no speed changes.
- Narration spans 34.3–42.769s.

### s06-evidence — Where the evidence stops (43s, 7s)
- Narration (Kokoro, already generated; do not rewrite): "Work before speed. Validity before capacity. Observed, not inferred. Unequal work blocks ranking."
- On-screen copy, verbatim: ["Evidence boundaries", "Work before speed.", "Validity before capacity.", "Observed, not inferred.", "Unequal work blocks ranking."]
- Claim trace: c-work-before-speed, c-validity-before-capacity, c-observed-not-inferred, c-unequal-work
- Footage: `assets/clips/s06-evidence.mp4` (1440x1800, 30 fps, real recording of #methodology?theme=dark&ch=rules); start at scene start, play 1:1, no speed changes.
- Narration spans 43.3–49.423s.

### s07-close — Brand close (50s, 4.5s)
- Narration (Kokoro, already generated; do not rewrite): "Token by Token. Every token is a measurement."
- On-screen copy, verbatim: ["TOKEN BY TOKEN", "Every token is a measurement.", "github.com/KVSDURGASURESH/token-by-token"]
- Claim trace: c-quote, c-repo-url
- Footage: none — brand scene.
- Narration spans 50.3–53.116s.

## Claims (every factual line must map here)
- `c-open-lab`: Token by Token is an open inference lab.  (source: `dashboard/src/PublicSite.tsx`)
- `c-quote`: Every token is a measurement.  (source: `design/reference/claude-site-v2/README.md`)
- `c-declared-items`: Each study separates the system under test, workload, scenario, metric rules, validity gates and evidence boundary.  (source: `dashboard/src/PublicSite.tsx`)
- `c-disclosure-pattern`: The disclosure pattern defines the workload and system, publishes metric rules and thresholds, and states what the evidence cannot establish.  (source: `dashboard/src/PublicSite.tsx`)
- `c-wl-chat`: Real chat conversations without tools represent the chat slice of a mixed population.  (source: `dashboard/src/data/site-v2/methodology-sources.json`)
- `c-wl-agentic`: Agentic coding request histories carry system prompts, function tools and tool output.  (source: `dashboard/src/data/site-v2/methodology-sources.json`)
- `c-wl-timing`: Timing distributions model tool-execution gaps and human think time.  (source: `dashboard/src/data/site-v2/methodology-sources.json`)
- `c-wl-issuefix`: Issue-fix task generation and patch grading is an optional path.  (source: `dashboard/src/data/site-v2/methodology-sources.json`)
- `c-wl-replay`: A prompt pack and client-behavior profile support synthetic agent replay.  (source: `dashboard/src/data/site-v2/methodology-sources.json`)
- `c-optional-replay`: Synthetic agent replay is an optional fixture.  (source: `dashboard/src/data/site-v2/methodology-sources.json`)
- `c-wl-tau`: An optional external generator produces tool-agent-user evaluation sessions.  (source: `dashboard/src/data/site-v2/methodology-sources.json`)
- `c-optional-tau`: Tool-agent-user sessions are an optional integration.  (source: `dashboard/src/data/site-v2/methodology-sources.json`)
- `c-wl-corpora`: A workload is resolved from a declared exact-token corpus or a versioned request corpus.  (source: `dashboard/src/PublicSite.tsx`)
- `c-not-every-study`: Some supported sources are not in the bundled default mix, so not every source feeds every study.  (source: `dashboard/src/data/site-v2/methodology-sources.json`)
- `c-load-order`: Requests preserve order and use recorded or modeled gaps.  (source: `dashboard/src/PublicSite.tsx`)
- `c-context-depth`: Probes are run at multiple context depths.  (source: `dashboard/src/data/site-v2/methodology-sources.json`)
- `c-output-policy`: The output policy is named before results are read.  (source: `dashboard/src/PublicSite.tsx`)
- `c-client-visible`: The client records visible time to first token, post-first-token timing, output, completion validity, failures and timestamps.  (source: `dashboard/src/PublicSite.tsx`)
- `c-engine-gpu-context`: Engine and GPU telemetry provide context when comparable definitions are available.  (source: `dashboard/src/PublicSite.tsx`)
- `c-work-before-speed`: Throughput and latency are ranked only after delivered work is comparable.  (source: `dashboard/src/PublicSite.tsx`)
- `c-validity-before-capacity`: Failed or incomplete levels cannot qualify a deployment, even when surviving requests look fast.  (source: `dashboard/src/PublicSite.tsx`)
- `c-observed-not-inferred`: Only tested points are reported; an unmeasured rate is not interpolated.  (source: `dashboard/src/PublicSite.tsx`)
- `c-unequal-work`: Unequal delivered work blocks ranking.  (source: `dashboard/src/PublicSite.tsx`)
- `c-repo-url`: The public repository is on GitHub.  (source: `dashboard/src/PublicSite.tsx`)

Forbidden: production readiness, maximum sustainable rate (unless negated), capacity (unless negated), causal or
superiority claims, Grafana, provider endpoints, service identifiers, private workload paths, unresolved URLs.
No episode, recorded/planned status or episode result may appear in narration, on-screen copy, footage, routes or the end card.

## End card
- Canonical logo + lockup, the closing quote "Every token is a measurement." (source: `c-quote`).
- URLs allowed on the end card (validated at prep time):
  - https://github.com/KVSDURGASURESH/token-by-token
- No other URL may appear. The conditional website appears only if it is listed above.

## Audio
- Use the single supplied mix `assets/audio/preview-mix.wav` (narration + side-chain ducked music, preview-unapproved-music,
  -16.0 LUFS, -1.5 dBTP). Place it at 0s as one `<audio>` element. Do not re-mix, add SFX
  or change levels: the ducking and loudness are measured policy.
- Music bed `b-afro-tech-pulse` is a TEMPORARY, **UNAPPROVED** candidate for preview only; rights are unverified.
  Mark the render as unapproved music in the share copy handoff; the owner selects the final track later.
- A subtle audio-reactive element is welcome (RMS of the supplied mix); keep text static-readable.

## Composition rules
- Use Hyperframes conventions: `data-composition-id`, `data-start`, `data-duration`, `data-track-index`, one paused GSAP
  timeline registered in `window.__timelines`; GSAP is at `assets/vendor/gsap.min.js`. Entrance animation on every
  element, a transition between every scene, exit animations only on the final scene.
- Hold every text line long enough to read; narration lines sit at the times listed above.
- Run `npx hyperframes check`; fix every error. Render locally only.

## Delivery
Write only inside `composition/` and `preview/`. Do not modify `../capture/`, the repository's `assets/` directory, repository sources or the
reference directory `brag-output-2026-10-10-181619/`. Finish by confirming nothing was published.
