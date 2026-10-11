---
name: token-by-token-video
description: Create or revise Token by Token methodology and episode videos with Claude Brag, the approved signature music, real dashboard actions, and verified public measurements. Produces local review artifacts and reusable rendering specs.
---

# Token by Token video

Use Claude Code Brag for creative composition. Codex prepares evidence, captures the real UI, mixes local Kokoro narration, and verifies the result. The approved methodology reference is `docs/publication-drafts/2026-10-10-methodology-video/revision-6/`.

Read [production-contract.json](references/production-contract.json) and [editorial-direction.v5.md](references/editorial-direction.v5.md) for each new video. Read [workflow.md](references/workflow.md) for commands and the spec format.

## Permanent identity and motion

- Exact canonical SVG and dashboard wordmark: uppercase Oswald Variable 600, `.055em` tracking, orange BY. Opening descriptor: **The Inference Lab**.
- Dark dashboard palette; blended real UI excerpts, kinetic typography, restrained musical accents. Avoid screenshot boxes, harsh separator lines, fabricated controls, and abstract visualizers.
- Scroll down naturally with a fixed camera. Capture every delivery frame at 30 fps. Never stack reversing camera motion over scrolling footage. Use exact first/last source frames for holds. Settled text and cameras stay still.
- Use the owner-selected TOO EZ instrumental beginning at **00:20.000**, local Kokoro `af_heart`, and speech-dominant mixing. Music selection persists; licensing evidence remains a separate publication gate.
- Penultimate scene shows the subject's real dashboard action: methodology scroll, or the respective episode's selector/evidence interaction.
- End with an evidence-safe episode measurement or catchy benchmarking quote, exact brand, GitHub link, dashboard URL, and a stationary, high-contrast portal QR (at least 260px including quiet zone, at least 3s settled hold).

## Evidence and authority

Use only public dashboard JSON and public documentation. Bind every factual statement to an excerpt or JSON pointer; derive displayed numbers from those values. Distinguish recorded comparisons, validity, threshold attainment, and capacity. Do not infer causal engine superiority or sustainable capacity. An episode video covers its own episode; the earlier mixed Episode 00/01 film is only a motion reference.

User-requested video creation authorizes local preparation, authenticated Claude composition, and verification. Do not ask for the same approval repeatedly. Do not publish, upload, deploy, provision infrastructure, or read private benchmark evidence/credentials. Disable renderer telemetry. Stage only approved public evidence and media into Claude's isolated output directory; deny web tools and broad repository shell access.

## Repeatable workflow

1. Create a versioned JSON spec under `video/specs/` with scenes, claims, captures, quote and URLs. Confirm current public values, then run `pipeline.py validate`.
2. Run `pipeline.py prepare`, `capture`, and `audio`. Outputs contain locked source hashes, real 30fps frame sequences, capture manifests, narration and music mix, QR, and a focused Claude brief.
3. Run `pipeline.py compose`: Claude reads the staged Brag skill and latest rules, creates the composition, checks it, renders it and writes review artifacts. Preserve prior outputs.
4. Run `pipeline.py verify`; inspect the poster, every scene, transitions, real interaction clips, and QR. For scrolling revisions, use `audit_motion.py` on the rendered scrolling region. A clean decode alone does not establish visual quality.
5. Return the playable MP4 and concise changes/results. Stop at owner review. Record music rights and portal availability honestly; local drafts may show the requested portal with verification pending.

For unattended **local rerenders**, `pipeline.py rerender` uses the saved composition and source files, then verifies the output. `pipeline.py run` performs the full preparation-to-review workflow from a spec. Creative generation may vary between Claude runs; deterministic automation means locked inputs, explicit timelines/actions, checked commands and manifests, not a promise of bit-identical AI compositions or hardware video encodes. Do not create a recurring schedule without a requested cadence.
