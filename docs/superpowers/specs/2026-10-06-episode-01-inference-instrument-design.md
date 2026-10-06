# Episode 01 Inference Instrument design

**Date:** 2026-10-06  
**Status:** Proposed for owner review  
**Scope:** Dashboard information architecture, Episode 01 experience, recorded field-note experience, and a normalized telemetry-import boundary  
**Preservation rule:** The four design-spike concepts in the Codex visualization workspace remain unchanged and are not production assets.

## Purpose

Turn Token by Token from a conventional results dashboard into an authored, interactive inference study. A reader should understand what was tested, why it matters, how it was measured, and what changed at a selected load without first scrolling through inventory or generic metric cards.

The primary audience is inference engineers, technical founders, and GPU platform teams. Success means that a new reader can:

1. identify the current episode or field note and its evidence status;
2. choose a recorded load and see linked latency, throughput, validity, and telemetry evidence;
3. understand change relative to the preceding measured point or an explicitly pinned point;
4. distinguish an observation from an inference or recommendation; and
5. see unavailable evidence as unavailable rather than as zero, a placeholder result, or an implied prediction.

## Identity and evidence model

The public information architecture is:

| Entry | Public identity | Evidence state |
|---|---|---|
| Episode 00 | Warm-up: existing H100 runtime study | Recorded, exploratory |
| Episode 01 | Measure what matters: SGLang vs vLLM on H200, one controlled optimization at a time | Draft until matching evidence is imported |
| Field note | When more users mean more waiting: RTX PRO 6000 and H200 deployments using vLLM | Recorded, exploratory |
| Episodes 02–16 | Existing roadmap subjects and numbering | Planned unless evidence exists |

Episode 01 does not inherit measurements from the field note. The field note remains available as a recorded example inside the shared reading experience, but its hardware comparison never populates Episode 01 runtime lanes.

The existing Episode 01 measurement-contract fixture becomes methodology evidence for Episode 01 rather than a result. The catalog receives an explicit revision; historical identities are preserved through the existing numbering-migration metadata.

Editorial state and evidence state are separate:

- **Recorded:** validated, publishable measurements exist; missing metric families may still be unavailable.
- **Draft:** experiment question, arms, and method exist; no measurements are attached.
- **Import pending:** a run package exists but has not passed validation and sanitization.
- **Planned:** a readable question and intended method exist; no result visualization is shown.

## Considered approaches

### A. Restyle the current Session Study

This is the smallest change, but it preserves the current separation between interaction and evidence, keeps operational tools in the primary navigation, and cannot represent draft and import-pending episode states cleanly.

### B. Build separate page designs for every episode

This permits maximum art direction but duplicates metric behavior, evidence rules, accessibility, and import handling. It will drift as the series grows.

### C. Shared Inference Instrument shell — selected

Use one evidence-aware episode shell whose content and controls adapt to each study's declared data contract. Episode 01 and the recorded field note have distinct identities and datasets, but share navigation, guided chapters, comparison semantics, charts, and evidence-status components.

This approach provides a coherent series without pretending that different studies share the same experimental design.

## Product structure

Primary reader navigation becomes:

- **Episodes**
- **Field notes**
- **Methodology**
- **Lab tools** — planner, quick test, runner, import status, and canonical launch

The episode selector is an editorial list, not a card carousel. Every entry shows its number or field-note label, title, evidence state, and one-sentence question. Selection reveals:

- **What:** the comparison being made;
- **Why:** the decision the experiment informs;
- **How:** the matched work, load sweep, metrics, and evidence boundaries;
- one state-specific action such as Explore results, Read experiment, Review import status, or Read outline.

For Episode 01:

- **What:** Compare SGLang and vLLM on H200 across a baseline and explicitly defined optimization arms.
- **Why:** Find which controlled changes improve useful output, response time, or resource use under the declared workload.
- **How:** Replay matched work at recorded load levels and inspect latency, failures, quality, and aligned telemetry.

Before evidence is imported, the page states: **“H200 comparison planned; results have not been imported.”** It shows the planned arms, method, and missing-evidence inventory without skeleton charts or sample results.

## Visual direction: Inference Instrument

The visual language comes from laboratory instruments and scheduler timelines rather than SaaS dashboards or agent consoles.

### Tokens

The Episode 0 palette remains authoritative:

- paper `#080a0b`
- panel `#111617`
- panel-soft `#171d1e`
- ink `#f2f5ef`
- muted `#9aa4a1`
- line `#283133`
- line-strong `#465154`
- accent `#ff6a38`
- safe `#4bdcaf`
- warning `#f0ba4b`

No new decorative colors, gradients, or ambient glow are introduced. Series identity uses direct labels, marker shapes, and line styles. Verdict color is separate from runtime or deployment identity.

The condensed display face remains for concise study questions. A readable sans serif carries explanations and controls; tabular numerals carry measurements. Uppercase labels and monospace metadata are used only where they encode instrument state, identifiers, or units.

### Layout

At approximately 1440 × 900, the first viewport contains:

```text
┌ Token by Token ─ Episode selector ─ Methodology ─ Lab tools ┐
├───────────────┬──────────────────────────────────────────────┤
│ Episode/state │ Which changes improve serving on H200?      │
│ What          │ provenance · evidence boundary              │
│ Why           ├──────────────────────────────────────────────┤
│ How           │ arm selector     tested-load ruler          │
│ chapters      ├───────────────────────┬──────────────────────┤
│               │ Output throughput     │ TTFT                 │
│               │ linked selected point │ linked selected point│
│               ├───────────────────────┴──────────────────────┤
│               │ value · baseline · delta · bounded insight  │
└───────────────┴──────────────────────────────────────────────┘
```

The desktop rail is approximately 200 pixels wide and remains visually quiet. On mobile it becomes compact chapter navigation above the instrument. The page uses one continuous ruled surface instead of repeated floating metric cards.

The guided reading path is:

1. **Choose the load:** select a discrete measured point; inspect throughput, TTFT, TPOT, failures, and immediate deltas.
2. **Inspect the trade-off:** inspect full sweeps, optimization arms, queueing, KV cache, GPU, memory, and power where available.
3. **Judge the evidence:** inspect quality and SLO contracts, repetitions, configuration differences, coverage, limitations, provenance, and downloadable sanitized evidence.

Below the first viewport:

- Optimization-arm matrix with exactly one changed variable per declared arm where possible.
- Runtime-behavior small multiples for queue depth, queue wait, KV cache, GPU utilization, memory, and power.
- Sustained-run comparison, clearly separated from sweep measurements.
- Method, configuration, evidence boundaries, and source package.
- One next-episode continuation describing what will improve, without promising an outcome or date.

## Load sweeper and comparison behavior

The control selects indices into recorded load levels; it never interpolates. For the field note these levels are `2, 4, 8, 16, 32, 64, 100` simulated users.

The sweeper supports:

- pointer dragging that snaps to a tested level;
- discrete buttons as an equivalent control;
- Arrow keys for adjacent points and Home/End for the extremes;
- accessible value text such as “64 simulated users, measured level 6 of 7.”

The default baseline is the preceding lower measured point in the same series and measurement type. At 64 users the default comparison is 32 users. At the first point the UI states “First measured point; no previous comparison.”

**Pin comparison** permits a deliberate non-adjacent basis such as 16 → 64. The selected point, comparison point, study arm, and measurement type remain visible beside every delta. Changing between sweep and soak resets incompatible baselines and explains why.

The load selection synchronizes every compatible plot and readout. The current point is solid, the baseline point is outlined, and exact values are available in text and a table.

## Motion

The memorable interaction is one moving measurement ruler across linked consequences.

When the selected load changes, a slim marker moves between fixed load ticks across aligned throughput and latency plots. The baseline marker remains outlined. Difference brackets reveal the absolute and relative changes. The axes and measured points never move, and numerical values never tween through invented intermediate results.

- Selection settles in approximately 160 milliseconds.
- Rapid input cancels obsolete motion; the latest selection wins.
- Configuration changes preserve compatible load and baseline selections.
- Hover or keyboard focus synchronizes the same point across plots.
- There is no autoplay, ambient pulsing, particle field, simulated queue population, or scroll hijacking.
- Under reduced motion, markers and brackets update immediately with identical information.

## Metric vocabulary and explanations

Every metric uses its real name, unit, statistic, measurement boundary, and a one-line interpretation.

| Metric | Required explanation | Direction |
|---|---|---|
| Output throughput | Successful output tokens divided by the declared measurement duration. | Higher is favorable only for this metric. |
| TTFT p50 / p95 | Time from the declared request-start boundary to first visible content. | Lower is favorable. |
| TPOT p50 / p95 | First-to-last content span divided by exact output tokens minus one. | Lower is favorable. |
| Failed / invalid requests | Requests that did not meet the recorded completion-validity contract. | Lower is favorable. |
| Runtime queue depth | Requests waiting for admission according to the runtime-native metric. | Contextual; rising can be concerning. |
| Runtime queue wait | Time spent in the server queue where directly measured. | Lower is favorable. |
| KV-cache occupancy | Used capacity as a share of the runtime-reported KV-cache capacity. | Contextual. |
| GPU utilization | Device utilization sampled during the aligned measurement window. | Contextual. |
| GPU memory used | Device memory consumption during the aligned measurement window. | Contextual. |
| GPU board power | Sampled board power in watts during the aligned measurement window. | Contextual. |

Each graph includes one visible sentence describing its axes, statistic, and purpose. Example: “Each point shows p95 visible TTFT at one tested load; higher points mean a longer wait for initial output.”

Client-visible TTFT is never labeled as server queue time. A native queue metric is shown only if its source and definition are present.

## Delta semantics

For compatible measurements:

- absolute change is `current − baseline`;
- relative change is `(current − baseline) / baseline × 100`;
- rate changes show percentage-point movement prominently;
- zero baselines show absolute change and “relative change unavailable”;
- missing evidence shows an em dash and a reason, never zero.

Status combines text, symbol, and color:

- `✓ Improved` in safe green;
- `↓ Regressed` in red derived through accessible use of the existing accent treatment;
- `≈ Within tolerance` or `◇ Contextual change` in warning orange.

“Within tolerance” is used only when a declared metric-specific practical tolerance exists. It does not assert statistical equivalence. Contextual metrics such as GPU utilization and power do not receive automatic good/bad verdicts.

The field note supports the explicit pinned observation:

> **Observed, H200 sweep, 16 → 64 simulated users:** output increased 3.2% (+11.51 tok/s); median visible TTFT increased 1,803.6% (+21.07 s).

Whole-percentage display rounds the TTFT increase to **+1,804%**. The statement is visible waiting, not proven server queueing. The normal adjacent comparison at 64 users remains 32 → 64 and is labeled separately.

## Evidence bundle and VictoriaMetrics import

The browser never queries a remote VictoriaMetrics instance. Evidence moves through:

```text
private remote run package
  → validation and normalization
  → sanitized, versioned evidence bundle
  → dashboard adapter
  → Inference Instrument
```

The normalized bundle contains:

- schema and catalog versions;
- episode, study, run, arm, and repetition identities;
- runtime/version, image digest, model/tokenizer revisions, precision, GPU/topology, effective flags, and configuration digest;
- workload digest, baseline arm, changed variables, cache state, and quality/SLO contract;
- load kind/value, slots, warmup/measurement/drain windows, and clock relationship;
- canonical metric ID, original metric name, source/version, unit, type, aggregation, population, and denominator;
- sample count, expected interval, duration, gaps, resets, availability, and missing reason;
- artifact hashes, importer version, validation results, and publication eligibility.

Sources remain explicit and separate:

1. client observations;
2. runtime-native metrics;
3. device telemetry;
4. synthetic fixtures.

The importer accepts a private run manifest plus VictoriaMetrics JSON-lines exports. It merges split series by identity, binds samples to the correct run/arm/repetition/GPU/window, preserves raw counters and histograms, identifies resets and incomplete windows, and applies metric-specific aggregation. It never averages percentiles or silently equates incompatible runtime definitions.

Sanitization uses an allowlist. Endpoints, credentials, prompts, outputs, and machine identifiers remain private. Missing intervals remain gaps. Episode 0 telemetry remains bound to Episode 0 and cannot backfill another study.

Publication fails closed when run attribution, units, source definitions, or time windows are ambiguous.

## Component and data boundaries

The implementation should introduce focused units:

- `EpisodeShell`: navigation, selector, evidence state, What/Why/How, and chapter navigation.
- `EvidenceAdapter`: converts a validated study bundle into presentation-ready arms, loads, metrics, and availability states.
- `LoadSweeper`: accessible discrete selection and pinned-comparison state.
- `LinkedMetricInstrument`: synchronized measured points, ruler, brackets, readouts, and table equivalent.
- `MetricExplanation`: canonical name, definition, unit, statistic, source, and direction semantics.
- `EvidenceBoundary`: observation, inference, recommendation, limitations, and provenance.
- `ImportStatus`: draft/import-pending validation state without exposing private artifacts.

The components consume typed normalized data. They do not infer missing metric names, measurement boundaries, or compatibility in the view layer.

Existing Episode 0, field-note, fixture, and concept artifacts remain available during migration. Legacy hashes redirect or render their existing views until parity tests pass.

## Error and empty states

- No matching evidence: show the declared experiment and “No measurements attached.”
- Metric unavailable: show the missing reason and affected arms or loads.
- Incompatible comparison: retain both values but suppress a delta and explain the mismatch.
- Invalid import: keep private evidence unpublished and expose only a local validation report.
- Partial telemetry: show covered windows and gaps; do not extrapolate.
- Failed chart rendering: keep the table and metric explanation available.

## Accessibility and responsive behavior

- All controls are keyboard and touch operable with visible focus.
- The sweeper has buttons in addition to slider semantics.
- Plot information is available through concise live text and a readable table.
- One polite announcement summarizes selection changes; individual cells do not all announce.
- Marker shape, direct labeling, symbols, and text preserve meaning without color.
- Touch targets are at least 44 pixels.
- At 390 pixels, plots recompose vertically without mandatory horizontal chart scrolling for the primary task.
- At 200% zoom, selection, comparison basis, units, and evidence state remain available.
- Reduced-motion mode preserves endpoints, brackets, and insight text without travel animation.

## Verification and acceptance criteria

1. Episode 00, Episode 01, and the field note retain distinct identities and provenance.
2. No SGLang/H200 measurement appears without matching validated evidence.
3. Existing concept artifacts and legacy views remain unchanged and reachable.
4. All recorded load levels work, including the first-point state.
5. At 64 users, the default baseline is 32; a pinned 16 baseline reproduces +3.2% throughput and +1,803.6% visible-TTFT change.
6. Sweep and soak measurements cannot silently share comparison baselines.
7. Selected and baseline points update across every compatible plot, readout, and table.
8. Every graph and metric exposes its name, explanation, units, statistic, source, and coverage.
9. Missing TPOT, queue, KV, GPU, memory, or power evidence remains unavailable with a reason.
10. Direction, magnitude, comparison basis, and non-color verdict are understandable together.
11. Draft and planned episodes show no invented charts or performance numbers.
12. Import validation rejects ambiguous attribution, incompatible definitions, malformed series, missing required identities, and unsafe labels.
13. Import tests cover split series, time gaps, resets, empty exports, duplicate samples, and partial windows.
14. Interaction tests cover pointer, keyboard, touch-sized controls, reduced motion, 390-pixel layout, zoom, and screen-reader summaries.
15. Existing dashboard tests remain passing; production readiness is not claimed without validated remote evidence.

## Deliberate exclusions

- No browser-to-remote-VictoriaMetrics connection.
- No predictive interpolation between tested loads.
- No fabricated Episode 01 results or telemetry.
- No universal GPU or runtime ranking.
- No automatic interpretation of utilization, memory, or power as improvement.
- No autoplay, particle animation, decorative glow, or scroll hijacking.
- No deletion or replacement of the four design concepts.

