# Local production workflow

Run from the repository root. No command publishes. Supply a new output directory per creative revision; `prepare` refuses to overwrite an existing input manifest.

```sh
python3 skills/token-by-token-video/scripts/pipeline.py validate --spec video/specs/episode-01.v2.json
python3 skills/token-by-token-video/scripts/pipeline.py run --spec video/specs/episode-01.v2.json --out docs/publication-drafts/2026-10-11-episode-01-video/revision-1 --music /Users/durgasuresh/Downloads/TOO-EZ-Instrumental-version.aac
```

Individual stages: `prepare`, `capture`, `audio`, `compose`, `verify`, `rerender` (same `--spec` / `--out`). `run` performs all stages. `rerender` renders the saved composition and verifies it; it never regenerates the story or narration.

To replace just one capture after correcting its action, run `node skills/token-by-token-video/scripts/capture.mjs --out <revision-directory> --shot <capture-id>`. The manifest preserves the other shots. Captures clamp and freeze their actual starting scroll position, so opening a note cannot trigger a viewport jump when the document grows.

Requirements: Python with local Kokoro/soundfile, installed local model/voices/synth helper, Node and dashboard Playwright/Vite, installed Chromium, FFmpeg/FFprobe, cached Hyperframes, authenticated Claude Code. The script discovers local paths and accepts `--tts-python` and `--hyperframes`. It never downloads runtimes, models, browsers or fonts. A local QR encoder is required; `TBT_QR_LIBRARY` can point to an existing installation. Missing dependencies stop with a concrete error.

`compose` sends only the staged public package to Anthropic. The restricted Claude session has package file access and an allowlist for local Hyperframes/FFmpeg/FFprobe; web tools are denied. Authentication remains with Claude, never with the video script.

## Spec v2

- `slug`, `episode`, `duration`, `scenes` (`id`, `start`, `duration`, `narration`, `text`, `claims`).
- `claims`: `id`, public `source`, and either `pointer` plus exact `value`, or an `excerpt` present in the source.
- `captures`: `id`, dark `route`, target `selector`, `duration`, downward `travel`, optional real button `click` / `click_at`, viewport/crop. Clicks are real Playwright clicks and scrolling uses real page scroll positions.
- `closing_quote`, `qr_url`, `qr_hold_seconds`, `music_offset` (20), `width`, `height`, `fps`.

Scene timelines must be contiguous and sum to the duration. Capture records every delivery frame, logs scrollY, and refuses upward reversals. Route changes start a new shot. Configuration capture may mask unrelated cost/next-episode sections; record masks in the manifest.

Validate exact JSON values, then use sensible rounded labels. Keep engine names visible: color alone does not identify an engine. Source/spec fingerprints reveal stale inputs after dashboard changes.

## Verify and review

The verifier checks full decode, dimensions, CFR/frame count, duration, codecs, audio loudness/peak, review markers and source/spec fingerprints. Claude runs the visual browser check. Independently inspect animated seams, scroll direction, settled-text motion, actual note unfolding, and a decoded QR from a rendered end frame. Record findings in `preview/REVIEW-NOTES.md`.

Music selection is settled; publication clearance requires rights evidence. Portal availability requires an actual HTTPS check. Neither follows from a successful local render. Owner review and publication are separate from this local workflow.
