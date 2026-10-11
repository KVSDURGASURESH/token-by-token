# Claude Code `/brag` task — Token by Token methodology video, TOO EZ sync pass

Invoke and use the full `/brag` skill as the creative/compositing authority for this revision. You are running inside an isolated, self-contained `revision-4` directory containing only the approved video package. Do not try to inspect parent directories or the rest of the repository. Follow the no-publication requirements below.

Do not publish, upload, host, deploy, log in, or use WebFetch/WebSearch. Do not change the narration, claims, methodology-only scope, verified dashboard captures, exact SVG logo, exact Token by Token wordmark treatment, fonts, URLs, or duration. Do not introduce episode catalogues, episode plans, model rankings, or unsupported measurements.

## Owner direction

- Use the owner-supplied audio file `/Users/durgasuresh/Downloads/TOO-EZ-Instrumental-version.aac` beginning at exactly source time `00:20.000`.
- Match the video action to the music while keeping vocals dominant.
- This is the permanent methodology/introduction video direction, not an episode video.
- The track's reusable publication rights have not been documented. Everything must remain a local preview and clearly blocked from publication/master use.

## Prepared, authoritative inputs

- Verified composition source and its required local assets: `composition/index.html` and `composition/assets/`
- Existing synchronized base preview with the requested music offset: `preview/methodology-preview-too-ez-base.mp4`
- Vocal-safe 54.5-second mix: `audio/preview/preview-mix.wav` (already copied into the composition)
- Extracted 00:20–01:14.5 music segment: `cue-analysis/assets/music/too-ez-from-20s.wav`
- Hyperframes beat map: `cue-analysis/beats/assets/music/too-ez-from-20s.wav.json`
- Versioned music/rights lock: `inputs/music-lock.too-ez.v4.json`

The prepared mix measures approximately `-16.1 LUFS-I`, `-2.0 dBTP`, and `17.71 dB` narration-over-music margin. Preserve those audio characteristics. Do not remix unless a technical render requirement makes it unavoidable.

## Timing direction

The narration timeline and total duration are authoritative. Do not move scene copy or narration boundaries merely to chase beats. Instead, use tasteful micro-timing inside each scene: entrance reveals, underline sweeps, token/pulse accents, dashboard scroll starts/stops, section-title hits, and end-card resolve.

The beat detector reports 210 BPM, equivalent to the track's 105 BPM musical feel. Favor the stronger musical pulses rather than animating every double-time transient.

Current scene boundaries are `0.0`, `5.0`, `12.5`, `25.0`, `34.0`, `43.0`, `50.0`, `54.5` seconds. Useful strong cues from the prepared beat map include:

- opening: `0.667`, `1.524`, `2.381`, `2.953`, `3.810`, `4.381`
- first transition: `5.238`
- workload sequence: `16.667`, `17.524`, `18.096`, `18.953`, `19.810`, `20.381`, `21.238`, `22.096`, `22.667`, `23.524`, `24.381`
- measurement/evidence lift: `33.524`, `34.381`, `34.953`, `35.810`, `36.381`, `37.238`, `38.096`, `38.667`, `40.381`, `40.953`, `41.810`
- evidence/end sequence: `42.667`, `42.953`, `43.524`, `44.096`, `44.953`, `45.524`, `46.381`
- softer close cue near `50.096`

There is a deliberate musical breakdown around the `25.0`-second scene boundary. Let that transition breathe; do not force a heavy hit where the track has none.

## Work requested

1. Inspect the existing verified revision-2 composition and prepared revision-4 inputs.
2. Refine the self-contained revision-4 composition in `composition/`, preserving exact brand and source content.
3. Use `/brag` judgment to retime or add restrained motion accents to the useful musical cues above. The motion should feel deliberate and premium, not like a visualizer. Keep dashboard text legible and scrolling purposeful.
4. Render the synchronized local preview to `preview/methodology-preview-too-ez-synced.mp4` at 1080x1350, 30 fps, exactly 54.5 seconds, H.264/AAC.
5. Generate a poster and contact sheet, then visually inspect them for exact logo/wordmark, dark dashboard styling, text safety, and absence of episode content.
6. Write `preview/REVIEW-NOTES.md` and `not-published.json`. Record the exact 00:20 source offset, local owner-supplied file, measured audio values, beat-sync decisions, and the explicit rights/publication block.
7. Run Hyperframes checks, full decode, and FFprobe. Fix any issue within this isolated package.

Do not modify unrelated dirty files. Do not commit. Stop at local review artifacts and report exactly what changed, what passed, and any remaining publication blocker.
