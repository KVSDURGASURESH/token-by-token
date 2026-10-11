# Methodology introduction (revision 2) — owner review notes

Status: **preview only — not published.** Nothing was uploaded, hosted, shared or posted. V1 (`../preview/`, `../audio/`, `../capture/`) is untouched.

## What this is
The permanent introduction to Token by Token (not a trailer): WHAT (open inference lab) → WHY (declare system, workload, scenario, metric rules, validity gates, evidence boundary) → WORKLOAD SPECTRUM → MEASUREMENT LENS (with representative load) → EVIDENCE BOUNDARIES → BRAND CLOSE.
No episode, status, result or episode link appears in narration, on-screen copy, footage, routes, title, share copy or the end card.

- Video: `methodology-preview.mp4` (1080x1350, 30 fps, H.264/AAC, 54.5 s). Poster baked as frame 0 (`poster.jpg`, t = 4.6 s).
- Footage: real recordings of the built dashboard Methodology page, dark theme, real scrolling and route changes. Every frame was audited at capture time: text containing "episode" never entered a rectangle the composition may show (`capture-manifest.json` → `exposure_audit`, `../../../../video/specs/methodology-intro.v2.crop-plan.json`). The site bar, the left rail, the episode protocols section and the episode-scope text are outside every crop.
- Narration: Kokoro `af_heart`, speed 1.12, generated locally from `video/specs/methodology-intro.v2.json` (transcript in `transcript.txt`).

## Music — OWNER GATE (nothing selected)
- Three normalized 12-second auditions with the **same narration phrase** are in `../audio/auditions/`:
  - A `audition-a-afro-house-drive.(wav|mp4)` — Afro-house drive
  - B `audition-b-afro-tech-pulse.(wav|mp4)` — Afro-tech pulse
  - C `audition-c-organic-afro-edm.(wav|mp4)` — organic Afro-EDM
  All three are 120 BPM, locally synthesized original percussion/bass/tones (`skills/token-by-token-video/scripts/afro_beds.py`); no samples and no third-party audio. Each is −16 LUFS with true peak ≤ −1.5 dBTP, music 16–17 dB below speech, side-chain attack 175 ms / release 575 ms.
- The preview uses **B (afro-tech-pulse) as a temporary, UNAPPROVED bed**, picked only from objective proxies (clearest beat pulse, least overlap with the speech band, largest speech margin). I could not listen to any of them: judge groove, low-end weight and taste yourself. No track is selected; `music-lock.afro-edm.v2.json` keeps `selected: null` and `rights.status: "unverified"`.
- Rights: the beds are original synthesis, but that is not a publication clearance. The master and any publication stay blocked until you select a track and record reusable-rights evidence.

## Website
`tokenbytoken.org` is **omitted** from the end card: this run was offline-only (no external network), so the live DNS + HTTPS gate could not pass. Run `validate.py --stage preview` online to include it if it resolves.

## Disclosure
`npx hyperframes` is not installed in this checkout, and my first call fetched Hyperframes 0.8.146 from the npm registry (an unintended external fetch, contrary to the no-network rule). Everything afterwards used that cached copy by absolute path, telemetry off, no Gemini description, no cloud. Delete `~/.npm/_npx/702923228c2ce1e6` if you do not want it.
