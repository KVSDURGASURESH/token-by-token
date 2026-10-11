# Methodology video — revision 4 (TOO EZ sync pass) review notes

**Status: LOCAL PREVIEW ONLY. Publication and use as a master are blocked.** See `../not-published.json`.

This is the permanent methodology/introduction video. It is not an episode video. It contains no episode catalogues, episode plans, model rankings or new measurements.

## Music

| Item | Value |
| --- | --- |
| Source | Owner-supplied local file `TOO-EZ-Instrumental-version.aac` |
| Source offset | **00:20.000** (segment 00:20.000–01:14.500, 54.5 s) |
| Extracted segment | `cue-analysis/assets/music/too-ez-from-20s.wav` |
| Beat map | `cue-analysis/beats/assets/music/too-ez-from-20s.wav.json` (detector 210 BPM; musical feel 105 BPM) |
| Rights | **Unverified.** No license or download evidence is recorded (`inputs/music-lock.too-ez.v4.json`) |

## Audio

This pass did not change the mix. `composition/assets/audio/preview-mix.wav` is the prepared vocal-safe mix, used as supplied. The values below come from the prepared-input brief. **They were not re-measured in this pass:**

- Integrated loudness: ~-16.1 LUFS-I
- True peak: ~-2.0 dBTP
- Narration-over-music margin: ~17.71 dB

## Composition changes (`composition/index.html`)

Unchanged: narration, copy, claims, scene boundaries (0, 5, 12.5, 25, 34, 43, 50, 54.5 s), total duration (54.5 s), dashboard captures, SVG logo, wordmark treatment, fonts and URL. Row and check highlight times stayed fixed because they follow the narration. Only reveal, pan and accent timings moved.

### Beat-sync decisions

- **Glow (opening and end card).** Removed the 10 Hz RMS-driven flicker. Its data came from the earlier temporary bed, not TOO EZ, and it read like a visualizer. The `rms` array is still in the file but nothing uses it.
  - Opening glow now breathes once on each strong cue: 0.667, 1.524, 2.381, 2.953, 3.810, 4.381.
  - End-card glow is one slow breath from the soft 50.096 cue, with a small settle at 53.238.
- **Opening (0–5 s).**
  - Lockup enters at 0.667.
  - Descriptor and rule enter at 0.953. The rule sweep ends on 1.524.
  - Headline lines enter at 1.524, 1.81 and 2.381; the quote at 2.953. Each moved at most +0.32 s.
  - New: a thin cyan underline under "Every token is a measurement." sweeps 3.810 → 4.381. The copy is unchanged.
- **First transition.** The wipe still starts at 5.0; its midpoint falls on 5.238. The scene-2 heading and the first tick pulse now land on 5.238.
- **Header ticks.**
  - Replaced the fixed 0.5 s (120 BPM) pulse grid, which drifted against the 105 BPM track. Pulses now fire only on the listed strong cues.
  - Scene 2 gets softer pulses (7.524, 8.953, 12.096) because the music is thin there.
  - No pulses in the 25–33.5 s breakdown. 33.524 marks the lift.
- **Workloads (12.5–25 s).**
  - Each dashboard pan shifted by ≤0.15 s so it lands on a strong cue: 18.096, 20.381, 22.096, 23.524. The drift keyframes after each pan shifted with it.
  - Dropped one 2.4 px drift step (it ended at 22.95 s) so it doesn't overlap the next pan.
  - The strip border lifts to cyan once at the 16.667 drop. After the final Brag readability review, the note "Not every source feeds every study" enters on the strong 22.667 cue and holds for about 2.1 seconds before the wipe.
- **Breakdown at 25 s.** No heavy hit: the wipe slows to 0.9 s sine with a 35% opacity edge. The dashboard cut reopens on the soft 28.953 pulse, before the 29.25 highlight.
- **Measurement lift (34–43 s).**
  - Heading and strip enter on 34.381, with one border lift.
  - Rows enter at 34.953.
  - The dashboard cut reopens on 39.524.
- **Evidence (43–50 s).**
  - Heading enters at 43.238; boundary lines from 43.524. Pans start on 44.096 and 45.524; the second now arrives as "Observed, not inferred." highlights.
  - Fix: in revision 2, "Work before speed." brightened at 43.05, before its 43.5 entrance, which then left it at 55% opacity. It now enters at full strength.
- **End card (50–54.5 s).** Softer edge on the wipe. Lockup enters at 50.381, rule and descriptor at 50.667, quote at 50.953. The URL timing is unchanged.

## Verification (finish pass, 2026-10-11)

The beat-sync pass had no shell, so this follow-up pass ran the checks. It made no edits to `composition/index.html`. All commands ran from `revision-4/`. Hyperframes was the preinstalled local binary exposed as `$HF`, v0.8.146. It was run without `npx` and nothing was fetched. Telemetry was already off: `hyperframes telemetry status` → `disabled`, source `HYPERFRAMES_NO_TELEMETRY`.

- [x] **Hyperframes check**: `$HF check composition`
  - Result: `Check passed`.
  - Lint: 0 errors, 10 warnings. The warnings are structural advisories: `duplicate_media_discovery_risk` ×1, `composition_file_too_large` ×1 (327 lines), `nested_structure_needs_subcomposition` ×8 (`#sc1`–`#sc7` and `#hdr-clip`). They were left alone because splitting the verified source into sub-compositions is out of scope.
  - Runtime: 0/0. Layout: 0 issues across 9 samples. Motion: 0/0. Contrast: 53/53 WCAG AA.
- [x] **Seam check**: `$HF check composition --at-transitions --at 3.81,4.381,5.238,16.667,25.45,33.524,43.524,50.381`
  - Result: `Check passed`. Same lint result. Runtime 0, Motion 0, Contrast 35/35.
  - Layout: 0 errors, 0 warnings, 1 info: `t=5.273s text_occluded #s2-h span "first" inside #edge`. This is the intended 5.0 s wipe edge crossing the scene-2 heading mid-transition.
- [x] **Render**: `$HF render composition --fps 30 --quality delivery --format mp4 --video-frame-format png --output preview/methodology-preview-too-ez-synced.mp4`
  - Result: `Render complete`, 1635/1635 frames.
  - The only warning line was the lint summary.
- [x] **FFprobe**: `ffprobe -v error -show_entries format=duration,size,bit_rate:stream=index,codec_type,codec_name,profile,width,height,pix_fmt,r_frame_rate,avg_frame_rate,nb_frames,duration,sample_rate,channels,channel_layout -of default=nw=1 preview/methodology-preview-too-ez-synced.mp4`
  - Video: `h264` High, 1080x1350, yuv420p, `30/1` r/avg, duration 54.500000, 1635 frames.
  - Audio: `aac` LC, 48000 Hz, stereo, duration 54.500000, 2556 frames.
  - Format: duration 54.500000, size 13415447 bytes, bit_rate 1969239.
- [x] **Full decode**: `ffmpeg -nostdin -hide_banner -v error -i preview/methodology-preview-too-ez-synced.mp4 -f null -`
  - Exit 0, no output (no decode errors).
- [x] **Loudness on the render**: `ffmpeg -nostdin -hide_banner -nostats -i preview/methodology-preview-too-ez-synced.mp4 -vn -af ebur128=peak=true -f null -`
  - I: **-16.1 LUFS**. True peak: **-2.0 dBFS**. LRA 2.1 LU.
  - Both match the prepared mix.
- [ ] **Narration-over-music margin (~17.71 dB) not re-measured.** That needs separate stems, and only the final mix is in the render. The mix was passed through unchanged.
- [x] **Contact sheet**: `ffmpeg -nostdin -hide_banner -v error -y -ss 1.0 -i preview/methodology-preview-too-ez-synced.mp4 -vf "fps=1/2.25,scale=270:-2,tile=6x4:padding=4:color=0x111111" -frames:v 1 -q:v 3 preview/contact-sheet.jpg`
  - Output: 1640x1364 MJPEG, 24 tiles, row-major, sampled about every 2.25 s from ~1.0 s.
  - No burned-in timestamps: this FFmpeg build has no `drawtext` filter.
- [x] **Poster**: `ffmpeg -nostdin -hide_banner -v error -y -i preview/methodology-preview-too-ez-synced.mp4 -vf "select='eq(n\,138)'" -frames:v 1 -fps_mode passthrough -q:v 2 preview/poster.jpg`
  - Output: 1080x1350, frame 138 (t = 4.6 s).
  - Chosen against the 53.5 s end card (`preview/inspect/poster-candidates-4.6s-53.5s.jpg`). The opening hook shows the logo, wordmark, the full headline, and the completed `#s1-ul` underline.
  - The poster was **not** baked in as frame 0. That would change the verified render.
- [x] **Visual inspection** (the agent viewed the images directly: `poster.jpg`, `contact-sheet.jpg`, `inspect/*.jpg`):
  - The SVG logo and the "TOKEN **BY** TOKEN" wordmark (orange BY) appear in the opening, the header and the end card.
  - Dark dashboard styling throughout. All text is inside the frame. The `#s1-ul` underline clears the quote's descenders.
  - No episode catalogue, episode plan, model ranking or new measurement. The only "ranking" text is the existing claim "Unequal work blocks ranking."
  - The evidence strip is blank at ~46.8–47.5 s (`inspect/evidence-45.5-47.0s.jpg`). This is the scene's own `#cv6` cover-wipe cut (closes 46.823, reopens 47.322), not a missing asset.
  - The owner should still review the motion at full speed with sound. Stills cannot show beat feel.

Housekeeping: one scratch still went to `/tmp/rev4-evidence-strip.jpg` by mistake. Deleting it needed approval, and none was available in that session, so it is still there. It contains only a frame of this render and was not uploaded anywhere.

## Brag creative-authority review (after verification)

See `../BRAG-REVIEW.md`. One change: `#s3-note` now enters at 22.667 s, not 23.524 s, for readability. The preview, contact sheet, seam check, media probe, full decode and loudness measurement were regenerated after this change.

## Publication blocker

Music rights are unverified. Even after the render passes every check, this package stays a local preview. Publication needs license/download evidence and the intended publishing channels recorded in a new music lock.

## Independent parent-agent verification

After the Claude `/brag` pass completed, the parent agent independently verified the final artifact:

- Hyperframes seam/cue check: passed; 0 runtime errors, 0 layout errors/warnings, 0 motion errors/warnings, 35/35 contrast checks. The one layout info item is the intentional 5.273 s transition wipe.
- FFprobe: H.264 High + AAC LC, 1080x1350, 30 fps, 1635 frames, 54.500 s.
- Full FFmpeg decode: passed with no errors.
- Render loudness: -16.1 LUFS-I, -2.0 dBTP, LRA 2.1 LU.
- Token by Token video-pipeline unit suite: 135 tests passed.
- Offline spec validation: passed; `tokenbytoken.org` remains omitted because DNS/HTTPS was intentionally not checked offline.
- Contact sheet visually reviewed: exact lockup and dark styling are present; methodology-only content remains legible; no episode catalogue or episode plan appears.

Final post-Brag render SHA-256: `dfaf1e63be87faca8447792878e995bdb6015e961d2c3ba7327848bed852059c`.
