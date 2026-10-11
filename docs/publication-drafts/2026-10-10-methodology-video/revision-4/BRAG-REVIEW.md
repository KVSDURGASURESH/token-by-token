# Brag creative-authority review — methodology video, revision 4

**Status: LOCAL PREVIEW ONLY. Publication and master use stay blocked** (`not-published.json`).

## Skill confirmation

I read all of `brag-skill/SKILL.md` (`/brag-slim`) and used it as the creative authority for this review. I then read `CLAUDE-TASK.md`, `preview/REVIEW-NOTES.md`, `not-published.json` and `composition/index.html`.

Where the owner's constraints conflict with Brag defaults, the owner's constraints win. These defaults were **not** applied:

- the 15–25 s length;
- the hook → reveal → highlights → punchline re-cut;
- new tone or copy;
- a new soundtrack or mix.

These stay fixed:

- 54.5 s at 1080x1350;
- the narration, copy and claims;
- the methodology-only scope;
- the logo, wordmark, fonts and URL;
- the dashboard captures;
- the TOO EZ audio from 00:20.000 and its prepared mix;
- the scene boundaries 0 / 5 / 12.5 / 25 / 34 / 43 / 50 / 54.5 s.

Inside those limits, I checked the composition against each Brag law.

## Creative verdict

**Approved with one small timing fix.** The composition meets the Brag laws that still apply under these constraints. Only one point clearly failed a law: the readability of one line. I fixed it and did not change anything else.

| Brag law | Verdict |
| --- | --- |
| **Hook** | Pass, with one caveat. The first beat (0.667 s) brings in the real logo and wordmark. "An open inference lab." is fully on screen by about 3.0 s, and the thesis line follows with a beat-locked underline. Frames 0–0.667 are near-empty: dark paper and faint glow. That is a deliberate breath before the first strong music cue. Starting earlier would break the music sync, so I left it. The thumbnail question is a delivery issue, covered under gates below. |
| **Show the thing** | Pass. Real dashboard captures pan, cut and land on cues in every content scene (2–6). Nothing is a mock-up or abstract filler. |
| **Specific** | Pass. Every line is the project's own methodology language ("Declared first", "Representative load", "Observed, not inferred.", "Unequal work blocks ranking."). There is no generic SaaS copy. |
| **Clear to a stranger** | Pass. The video says what it is (an open inference lab), how it works (declared, representative, measured, bounded) and where to find it (the GitHub URL on the end card). |
| **Readable (~0.3 s/word once settled)** | **One failure, now fixed.** The opening headline and quote, the scene headings, the rows (each highlighted on its narration cue), the evidence lines and the end-card quote and URL all hold long enough. Scene 3's note "Not every source feeds every study" (6 words, needs ~1.8 s) entered at 23.524 s. It settled at about 23.9 s, and the 25.0 s wipe reaches its left edge at about 25.13 s. That left only ~1.2 s to read it. |
| **Alive** | Pass. Rows stagger in, checks fire on narration, the dashboards pan, cover-wipes cut between captures, and section wipes run on the scene boundaries. Nothing sits static for long. |
| **Every frame postable** | Pass. The transitions are hard-edged clip-path wipes, not crossfades, so no frame shows two layouts muddied together. The seam checks in REVIEW-NOTES found no overflow and passed every contrast check. The near-empty frames 0–0.667 are clean, just not rich. |
| **Music and motion** | Pass. Accents fall only on strong 105-BPM-feel cues, never on every double-time transient. The 25 s breakdown gets a slow, soft wipe and no tick pulses. The lift returns at 33.524/34.381, and the end card resolves on the soft 50.096 cue. The header tick pulses are 5 px, so they don't read as a visualizer. The vocal-safe mix is untouched. |

## Composition changes

There is exactly one change, in `composition/index.html` (scene 3):

- **`#s3-note` entrance moved from 23.524 s to 22.667 s.** 22.667 is a strong cue from the prepared beat map, and the `#tk2` header tick already pulses on it, so the music sync holds. The note is now settled from about 23.0 s, which gives roughly 2.1 s of reading time before the 25 s wipe, up from about 1.2 s.
  - The copy, position, easing and 0.5 s duration are unchanged.
  - The narration, scene boundaries and row/check highlight times are unchanged.
  - Side effect: the note now appears about 0.6 s before row 06 highlights (23.3 s), not after it. The note is a caveat on the whole list, so I accept that order. **The owner should confirm at full speed with sound** that it doesn't run ahead of the spoken line.

I considered these and left them unchanged:

- **Starting the opening lockup at 0 s.** It would break the first-cue sync, and the hook already lands inside 2 s.
- **Baking the poster into frame 0.** That is a delivery step on the rendered file, not a composition change. It is listed under gates.
- **Removing the unused `rms` array.** It has no visual effect, so I didn't churn it.
- **Retiming any other reveal, pan or accent.** These already pass the laws above.

## Re-render required: **completed by the parent agent**

The preview, poster and contact sheet initially predated this change. The parent agent subsequently completed the same render and checks recorded in `preview/REVIEW-NOTES.md`:

1. Run the Hyperframes check, and the seam check with `22.667` and `24.9` added to `--at`.
2. Render at 30 fps, 1080x1350, 1635 frames, 54.5 s, H.264/AAC.
3. Run FFprobe and a full decode.
4. Re-measure loudness. The audio input is unchanged, so expect -16.1 LUFS-I and -2.0 dBTP.
5. Regenerate the contact sheet.

The Brag review pass itself could not run shell commands. The parent agent subsequently ran the requested seam check (including 22.667 and 24.9), rendered all 1635 frames, regenerated the contact sheet and poster, verified H.264/AAC at 1080x1350 / 30 fps / 54.5 s, performed a clean full decode, and re-measured -16.1 LUFS-I / -2.0 dBTP.

## Remaining owner and publication gates

1. **Music rights (blocking).** The owner-supplied TOO EZ instrumental (`TOO-EZ-Instrumental-version.aac`, from 00:20.000) still has no recorded license or download evidence and no intended publishing channels. `inputs/music-lock.too-ez.v4.json` lists rights as unverified. Publication and master use stay blocked until a new music lock records them.
2. **Owner review at full speed with sound.** Confirm the beat feel, and confirm the earlier scene-3 note doesn't run ahead of the narration.
3. **Narration-over-music margin (~17.71 dB) is still not re-measured.** It needs stems. The mix itself is unchanged.
4. **Thumbnail decision (optional, owner's call).** Brag's delivery step bakes the poster in as frame 0, and this render doesn't do that. If the target platform uses frame 0 as the thumbnail, it will show the near-empty opening frame. Replacing frame 0 keeps the duration and audio sync, but it adds a one-frame flash and changes the verified render.
5. Nothing was uploaded, hosted, deployed or published.
