# Hyperframes Composition Brief: Token by Token — Inference Lab

## Objective
Create a 45s vertical premium launch-style evidence video. Storyboard, VO script, claim boundaries and audio direction live in `brag-plan.md` (the creative contract).

## Output
- Composition directory: `composition/`
- Rendered video: `brag.mp4`; poster `brag.jpg` baked as frame 0
- Format: vertical, 1080x1920, 45s

## Source material (only these were inspected)
README.md, both publication drafts, both episode READMEs, docs/dashboard-captures/README.md, and three captures.
Staged assets in `composition/assets/img/`: `01-performance-1440.png` (unused unless needed), `02-delivered-work-1440.png`, `ep1-direct-answer.png` and `ep1-decode-floor.png` (crops of `episode-1-dark-1440.png`).

Copy that must appear verbatim:
- "27.5% more output throughput." / "Still below the decode target."
- "Mean delivered output versus request cap"; 99.9 vs 128; cap 128
- "Decode p10 ≥ 20 tok/s"; SGLang 17.48, vLLM 15.96; 480.44 vs 376.73 tok/s
- "Tested closed-loop loads. Not capacity."
- https://github.com/KVSDURGASURESH/token-by-token

## Creative direction
Polished, high-energy but restrained. Soft slides/crossfades (0.5–0.7s), long holds. Dark UI-native look matching the dashboard (near-black, mint, orange, amber threshold marker). Engine colors differ between Episode 00 and Episode 01 captures: always label by name.

## Audio
- Role: restrained support under narration
- Music: `assets/music/happy-beats-business-moves-vol-12-by-ende-dot-app.mp3`, ~0.30 intro, 0.12–0.15 under VO
- Cue guidance: preset JSON in `assets/music/cues/` (window 0–25s only; detect beyond)
- Audio-reactive: subtle glow only
- Voice: Kokoro `af_heart` via local Hyperframes TTS; script in the plan; fit to 45s, trim script not duration
- SFX: sparse; pick from plugin library (`sfx-analysis.md`), low HF risk, ≤0.6 volume

## Hard boundaries
Local only. `HYPERFRAMES_NO_TELEMETRY=1`, `DO_NOT_TRACK=1`. Never run hyperframes cloud/publish/present/feedback/auth or any upload or hosted render. No web fonts or remote assets; everything referenced locally. No modification of benchmark evidence. Forbidden on screen: Grafana, provider endpoints/IDs, private dashboards, credentials, workload paths, endlesstokens.ai, Substack URL; no capacity, production-readiness, causal-superiority or Episode 01 cost claims.

## Verification required before delivery
`hyperframes check` clean; frame-by-frame look at every scene for text overflow and forbidden content; ffprobe: 1080x1920, ~45s, audio present; poster is a settled frame; share-copy.txt matches plan.
