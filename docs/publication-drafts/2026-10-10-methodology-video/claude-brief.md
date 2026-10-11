# Claude Code /brag Composition Brief — Token by Token — how the lab measures

Status: preview only; handoff status is not published (see not-published.json). Local rendering only; no network, hosting, deployment, sharing or social posting.

## Objective
Compose the 52s Token by Token methodology/premise video from the validated package below.
Brand and footage are fixed inputs: **compose — do not reinterpret.** Do not invent claims, measurements, URLs,
screenshots, dashboard controls, logos or fonts. Do not recreate the dashboard; use only the recorded footage.

## Output (hard requirements)
- Composition directory: `composition/` (this brief's directory). Render to `preview/methodology-preview.mp4`.
- 1080x1350, 30 fps, H.264 + AAC, 52s (48–55s allowed). Dark theme only.
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
Real recorded dashboard clips are in `assets/clips/`. Framing is yours: you may crop/zoom toward the active content
(about 1.25–1.5x keeps dashboard text legible on a phone) and place it in a window with caption area. Never alter
the page content. Videos must be muted, top-level timed elements (not inside a timed div); audio is separate.

## Scenes
| id | time | kind | title |
|---|---|---|---|
| s01-brand | 0–5s | brand | Brand and premise |
| s02-episodes | 5–15s | dashboard | Episode index |
| s03-freeze | 15–21s | dashboard | Freeze the contract |
| s04-resolve | 21–27s | dashboard | Resolve the work |
| s05-measure | 27–34s | dashboard | Measure both sides |
| s06-states | 34–40s | dashboard | Evidence states |
| s07-boundaries | 40–46s | dashboard | Boundaries |
| s08-end-card | 46–52s | end-card | End card |

### s01-brand — Brand and premise (0s, 5s)
- Narration (Kokoro, already generated; do not rewrite): "Token by Token. Same GPU. Two engines. One declared bar."
- On-screen copy, verbatim: ["TOKEN BY TOKEN", "Inference Lab", "Same GPU. Two engines. One declared bar."]
- Claim trace: c-tagline, c-open-lab
- Footage: none — brand scene.
- Narration spans 0.3–4.801s.

### s02-episodes — Episode index (5s, 10s)
- Narration (Kokoro, already generated; do not rewrite): "We run open serving engines under recorded load, reading results one claim at a time. Two episodes are recorded; the rest are planned."
- On-screen copy, verbatim: ["Episodes", "Recorded", "Planned — no measurements"]
- Claim trace: c-claim-by-claim, c-ep0-recorded, c-ep1-recorded, c-planned-no-results
- Footage: `assets/clips/s02-episodes.mp4` (1440x1800, 30 fps, real recording of #episodes?theme=dark); start at scene start, play 1:1, no speed changes.
- Narration spans 5.3–13.748s.

### s03-freeze — Freeze the contract (15s, 6s)
- Narration (Kokoro, already generated; do not rewrite): "Before any result is read, the contract is frozen: workload, hardware, thresholds."
- On-screen copy, verbatim: ["01 Freeze the contract", "Declared before results"]
- Claim trace: c-freeze-contract
- Footage: `assets/clips/s03-freeze.mp4` (1440x1800, 30 fps, real recording of #methodology?theme=dark&ch=process); start at scene start, play 1:1, no speed changes.
- Narration spans 15.3–20.292s.

### s04-resolve — Resolve the work (21s, 6s)
- Narration (Kokoro, already generated; do not rewrite): "The workload is resolved. The endpoint is checked before any measurement begins."
- On-screen copy, verbatim: ["02 Resolve the workload", "03 Check the endpoint"]
- Claim trace: c-resolve-workload, c-check-endpoint
- Footage: `assets/clips/s04-resolve.mp4` (1440x1800, 30 fps, real recording of #methodology?theme=dark&ch=process); start at scene start, play 1:1, no speed changes.
- Narration spans 21.3–25.865s.

### s05-measure — Measure both sides (27s, 7s)
- Narration (Kokoro, already generated; do not rewrite): "Warm-up traffic is excluded. Then the client is measured, with engine and GPU telemetry alongside."
- On-screen copy, verbatim: ["04 Separate warm-up", "06 Measure both sides"]
- Claim trace: c-warmup-excluded, c-measure-both-sides
- Footage: `assets/clips/s05-measure.mp4` (1440x1800, 30 fps, real recording of #methodology?theme=dark&ch=process); start at scene start, play 1:1, no speed changes.
- Narration spans 27.3–33.7s.

### s06-states — Evidence states (34s, 6s)
- Narration (Kokoro, already generated; do not rewrite): "Every result carries an evidence state, and unequal work is never ranked."
- On-screen copy, verbatim: ["Evidence states", "Unequal work blocks ranking."]
- Claim trace: c-evidence-states, c-unequal-work
- Footage: `assets/clips/s06-states.mp4` (1440x1800, 30 fps, real recording of #methodology?theme=dark&ch=states); start at scene start, play 1:1, no speed changes.
- Narration spans 34.3–38.396s.

### s07-boundaries — Boundaries (40s, 6s)
- Narration (Kokoro, already generated; do not rewrite): "Tested loads are not capacity, and separate experiments are never pooled."
- On-screen copy, verbatim: ["Rules", "Tested loads are not capacity"]
- Claim trace: c-tested-loads-only, c-not-pooled
- Footage: `assets/clips/s07-boundaries.mp4` (1440x1800, 30 fps, real recording of #methodology?theme=dark&ch=rules); start at scene start, play 1:1, no speed changes.
- Narration spans 40.3–44.375s.

### s08-end-card — End card (46s, 6s)
- Narration (Kokoro, already generated; do not rewrite): "Every token is a measurement. Evidence, methods and limits are on GitHub."
- On-screen copy, verbatim: ["TOKEN BY TOKEN", "Every token is a measurement.", "github.com/KVSDURGASURESH/token-by-token"]
- Claim trace: c-quote, c-repo-url
- Footage: none — brand scene.
- Narration spans 46.3–50.844s.

## Claims (every factual line must map here)
- `c-tagline`: Same GPU. Two engines. One declared bar.  (source: `docs/superpowers/specs/2026-10-10-token-by-token-video-system-design.md`)
- `c-open-lab`: Token by Token is an open inference lab.  (source: `dashboard/src/PublicSite.tsx`)
- `c-claim-by-claim`: The lab runs open serving engines under recorded load and reads the results one claim at a time.  (source: `dashboard/src/PublicSite.tsx`)
- `c-ep0-recorded`: Episode 00 is recorded.  (source: `dashboard/src/data/episodes.json`)
- `c-ep1-recorded`: Episode 01 is recorded.  (source: `dashboard/src/data/episodes.json`)
- `c-planned-no-results`: Later episodes are planned and have no measurements.  (source: `dashboard/src/data/episodes.json`)
- `c-freeze-contract`: The contract (workload, hardware, thresholds) is declared before results are read.  (source: `dashboard/src/PublicSite.tsx`)
- `c-resolve-workload`: The workload is resolved from a declared exact-token corpus or a versioned request corpus.  (source: `dashboard/src/PublicSite.tsx`)
- `c-check-endpoint`: The endpoint is verified and smoke-tested before measurement.  (source: `dashboard/src/PublicSite.tsx`)
- `c-warmup-excluded`: Warm-up traffic is marked and excluded.  (source: `dashboard/src/PublicSite.tsx`)
- `c-measure-both-sides`: The client is measured, with engine and GPU telemetry as context.  (source: `dashboard/src/PublicSite.tsx`)
- `c-evidence-states`: Results are read through a defined vocabulary of evidence states.  (source: `dashboard/src/PublicSite.tsx`)
- `c-unequal-work`: Unequal delivered work blocks ranking.  (source: `dashboard/src/PublicSite.tsx`)
- `c-tested-loads-only`: Tested loads only; maximum sustainable rate is not measured.  (source: `dashboard/src/PublicSite.tsx`)
- `c-not-pooled`: Separate experiments share evidence rules but are not pooled into one experiment.  (source: `dashboard/src/PublicSite.tsx`)
- `c-quote`: Every token is a measurement.  (source: `design/reference/claude-site-v2/README.md`)
- `c-repo-url`: The public repository is on GitHub.  (source: `dashboard/src/data/episodes.json`)

Forbidden: production readiness, maximum sustainable rate (unless negated), capacity (unless negated), causal or
superiority claims, Grafana, provider endpoints, service identifiers, private workload paths, unresolved URLs.
Methodology footage must not imply that planned episodes already contain results.

## End card
- Canonical logo + lockup, the closing quote "Every token is a measurement." (source: `c-quote`).
- URLs allowed on the end card (validated at prep time):
  - https://github.com/KVSDURGASURESH/token-by-token
- No other URL may appear. The conditional website appears only if it is listed above.

## Audio
- Use the single supplied mix `assets/audio/preview-mix.wav` (narration + side-chain ducked music, preview-unapproved-music,
  -16.0 LUFS, -1.5 dBTP). Place it at 0s as one `<audio>` element. Do not re-mix, add SFX
  or change levels: the ducking and loudness are measured policy.
- Music bed `vol-12` is a TEMPORARY, **UNAPPROVED** candidate for preview only; rights are unverified.
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
