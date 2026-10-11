# Brag Plan: Token by Token — Inference Lab

## What is this app?
A public, local-first learning series on LLM inference, with a static dashboard of recorded evidence that says what each experiment does and does not support.

## The angle
A premium, restrained evidence film. The hook is a result that sounds like a win and then isn't: **27.5% more output throughput, still below the decode target.** Episode 00 teaches "check the work"; Episode 01 teaches "check the target". The video is built from the repo's real dashboard captures, with no invented numbers and no imitation of any other company's launch style.

## Hook (0–6s)
Real crop of the Episode 01 dashboard headline ("SGLang recorded 27.5% more output…") with the line **27.5% more output throughput.** then **Still below the decode target.** The second line lands after a beat.

## Key moments
- **Episode 00 equal-work warning:** the real "Mean delivered output versus request cap" chart. Highlight the 8,192 tok · c32 cell: vLLM 99.9 vs SGLang 128, same cap of 128. Caption: unequal delivered work, so no equal-work efficiency claim.
- **Separation card:** Episode 00 (H100) and Episode 01 (H200) are separate experiments, not a hardware comparison.
- **Episode 01 at 16 users:** the real "Experience floor" panel. SGLang 480.44 vs vLLM 376.73 output tok/s; decode p10 17.48 (SGLang) and 15.96 (vLLM) against the 20 tok/s floor. Both "Threshold missed".
- **Boundary beat:** both met the floor at 12 users, neither at 16 or 24. Tested closed-loop loads, not capacity.

## Outro / punchline
"More tokens" and "meets the target" are different findings. Token by Token — Inference Lab. github.com/KVSDURGASURESH/token-by-token

## User flow worth showing
Open dashboard → Episode 00 delivered-work check → Episode 01, select 16 users → direct answer → experience-floor gate (threshold missed).

## Tone
- Preset: polished
- Creative direction: high-energy but restrained premium launch film; no Apple imitation, no proprietary assets
- Interpretation: confident type, long holds on real evidence, soft slides/crossfades; energy from motion and a steady bed, not flashing text.

## Format: vertical — 1080x1920
## Duration: 45s (user-specified; overrides the skill's 15–25s default)

## Visual identity (from the project's dashboard captures)
- Background: near-black (~#0a0c0d; sampled from captures, to be confirmed at composition)
- Accent: mint green (~#45d8b4) and orange (~#ff7043), both from the dashboard; amber for threshold marker
- Text: off-white
- Display font: heavy condensed grotesque, matching the dashboard headlines (Oswald-like; local fallback decided at composition, no web fetch)
- Body font: small mono / clean sans
- Strongest visual elements: EP 01 headline block, delivered-work chart, experience-floor bars with threshold marker
- **Legend caveat:** in the repo's own captures the engine colors differ between Episode 00 (SGLang orange, vLLM mint) and the Episode 01 panel (vLLM orange, SGLang mint). The video must label engines by name and never rely on color alone.

## Voiceover script (Kokoro, af_heart; ~105 words, must fit 45s)
1. (0–6) "Twenty-seven point five percent more output throughput. And it still missed the decode target."
2. (6–17) "Episode zero started with a warning. Same output cap, different delivered work: vLLM averaged ninety-nine point nine tokens against a hundred and twenty-eight. Those rates describe unequal work."
3. (17–21) "Episode one is a separate experiment."
4. (21–34) "At sixteen users, SGLang delivered four-eighty tokens a second to vLLM's three-seventy-seven. But the slow tail decoded at seventeen and sixteen, under the twenty-token floor."
5. (34–40) "Both cleared it at twelve users. Neither did at sixteen or twenty-four. These are tested loads, not capacity."
6. (40–45) "Token by Token. Evidence you can inspect, on GitHub."

## Share copy (draft)
27.5% more output throughput — still below the decode target. Token by Token's Episodes 00 and 01 on what serving measurements do and don't let us conclude. https://github.com/KVSDURGASURESH/token-by-token

## Audio direction
- Role: restrained cinematic support under narration
- Music: vol-12 ("Happy Beats / Business Moves", ende.app; plugin-licensed), ~110 BPM, steady and clean
- Music treatment: fade in 0–1.5s at ~0.30, duck to 0.12–0.15 under voiceover, brief lift in the final 3s, fade out at end
- Music cue guidance: bundled preset read. Strong cues in the 0–25s window: 8.74s, 10.93s, 13.11s; strong beats are 22.93s and 24.56s. Beyond 25s, detect at composition time. Lock only 1–3 reveals (6s scene 2 headline near 6.00/6.56; Episode 01 reveal near ~22.37; CTA). Beat-grid unused for text; readability wins.
- Audio-reactive treatment: subtle; bass/RMS breathes a soft glow behind the dashboard card. No waveform or equalizer visuals.
- SFX posture: sparse. 2–3 soft cues (one reveal impact on the hook, soft drop on the threshold-missed bars, one bell at the CTA).
- Restraint rule: nothing may mask the voice; SFX ≤0.6; no risers or stingers.

## Storyboard

### Scene 1 — Hook — 6s
Dark field. Crop of the real Episode 01 "Direct answer / 16 users" headline slides up. Type: "27.5% more output throughput." holds ~2s, then "Still below the decode target." Hold ≥2s.
Sequential/interaction: two lines, second after ~2.5s; each held ≥1.5s settled.
Audio intent: quiet confidence; music in, one soft impact on the first line.
Audio-coupled idea: none
Transition mood: soft slide → Scene 2

### Scene 2 — Episode 00 warning — 11s
Label "EPISODE 00 · H100 · exploratory". Real delivered-work chart enters, then zooms to the 8,192 tok · c32 pair; callout "99.9 vs 128 — same cap of 128". Line: "Unequal work. No equal-work claim."
Sequential/interaction: chart → zoom → two numeric callouts (vLLM 99.9, SGLang 128), each held ≥1.2s.
Audio intent: caution, slightly lower energy
Transition mood: crossfade → Scene 3

### Scene 3 — Separate experiments — 4s
Two-line card: "Episode 00 → H100." "Episode 01 → H200." Under it: "Separate experiments. Not a hardware comparison."
Sequential/interaction: lines appear one by one, hold ≥0.8s each.
Transition mood: slide → Scene 4

### Scene 4 — Episode 01 at 16 users — 13s
Simulated dashboard interaction: cursor moves on the 12 / 16 / 24 selector and lands on 16 (UI rebuilt from the capture's design; the capture itself is shown for the panel). Then the real experience-floor crop: bars fill to SGLang 17.48 and vLLM 15.96 against the 20 tok/s marker; "Threshold missed" appears on each. Output rate chips: SGLang 480.44, vLLM 376.73 tok/s.
Sequential/interaction: selection → bars fill → two threshold-missed tags.
Audio-coupled idea: one soft click on select; one soft drop when the tags land.
Transition mood: soft crossfade → Scene 5

### Scene 5 — Claim boundary — 6s
"Met at 12 users. Missed at 16 and 24." then "Tested closed-loop loads. Not capacity."
Sequential/interaction: two lines, held ≥1.5s each.
Transition mood: crossfade → Scene 6

### Scene 6 — Outro / CTA — 5s
Typographic wordmark only (the logo file is outside the inspect list), "Token by Token — Inference Lab", then "github.com/KVSDURGASURESH/token-by-token". Hold final 2s.
Audio intent: music lifts slightly, soft bell, fade.
Transition mood: end

Scene sum: 6+11+4+13+6+5 = **45s**.

**Music mood for this video:** polished, steady, restrained
**Audio summary:** quiet bed under a calm narrator, one reveal impact, two soft UI cues, a short bell at the CTA.

## Claim boundaries (enforced on screen and in VO)
- Never say capacity, maximum sustainable rate, production-ready, causally better, or give an Episode 01 cost.
- 27.5% is SGLang vs vLLM at 16 users, vLLM as denominator; say "recorded", not "faster engine".
- No Grafana, provider/service IDs, private dashboards, workload paths, endlesstokens.ai, or Substack URL. The captures were checked: none shows these.
- Do not mention the benchmarking harness beyond what the drafts' own attribution line requires; omit it from the video.

## Delivery notes (post-render)
- Final scene timings follow the generated Kokoro (af_heart, 1.05x) segments: 0–5.6, 5.6–16.4, 16.4–19.6, 19.6–32.4, 32.4–39.2, 39.2–45.0 (45.0s total).
- Scene 4 keeps the output-throughput chips on screen (dimmed) under the decode-floor evidence so the 27.5% and the missed floor read together.
- Scene 2 uses the Episode 00 chart colors (SGLang orange, vLLM mint); Scene 4 uses the Episode 01 panel's (vLLM orange, SGLang mint). Every engine is labeled by name.
- Beat locks: Scene 2 zoom at 8.74s and Scene 4 output reveal at 22.37s (strong cues); hook number on beat 0.56s.
- Audio-reactive: music RMS (10 Hz) drives a subtle background glow only.
- Local-only: Hyperframes 0.8.145 via npx, kokoro-onnx in `.tts-venv/` (inside this directory), GSAP/fonts from npm packed locally. No cloud, publish, auth or upload commands were run; telemetry disabled.
