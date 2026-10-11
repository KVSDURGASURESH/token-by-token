# Page construct: the global template for every page

Status: proposal for implementation · not yet built
Prepared: 2026-10-07, against branch `codex/episode-1-local-prep` at commit `6024d08`
Audience: the team member implementing the redesign (intended to be built with Claude Design)
Reference page: **Episode 01** (`#episode-1`) is the owner's preferred look

This document defines one page construct, a shared shell plus one episode template. Every existing and future
page uses it, in the same way a WordPress or CMS theme works. It records what is wrong with the current pages,
the target structure, the rules behind it, and how each existing page maps onto it.

Read it with the [continuation guide](CONTINUATION-GUIDE.md) and the
[interactive evidence design brief](../handoffs/2026-10-06-interactive-evidence-design-brief.md). Where those
documents and this one disagree about **page structure**, this document wins. Everything they say about
**evidence boundaries, public-data rules and metric semantics** still applies unchanged.

---

## 1. What stays and what changes

### Keep exactly as it is

These are the owner's stated preferences:

- **The visual identity of Episode 01.** That covers the palette, Oswald uppercase display type, Avenir Next body
  text, ruled editorial bands, generous negative space, and the light/dark themes.
- **The episode-first experience:** a persistent left episode list, a concise **Brief** as the default view, and
  the dense **Evidence lab** opened on demand.
- **Episode 01's content and voice.**
- **All evidence boundaries** from the continuation guide: no serving profiles, versions, flags, endpoints or
  internal recipes; no causal claims; recorded points are never interpolated.

### Change

The **construct** (layout, reading order, navigation and hierarchy) is what feels wrong. Section 2 lists the
specific anti-patterns. The fix is structural: one shell, one template, one fixed chapter order, and a small set
of rules that apply on every page.

---

## 2. Diagnosis: anti-patterns found in the current pages

These were observed by rendering `#episodes`, `#episode-0`, `#episode-1` (Brief and Evidence lab), `#episode-2` and
`#methodology` at 1440px and 390px wide.

### 2.1 Episode 01 (the reference page)

| # | Anti-pattern | Where | Why it hurts |
|---|---|---|---|
| 1 | **Controls below or to the right of what they change** (bottom-to-top and right-to-left linking) | The 12/16/24 selector sits inside the "Four signals" box, *below* the lead finding it rewrites. In the lab, "Compare deployments / Compare loads" sits top-right but changes charts ~1,500px further down. | The reader changes something at the bottom and the text above changes. Cause and effect run backwards. |
| 2 | **Explanation appears far from what was clicked** | Clicking a plot opens the "Metric explanation" panel *below the whole plot grid* | The eye has to search for the result of the click |
| 3 | **Section headings and explanations split diagonally** | Evidence boundary, Experience floor and every Methodology section: giant heading on the left, explanation aligned to the bottom-right | The eye zig-zags from heading, down-right to the explanation, then back left to the content |
| 4 | **Three menus for the same job** | Top bar (Episode 00 / Episode 01), "Choose episode +" dropdown and the left episode list | On a phone they stack, so the page title starts ~400px down. The theme switch also overlaps "Field notes" on phones. |
| 5 | **The same finding is said three times** | Evidence lab: lead finding, then "Direct answer / 16 users", then "SGLang versus vLLM at 16 users" | Repetition reads as padding and pushes evidence down |
| 6 | **Flat heading hierarchy** | The question, the finding, "Enough to understand the result." and the boundary headings are all huge uppercase Oswald | Nothing signals what matters most |
| 7 | **The episode title is not a heading** | "Measure what matters" appears only in the rail and in the label line | The page doesn't announce which episode it is |
| 8 | **Caveats too late** | "Read this before sharing" and "Not established" sit at the very bottom of the lab; the brief has one small grey line | A reader who stops at the finding never sees its limits |
| 9 | **One colour, two meanings** | Experience floor: vLLM's bar is red because red is vLLM's colour, while red elsewhere means "worse" | The guide says engine identity must stay neutral |
| 10 | **Decoration in prime space** | The "BRIEF / 1 FINDING / 4 ESSENTIAL SIGNALS" box occupies the top-right of the lead | It tells the reader nothing |
| 11 | **The rail changes shape** | "On this page" grows from 2 to 5 entries when the lab opens; "Back to the episode brief" sits mid-page | Navigation should be stable |
| 12 | **Redundant control** | The three load buttons plus a range slider for three points | The design brief itself says to prefer one compact segmented control |

### 2.2 The other pages compared with Episode 01

| Page | Problem |
|---|---|
| **Episode 00** (`PublishedRunpodStudy.tsx`) | Still the old layout: the **model name** is the title, the top of the page is six raw counters, disclosures come before results, and "How to read this study" sits at the bottom with its heading left and list right. No shell, no left list, no Brief/Evidence split. **Engine colours are reversed** relative to Episode 01: SGLang is orange and vLLM mint here, vLLM red-ish and SGLang teal there. |
| **Methodology** (`MethodologyPage.tsx`) | Its own layout with the diagonal heading pattern (#3). It describes **only Episode 01's** experiment (H200, 12/16/24 users, two sessions per user) but sits in the global menu as if it covered the series. Episode 00's method was different. |
| **Episodes index** (`EpisodeIndex.tsx`) | The older serif design at a narrower width, so it doesn't look like the episode pages |
| **Episode 02 and later** | No page. Rail links go to the Experiment Planner, and `#episode-2` falls back to the index. |
| **Top menu** (`App.tsx`) | Episode 00 and Episode 01 are hard-coded and won't scale to 17 episodes |

---

## 3. Design principles

1. **Read top to bottom, left to right.** Anything that controls content sits above it. Anything that explains
   content sits directly below it.
2. **Answer first, then mechanism, then exact evidence.** This is unchanged from the design brief, and the
   chapter order enforces it.
3. **One place for each thing.** One episode menu per device, one statement of the finding, one control bar.
4. **Stable structure, variable content.** Every episode has the same chapters in the same order. Status (recorded,
   fixture or planned) only changes what fills them.
5. **Caveats travel with claims.** Limits sit next to the finding, not at the end of the page.
6. **Identity is not judgement.** Engine colours never use the better/worse colours.

---

## 4. The global shell (every page)

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ TOKEN BY TOKEN / INFERENCE LAB    EPISODES  METHODOLOGY  FIELD NOTES  LAB TOOLS ▾  [LIGHT|DARK] │  A
├────────────────┬─────────────────────────────────────────────────────────────────┤
│ B  LEFT LIST   │  MAIN COLUMN                                                    │
│                │                                                                 │
│ EPISODES       │  (page content — see §5 for the episode template)               │
│  00 Warm-up    │                                                                 │
│ ▌01 Measure…   │                                                                 │
│  02 Equal-work │                                                                 │
│  ⋮ scrolls     │                                                                 │
│                │                                                                 │
│ ON THIS PAGE   │                                                                 │
│  01 Brief      │                                                                 │
│  02 Method     │                                                                 │
│  03 Evidence   │                                                                 │
│  04 Boundaries │                                                                 │
│  05 Source     │                                                                 │
├────────────────┴─────────────────────────────────────────────────────────────────┤
│ ← 00 Warm-up                                    02 Equal-work runtime baseline → │  G
└──────────────────────────────────────────────────────────────────────────────────┘
```

### A. Site bar

- Same content, position and font on every page, including the index, Methodology, Field notes and lab tools.
- Left: wordmark `TOKEN BY TOKEN / INFERENCE LAB`, linking to `#episodes`.
- Menu: **Episodes · Methodology · Field notes · Lab tools ▾**. The Lab tools group holds Local results, Quick test,
  Experiment planner, Episode runner and Canonical launch.
- **No per-episode links in the bar.** Remove the hard-coded "Episode 00" and "Episode 01" items.
- The Light/Dark switch lives **inside** the bar, at the right end. It is no longer a separately positioned element,
  which fixes the phone overlap.
- On an episode page, "Episodes" shows as the current section (`aria-current="true"`), and the left list holds
  `aria-current="page"`.

### B. Left list (desktop ≥ 981px)

- **Navigation only.** It holds two blocks:
  1. **Episodes**: all 17 from `data/episodes.json`, scrollable, each with number, title and status. Planned episodes
     link to their own planned page (§6.3), **not** to the planner.
  2. **On this page**: the episode's chapters, **always the same five** (§5.2). Clicking 02–05 while the lab is
     closed opens the lab, then scrolls to the chapter. The current chapter is highlighted as the reader scrolls.
- Move the big "EP 01", the state label and What/Why/How out of the rail and into the main column (§5.1, §5.3).
- On non-episode pages (index, Methodology, Field notes), "On this page" lists that page's own sections. The
  Episodes block stays.

### B′. Phone and tablet (≤ 980px)

- The left list collapses into **one** dropdown: `Episode 01 · Measure what matters ▾`.
- "On this page" becomes a horizontal row of chapter chips under the dropdown.
- There is never more than one episode menu on screen.

### G. Pager

Previous and next episode as two cards (number and title). It appears on every episode page, including planned
ones.

### Main column width

There is one content width for every page. Header, facts strip, control bar, sections and tables all align to the
same left and right edges. Today the Episode 01 warning/lead blocks and the facts row have different widths;
remove that difference.

---

## 5. The episode template

### 5.1 Region C: episode header

```
 Episodes / Episode 01                                         ← breadcrumb
 EPISODE 01 · RECORDED STUDY                                   ← label (teal, small caps)
 MEASURE WHAT MATTERS                                          ← H1 = episode title (largest text)
 WHAT BREAKS FIRST WHEN TWO INFERENCE ENGINES                  ← the question (smaller, muted)
 MEET THE SAME H200 WORKLOAD?
 [ RECORDED · EXPLORATORY · CAPACITY NOT ESTABLISHED ]         ← status chip (amber outline)
 ┌──────────────┬───────────────────┬─────────────────┬──────────────────┐
 │ HARDWARE     │ ENGINES           │ MEASURED LOADS  │ WINDOW           │  ← facts strip
 │ 1× H200      │ ● vLLM  ◆ SGLang  │ 12 · 16 · 24    │ 2m warm · 5m     │
 └──────────────┴───────────────────┴─────────────────┴──────────────────┘
```

- **H1 is always the episode title** from the catalog, so every episode announces itself the same way. The
  question becomes the deck beneath it, smaller and muted, still Oswald uppercase.
- The facts strip has four cells, its content set per episode. It replaces today's provenance line and Episode 00's
  six raw counters.
- Fixture or exploratory evidence uses the status chip. If an episode needs a stronger warning (as the old
  Episode 1 fixture did), use a full-width banner at the **same width** as the facts strip.

### 5.2 Fixed chapter order

| # | Chapter | Purpose | Visible by default |
|---|---|---|---|
| 01 | **Brief** | The finding, four signals and what it does not say | Yes |
| 02 | **Method** | This episode's setup and protocol; links to global Methodology for definitions | In the evidence lab |
| 03 | **Evidence** | Linked plots, thresholds, per-engine readouts, exact table | In the evidence lab |
| 04 | **Boundaries** | Matched vs deployment-specific; observed vs not established | In the evidence lab |
| 05 | **Source** | Provenance, public data file, how to reproduce | In the evidence lab |

With the lab closed, chapters 02–05 still appear as **greyed heading rows** under the Brief. The reader can see the
whole page structure, and the rail entries stay valid.

### 5.3 Region D: sticky control bar

```
 ████ MEASURED LOAD [ 12 |▐16▌| 24 ] users · recorded points only, never interpolated ████
```

- **One** control bar, placed directly under the header, **above** every chapter. It stays fixed to the top while
  scrolling, so the control always sits above whatever it changes.
- Brief view: the measured-load segmented control only.
- Evidence lab: adds **Compare [Engines at this load | Loads within each engine]** to the same bar. "Baseline" and
  "Pin current point" appear **only** in "Loads" mode.
- **Remove the range slider.** Three recorded points need three buttons.
- Episodes without a load dimension change the control's label and values, not its position (§6.1). Planned
  episodes hide the bar.
- Remove the control currently inside the Four-signals box and the large "Move through the evidence" section.

### 5.4 Chapter 01: Brief (default view)

```
 01 / BRIEF
 ENOUGH TO UNDERSTAND THE RESULT.                         ← section heading
 One finding, four signals and what the evidence does not say.   ← explanation, directly under heading
 ───────────────────────────────────────────────────────────────
  WHAT                  │ WHY                   │ HOW            ← moved from the left list
 ───────────────────────────────────────────────────────────────
 RECORDED OBSERVATION / 16 USERS
 SGLANG RECORDED ↑ 27.5% MORE OUTPUT AND                   ← the finding, stated ONCE on the page
 ↓ 26.8% LOWER MEDIAN TTFT THAN VLLM.
 Matched load, one H200. Deployment comparison only.
 ┌──────────────┬──────────────┬──────────────┬──────────────┐
 │ THROUGHPUT   │ TTFT P50     │ TPOT P50     │ DECODE P10   │
 │ higher better│ lower better │ lower better │ higher better│
 │ ● 376.7 tok/s│ ● 2,789.8 ms │ ● 49.5 ms/tok│ ● 16 tok/s   │
 │ ◆ 480.4 tok/s│ ◆ 2,041.9 ms │ ◆ 27.7 ms/tok│ ◆ 17.5 tok/s │
 │ ✓ 27.5%      │ ✓ 26.8%      │ ✓ 44.1%      │ ✓ 9.5%       │
 └──────────────┴──────────────┴──────────────┴──────────────┘
 ┃ WHAT THIS DOES NOT SAY                                  ← caveats beside the finding (amber rule)
 ┃ • Capacity was not established under the declared service objectives.
 ┃ • This is a recorded deployment comparison, not an engine-only benchmark.
 ┃ • Both engines miss the 20 tok/s decode floor at 16 users.
 ───────────────────────────────────────────────────────────────
 Want the mechanism and exact evidence?          [ OPEN EVIDENCE LAB ↓ ]
 ───────────────────────────────────────────────────────────────
 02  METHOD        ┐
 03  EVIDENCE      │ greyed rows: "in evidence lab"
 04  BOUNDARIES    │
 05  SOURCE        ┘
```

Values shown are Episode 01 at 16 users, taken from the current page.

- Remove the "BRIEF / 1 FINDING / 4 ESSENTIAL SIGNALS" box.
- "What this does not say" pulls 2–3 items from the episode's limitations. It must always appear in the Brief.
- Opening the lab **does not replace the Brief**. Chapters 02–05 expand below it, and the button becomes
  "Collapse lab ↑". This removes the need for a mid-page "Back to the episode brief" button.

### 5.5 Chapters 02–05: evidence lab

```
 ████ MEASURED LOAD [12|▐16▌|24]  │  COMPARE [▐Engines at this load▌| Loads within each engine] ████

 01 BRIEF (unchanged, above)                                        [ COLLAPSE LAB ↑ ]

 02 / METHOD
 ONE GPU. TWO ENGINES. THREE MATCHED PRESSURE POINTS.
 explanation paragraph
 [ Users 12→16→24 | Session slots 24→32→48 | Gate: decode p10 ≥ 20 tok/s | Validity: ≤1% failed ]
 → How the session replay works        → Metric definitions (Methodology)

 03 / EVIDENCE
 ENGINES AT 16 USERS                         ← heading only; the finding is NOT repeated
 Runtime configurations differ; capacity not established; <2% shown as ≈ unchanged.
 ┌ EXPERIENCE FLOOR ─────────────────────────────────────────────┐
 │ ● vLLM    ▓▓▓▓▓░░░│░░░░  16 tok/s    ✕ Threshold missed       │  bar colour = outcome
 │ ◆ SGLang  ▓▓▓▓▓▓░░│░░░░  17.5 tok/s  ✕ Threshold missed       │  (met green / missed red)
 └───────────────────────────────────────────────────────────────┘
 ┌ OUTPUT THROUGHPUT (selected) ─────┬ VISIBLE TTFT P50 ──────────┐
 └───────────────────────────────────┴────────────────────────────┘
 ┌ EXPLAINING: OUTPUT THROUGHPUT ──────────────────────────────────┐  ← opens directly under the
 │ unit · direction · source │ definition + caveat │ values 12/16/24 │    row that holds the clicked
 └─────────────────────────────────────────────────────────────────┘    plot
 ┌ TPOT P50 ──────────┬ WAITING REQUESTS ──────┬ GPU BOARD POWER ───┐
 └────────────────────┴────────────────────────┴────────────────────┘
 ┌ ● vLLM · 665/666 valid ─────────┬ ◆ SGLang · 889/889 valid ──────┐
 │ 7 readouts vs the other engine  │ 7 readouts vs the other engine │
 └─────────────────────────────────┴────────────────────────────────┘
 ▸ OPEN EXACT MEASUREMENT TABLE

 04 / BOUNDARIES
 A DEPLOYMENT COMPARISON, NOT AN ENGINE-ONLY VERDICT.
 Read this before sharing. The public bundle holds measured outcomes, not serving recipes.
 ┌ What is matched ───────────────┬ What remains deployment-specific ┐
 ├ The declared gate ─────────────┼ Result boundary ──────────────────┤
 ├ Observed ──────────────────────┼ Not established ──────────────────┤
 └────────────────────────────────┴───────────────────────────────────┘

 05 / SOURCE
 WHERE THESE NUMBERS COME FROM
 Provenance line · Selecting a load changes the view only; it never reruns the benchmark.
 Public data file ↗ · Reproduce with the public binary → · Methodology →

 ← 00 Warm-up                                  02 Equal-work runtime baseline →
```

Changes from today's Episode 01 lab:

- **Merge** `runtime-answer` ("Direct answer") and `comparison-summary` ("Observation") into one chapter heading. In
  "Engines" mode the heading is "Engines at N users" with the caveat line. In "Loads" mode it is "Compared with N
  users" followed by each engine's own change.
- **The metric explanation panel moves** directly under the plot row that holds the active plot.
- **Experience floor bars use outcome colours** (met = green, missed = red). Engines are identified by marker and
  name only.
- **Merge** "Evidence boundary / Do not skip" and "Read this before sharing" into chapter 04.
- Move the "One GPU. Two inference engines…" opening (`instrument-opening`) into chapter 02.

### 5.6 Region G and footer

The pager (§4) closes every episode page. The source line now lives in chapter 05, so there is no separate
footer line beneath the pager.

---

## 6. Status variants: one template, different fill

| Region / chapter | Recorded (Ep 00, Ep 01) | Fixture (legacy Ep 1 fixture) | Planned (Ep 02–16) |
|---|---|---|---|
| Header label | `EPISODE NN · RECORDED STUDY` | `EPISODE NN · LOCAL FIXTURE` | `EPISODE NN · PLANNED` |
| Status chip / banner | Amber chip | Full-width amber banner: "Local fixture — not provider measurement" | Chip: "Planned — no measurements" |
| Facts strip | Measured facts | Declared protocol facts | Candidate facts (all marked unverified) |
| Control bar | Yes | Yes, if the fixture has a dimension | **Hidden** |
| 01 Brief | Finding, four signals, caveats, Open evidence lab | Same, every number labelled synthetic | "No results yet": what it will measure + **Design this experiment →** + **Read roadmap stage ↗** |
| 02 Method | Episode setup | Declared protocol | Planned method (from the roadmap stage) |
| 03 Evidence | Full lab | Full lab, synthetic labels | Greyed: "Appears after a recorded run" |
| 04 Boundaries | Observed / not established | Fixture limits | "Planned proposal, not a result or authorization to spend" |
| 05 Source | Data file, reproduce | Fixture file and hash | Roadmap and planner links |
| Pager | Yes | Yes | Yes |

### 6.1 Episode 00 mapped onto the template

| Region | Content |
|---|---|
| Label | `EPISODE 00 · RECORDED STUDY · EXPLORATORY` |
| H1 | **Warm-up** (replaces the model name "Qwen2.5-32B-Instruct runtime study") |
| Question | "How did vLLM and SGLang behave serving Qwen2.5-32B-Instruct on one H100?" |
| Facts strip | Hardware: one H100 80GB per run · Engines: ● vLLM 0.29.0 ◆ SGLang 0.5.20 · Model: Qwen2.5-32B-Instruct BF16 · Requests: 936, 0 failures |
| Control bar | **WORKLOAD** segmented control with the six categorical cells `128·c1 B │ 128·c16 S │ 2,048·c4 B │ 2,048·c24 S │ 8,192·c8 B │ 8,192·c32 S`, labelled "categorical workloads, not a sweep". Per the design brief, Episode 00 must **not** become a numeric load sweep. |
| 01 Brief | Finding for the selected cell, plus four signals: **delivered output rate, TTFT p50, TPOT p50, and mean delivered output vs the configured cap**. Where delivered output differs between engines (the long-context cells), the output-rate signal shows amber "≈ unequal work, not comparable" instead of better/worse. "What this does not say" includes "No winner is claimed" and the unequal-work caveat. |
| 02 Method | Closed-loop synthetic workload; six input-length/concurrency cells; 2–3 repetitions; BF16, 16,384-token context, prefix caching and chunked prefill on both arms |
| 03 Evidence | Today's `ScientificCharts`, `TelemetryCharts` and exact comparison table, unchanged in content. **Restyle engine colours to the shared identity tokens (§7.4)**: today SGLang is orange and vLLM mint. |
| 04 Boundaries | Today's "Study disclosures" (Compatibility, Exclusions, Preflight facts, Future work) and "How to read this study" |
| 05 Source | Sanitized public aggregate, checksums, `docs/results.md`, reproduction notes |

Reference values for the 8,192-input, concurrency-32 cell, from `episodes/00-warm-up/README.md`:

| Metric | vLLM | SGLang |
|---|---|---|
| Delivered output rate | 57.5 tok/s | 43.7 tok/s |
| TTFT p50 | 47.9 s | 88.3 s |
| Mean delivered output | 99.89 tokens/request | 128.00 tokens/request |
| Configured output cap | 128 tokens/request | 128 tokens/request |

### 6.2 Episode 01 mapped onto the template

This is covered by §5. The content is today's `Episode1Instrument.tsx`, `LinkedMetricInstrument.tsx` and
`LoadSweeper.tsx`, rearranged into the chapters. Methodology's session-replay material moves in as well (§6.4).

### 6.3 Episode 02 (planned) mapped onto the template

| Region | Content |
|---|---|
| Label | `EPISODE 02 · PLANNED` |
| H1 | **Equal-work runtime baseline** |
| Deck | Catalog summary: "Compare HF/PyTorch, vLLM and SGLang under the same model, corpus, template and output contract." Don't invent a question; use the summary until the owner writes one. |
| Facts strip | Model: selected in planner · Hardware: candidate, availability unverified · Engines: vLLM · SGLang · control · Status: not execution-ready |
| Control bar | Hidden |
| 01 Brief | "No results yet", a short "What this episode will measure" taken from `docs/roadmap.md#equal-work-runtime-baseline`, and two actions: **Design this experiment →** (`#experiment-planner?episode=2`) and **Read roadmap stage ↗** |
| 02–05 | Same headings with planned placeholders, as in the table above |

Every planned episode (03–16) uses this variant automatically from `data/episodes.json`. The catalog fields
`title`, `summary`, `model`, `hardware`, `runtimes` and `roadmapAnchor` already exist.

### 6.4 Methodology: a global page in the same shell

```
 METHODOLOGY · APPLIES TO ALL EPISODES
 HOW THE LAB MEASURES
 deck: definitions before conclusions
 01 Metric definitions    TTFT, TPOT, decode p10, output throughput, goodput, completion validity,
                          contextual telemetry (today's "definition-ledger")
 02 Evidence rules        recorded vs fixture vs planned; recorded points never interpolated;
                          unavailable is labelled, never plotted as zero
 03 Reading the colours   outcome colours vs engine identity (§7.4)
 04 Episode protocols     cards linking to each episode's chapter 02:
                          → Ep 00 closed-loop categorical cells   → Ep 01 session replay
```

- Today's Methodology content that is **specific to Episode 01** moves into **Episode 01 → 02 Method**. That covers
  the 50/30/20 population, request anatomy, two-session replay, protocol gates and aligned evidence. The interactive
  components (`RequestAnatomy`, `SessionReplay`, `EvidenceViews`) move with it and are not rewritten.
- The global page keeps only what applies to every episode.
- Section headers use the stacked pattern (§7.1). The current giant-left-heading, bottom-right-paragraph layout goes.

### 6.5 Episodes index and Field notes

- Both use the global shell (site bar, left list with no current episode, pager not shown).
- **Index:** keep the series introduction and the list of 17 episodes, restyled to Episode 01's typography and
  width so the site no longer switches design between pages. Each row shows number, status label, title (Oswald),
  summary and actions. Planned rows link to their planned page (§6.3).
- **Field notes** (`SessionCapacityStudy.tsx`) was not reviewed for this proposal. Apply the same template, with
  label `FIELD NOTE` instead of `EPISODE NN`.

---

## 7. Rules every page follows

### 7.1 Section header anatomy

```
 01 / BRIEF                       ← label: 11px, 600, letter-spacing .16em, uppercase, teal
 ENOUGH TO UNDERSTAND THE RESULT. ← section heading (H2)
 One-line explanation.            ← 16px body, muted, max ~70ch
 [content]
```

All four parts are left-aligned and stacked vertically. Never place the heading on the left with its explanation
on the right or bottom-right.

### 7.2 Placement rules

1. A control sits **above** the content it changes, never below it and never in a far corner.
2. A click opens its result **directly under** what was clicked.
3. The finding is stated **once** per page.
4. Each device has **one** episode menu: the left list on desktop, the dropdown on phone.
5. Caveats sit **next to** the claim they qualify.
6. Every chart has a one-line "what to notice" caption (from the continuation guide).

### 7.3 Type scale

There are four heading levels and the gaps between them must stay visible. Font: Oswald (`"Oswald Variable"`),
uppercase. Body: `"Avenir Next", Avenir, Helvetica, sans-serif`.

| Role | Desktop | Phone | Weight | Notes |
|---|---|---|---|---|
| Page title (H1) | ~104px, line-height .9 | ~54px | 700 | Episode title only |
| Deck / question | ~36px, line-height 1.05 | ~26px | 500 | Muted ink |
| Finding | ~52px, line-height 1.02 | ~34px | 600 | Outcome-coloured phrases inside |
| Section heading (H2) | ~44px, line-height 1 | ~32px | 600 | |
| Panel heading (H3) | ~22–26px | ~20px | 600 | |
| Label | 11px, .16em tracking | 10px | 600 | Teal, uppercase |
| Body | 16px / 1.55 | 15px | 400 | Max ~70ch |
| Small / caption | 12–13px | 12px | 400–500 | Muted |

### 7.4 Colour: two systems that never mix

Use the existing tokens in `dashboard/src/styles.css`. Light-theme values are shown; dark-theme values come from the
`:root` block.

**Surface and text:** `--paper #fbfaf5`, `--panel #f1f0e9`, `--panel-soft #e8e8e1`, `--line #d3d8d1`,
`--line-strong #98a8a2`, `--ink #172f2d`, `--copy #455a56`, `--muted #596965`, `--safe` (teal, labels and current
state) `#006d6b`.

**Outcome:** used only for a stated comparison.

| Meaning | Token | Light | Symbol |
|---|---|---|---|
| Better | `--better` | `#006d45` | ✓ / ↑ or ↓ in the favourable direction |
| Worse | `--worse` | `#b22f18` | ✕ / arrow in the unfavourable direction |
| Unchanged / caution / unequal work | `--neutral` | `#8a5b00` | ≈ |

**Engine identity:** neutral, told apart by lightness, marker and line style, never by outcome colours.

| Engine | Colour | Marker | Line |
|---|---|---|---|
| vLLM | `--ink` | ● circle | solid |
| SGLang | `--muted` | ◆ diamond | dashed |
| A third arm, if ever needed | `--line-strong` | ■ square | dotted |

Add these as new tokens (for example `--engine-a`, `--engine-b`) and use them in **both** Episode 00 and Episode 01
charts. Today's `.arm-vllm`/`.arm-sglang` red/teal rules and Episode 00's `runtimeColors` orange/mint map are
replaced.

### 7.5 Spacing and grid

- Page side padding: 40px desktop, 14–16px phone. No horizontal page scroll at any width; wide tables and plots
  scroll inside their own box.
- Rail width ~230px with a 48px gap to the main column.
- Vertical rhythm: 56–64px between chapters, ~28–36px between blocks inside a chapter.
- Ruled bands (1px `--line`) and bordered panels as Episode 01 uses them today. No rounded cards or gradient washes.

### 7.6 Accessibility

- Real `<button>` and `<a>` elements. Segmented controls use `role="group"` with `aria-pressed`.
- Comparison text that updates uses `aria-live="polite"`, as it does today.
- Touch targets ≥ 44px. Text contrast ≥ 4.5:1 (3:1 at 24px and above).
- Outcome is never shown by colour alone: always pair it with ✓ / ✕ / ≈ and words.
- Respect `prefers-reduced-motion`, as the current code does.

---

## 8. Phone layout (390px)

```
 TOKEN BY TOKEN                 [MENU] [☀/☾]
 [ Episode 01 · Measure what matters  ▾ ]      ← the single episode menu
 01 Brief · 02 Method · 03 Evidence · …         ← chapter chips, horizontal scroll
 EPISODE 01 · RECORDED STUDY
 MEASURE WHAT MATTERS
 question…
 [status chip]
 facts strip as 2 × 2
 ███ MEASURED LOAD [12|16|24] ███                ← sticky
 01 BRIEF
   What / Why / How stacked
   finding
   four signals stacked (one per row)
   what this does not say
   [ OPEN EVIDENCE LAB ↓ ] full width
 02–05 greyed rows
 pager (stacked)
```

---

## 9. Implementation map

These are suggestions for the implementer. Names are indicative; keep to the surrounding code's style.

| New / changed piece | Based on | Notes |
|---|---|---|
| `SiteBar` | `App.tsx` nav + `ThemeSwitch.tsx` | Remove per-episode links; theme switch inside the bar |
| `EpisodeTemplate` (generalized shell) | `instrument/EpisodeShell.tsx` | Rail = episode list + fixed 5 chapters; header region C; control-bar slot; chapter slots; pager. Drop the "Choose episode" dropdown on desktop and use it as the phone menu. |
| `ControlBar` | `instrument/LoadSweeper.tsx` + `comparison-mode` in `Episode1Instrument.tsx` | One sticky bar; no slider; pin only in Loads mode |
| `SectionHeader` | the `header` blocks repeated across components | One component for label, heading and explanation |
| `PlannedEpisode` | new | Driven entirely by `data/episodes.json` |
| Episode 01 content | `Episode1Instrument.tsx`, `instrument/LinkedMetricInstrument.tsx` | Rearrange into chapters 01–05; merge duplicate answer blocks; move explanation panel; outcome-coloured threshold bars |
| Episode 00 content | `PublishedRunpodStudy.tsx`, `ScientificCharts.tsx`, `TelemetryCharts.tsx`, `studyPresentation.ts` | New Brief with a workload selector; existing charts and table move into chapter 03; disclosures into chapter 04; engine colours to identity tokens |
| Methodology | `MethodologyPage.tsx`, `methodology/*` | Split: global definitions/rules page + Episode 01 chapter 02 |
| Index | `EpisodeIndex.tsx` | Restyle to Episode 01 typography and width inside the shell |
| Routing | `App.tsx` | Every catalog episode gets `#episode-N`; planned episodes render `PlannedEpisode` |
| Styles | `styles.css` | Add one "page template" layer with the tokens from §7; retire per-page header variants (`.study-identity`, `.episode1-hero`, `.instrument-hero`, `.method-hero`) once pages move over |

**Preserve earlier work:** item 7 of the continuation guide says not to delete earlier concepts. Keep the current
pages reachable under non-default routes during the transition, for example `#episode-0-classic`, alongside the
existing `#episode-1-fixture`.

**Shareable URL state** stays: `load`, `mode`, `baseline` and `depth` (lab open or closed) in the hash, as today.

---

## 10. Acceptance checklist

A page passes when all of these hold at 1440, 768, 542 and 390px:

- [ ] Site bar identical on every page; theme switch inside it; no overlap at 390px.
- [ ] Exactly one episode menu visible per width.
- [ ] H1 is the episode title; the question is the deck.
- [ ] Header, facts strip, control bar and content share one left and right edge.
- [ ] The control bar sits above every chapter and stays fixed while scrolling; no control sits below content it
      changes.
- [ ] The finding text appears exactly once in the page's DOM.
- [ ] "What this does not say" is visible in the Brief without opening the lab.
- [ ] "On this page" lists the same five chapters with the lab open or closed.
- [ ] Clicking a plot opens its explanation directly beneath that plot's row.
- [ ] Every section header is stacked: label, heading, explanation.
- [ ] No outcome colour (better, worse, neutral) is used to identify an engine.
- [ ] Episode 00 and Episode 01 use the same engine colours and markers.
- [ ] Episode 00 workloads stay categorical, with no numeric-sweep affordance.
- [ ] Every planned episode has its own page with "Design this experiment" and the pager.
- [ ] No horizontal page scroll at any width; no network requests beyond the static bundle.
- [ ] Evidence-boundary rules from the continuation guide still hold (no profiles, versions, flags, endpoints).

### Tests that will need updating

These tests encode today's structure, so they need intentional updates alongside the redesign:

- `tests/dashboard_instrument_acceptance.cjs`: expects the question as a heading, the "Choose episode" button,
  What/Why/How labels, two `nav [aria-current="page"]`, the range slider "Tested load", "Back to the episode brief",
  and Brief/Lab swapping (not appending).
- `tests/dashboard_interactive_evidence_contract.cjs`: source-text assertions on `Episode1Instrument.tsx`,
  `LinkedMetricInstrument.tsx` and `EpisodeShell.tsx` (for example `Back to the episode brief`, `instrument-lead`,
  `episode-scroll`).
- `tests/dashboard_methodology_contract.cjs` and `tests/dashboard_methodology_acceptance.cjs`: expect the
  population, anatomy, replay and gate content on `MethodologyPage.tsx`.
- `tests/dashboard_series_acceptance.cjs`: expects the "Table of contents" heading, `.published-study-table` on
  `#episode-0`, and an "All episodes" link.

Baseline on 2026-10-07 at `6024d08`, before any redesign work:
- **Already failing:**
  - `dashboard_instrument_contract.cjs` expects model family `Qwen3.8 27B`, but the public data now says
    `Matched model family`.
  - `dashboard_series_acceptance.cjs` times out looking for the removed "All episodes" link.
- **Need specific setup:**
  - `dashboard_planner_acceptance.cjs` hard-codes port 5173.
  - `dashboard_offline_acceptance.cjs` needs a built `dashboard/dist`.
- **Passed:** the other tests.

---

## 11. Decisions already made

- Episode 01 is the visual and editorial reference for every page.
- Chapter order is fixed: Brief · Method · Evidence · Boundaries · Source.
- The Brief is the default view, and the evidence lab opens on demand **below** it.
- Operator tools stay grouped under **Lab tools**.

## 12. Open items for the owner

1. **Episode 00's question line.** The proposed wording is in §6.1; the owner should confirm it.
2. **Planned-episode deck.** Use the catalog summary for now, or write a question for each of Episodes 02–16.
3. **Engine identity colours.** The ink and muted pairing in §7.4 is the proposal. Confirm, or pick two neutral
   tones that work in both themes.
4. **The Field notes page** was not reviewed for this proposal.

## 13. Out of scope

- New evidence, data rebuilds or changes to the public evidence contract.
- Changes to lab tools (Quick test, Planner, Runner, Canonical launch) beyond placing them in the shared site bar.
- Publication copy (LinkedIn and Substack drafts).
- Merging to `main` or publishing externally. Both require the owner's approval, per the continuation guide.
