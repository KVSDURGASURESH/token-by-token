---
name: token-by-token-video
description: Build evidence-safe Token by Token launch videos locally — validate brand, claims and music gates, capture the real dark dashboard, hand a checked package to Claude Code /brag, and QA the result. Use for methodology or episode video previews and signature-music auditions; never publishes.
---

# Token by Token video

Produce reviewable, local-only launch videos from the real dashboard. The dashboard and `assets/token-by-token.svg` are the brand authority; nothing is recreated or approximated.

## Boundaries (read first)

- Everything except the Anthropic model call itself runs locally. Disable Hyperframes/brag telemetry (`HYPERFRAMES_NO_TELEMETRY=1`, `DO_NOT_TRACK=1`).
- Never publish. No cloud rendering, feedback upload, hosting, deployment, social posting, browser login, or provider infrastructure. Every handoff is marked not published with `not-published.json`.
- Never read private benchmark evidence, credentials, endpoints, Grafana, or service identifiers.
- Do not invent claims, measurements, URLs, screenshots, dashboard controls, logos, or fonts.
- Music: auditions may use the bundled `/brag` tracks locally. The final master and any publication handoff are blocked until the owner selects a track and reusable rights are documented in `references/music-lock.json`.

## Workflow

Apply the owner-approved recurring visual/editorial requirements in `references/editorial-direction.v5.md` to methodology and subsequent episode videos.

1. Read `docs/superpowers/specs/2026-10-10-token-by-token-video-system-design.md` and the per-video spec in `video/specs/`.
2. Validate: `python skills/token-by-token-video/scripts/validate.py --spec <spec> --stage audition|preview|master [--offline] --json`. Checks `references/video-spec.v1.schema.json`, `references/brand-lock.json`, `references/music-lock.json`, claim traces, forbidden text, conditional website policy.
3. Capture the real built dashboard on loopback with `scripts/capture.mjs` (real clicks, scrolls, route changes; dark theme only). A route notice, console error, wrong hash, or brand drift stops the run. With `--crop-plan <spec>.crop-plan.json` every frame is audited so forbidden text (e.g. episode content) never enters a rectangle the composition may show.
4. Auditions: `scripts/mix_audio.py audition` produces three same-narration, loudness-normalized candidates. The owner chooses; never choose for them. `scripts/afro_beds.py` synthesizes original local beds when the owner asks for a custom Afro-EDM direction (`references/music-lock.afro-edm.v2.json`).
5. Preview: `scripts/render.sh` validates, builds the brief, and invokes Claude Code `/brag` with no network tools or publication authority. `/brag` composes; it does not reinterpret brand or copy.
6. QA: `scripts/qa.py` checks codec, size, fps, duration, full decode, poster at frame zero, audio, true peak, manifests, forbidden text, and the not-published marker.
7. Stop at the owner gate: music selection and rights, preview notes. Only then render the master (`--stage master`). Episode videos start only after methodology approval.

See `video/README.md` for exact maintainer commands.
