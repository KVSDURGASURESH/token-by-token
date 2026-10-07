# Interactive evidence experience: UI/UX design handoff

Status: working design brief for independent review
Implementation owner: Codex
Design reviewers: GPT-6 Astra Ultra, then Claude Opus
Publication target: LinkedIn and Substack companion experience

## Implementation progress

- [x] Build a persistent left episode rail with available and planned studies.
- [x] Make the concise Episode Brief the default view.
- [x] Limit the Brief to one finding, three recorded loads, and four essential signals.
- [x] Apply direction-aware green/red/orange outcome semantics; keep engine identity neutral.
- [x] Move linked plots, definitions, exact tables, thresholds, and evidence boundaries into an opt-in Evidence Lab.
- [x] Keep Brief/Evidence state shareable in the URL and provide a clear return path.
- [x] Remove model-serving profile details from the public Episode 01 presentation and static bundle.
- [x] Verify desktop, tablet, and mobile interaction with no horizontal page overflow.
- [ ] Incorporate any final non-blocking recommendations from the independent Opus functional review.
- [ ] Commit, push, and merge only after owner approval.

## Mission

Create a distinctive interactive evidence experience for engineers evaluating LLM inference behavior. Fuse the scientific density of Episode 00 with the editorial clarity and visual confidence of Episode 01. The result should feel like an instrument the reader learns by touching, not a generic AI dashboard, a marketing template, or a static report with charts pasted into it.

The first screen must answer three questions quickly:

1. What was tested?
2. What changed?
3. Why should I keep exploring?

Within five minutes, a technical reader should be able to reproduce the comparison logic, inspect every public metric, understand the evidence limits, and leave with a safe command for trying the public binary.

## Repositories to inspect

### Public experience

`$TOKEN_BY_TOKEN_REPO`

- Branch: `codex/episode-1-local-prep`
- Live local UI: `http://127.0.0.1:5196/`
- Episode index: `#episodes`
- Episode 00: `#episode-0`
- Episode 01: `#episode-1`
- Methodology: `#methodology`
- Current publication handoff: `handoffs/2026-10-06T12-11-11Z-static-evidence-publication.md`
- QA record: `docs/validation/2026-10-06-static-site-qa.md`
- Public Episode 01 evidence: `dashboard/src/data/episode-1-public.v1.json`
- Sanitized Episode 00 presentation: `dashboard/src/data/episode-0-public.json`

### Benchmark product and public binary source

`$BENCHMARK_SOURCE_REPO`

Inspect this repository only to understand the benchmark journey, corpus model, metric vocabulary, report structure, and existing CLI capabilities. Do not copy private deployment recipes, profile names, versions, endpoints, identifiers, environment variables, or organization-specific settings into public design artifacts.

Relevant concepts include:

- multi-turn coding-agent and conversational traffic;
- concurrent users with multiple live sessions;
- real recorded request shapes and long accumulated contexts;
- client, inference-engine, and GPU measurements aligned over one window;
- validity gates for errors, sample completeness, coherence, and evidence provenance;
- public result artifacts, including per-level outcomes, server-level telemetry, and time-series exports.

## Audience and jobs

Primary audience: inference engineers, platform engineers, technical founders, and practitioners deciding how to benchmark a serving stack.

Secondary audience: technically curious readers arriving from LinkedIn or Substack who need a guided explanation before they can read the full evidence.

Core jobs:

- understand the experiment in under 30 seconds;
- compare two recorded inference-engine observations at a selected load;
- see whether a metric improved, regressed, or stayed effectively unchanged;
- move from a headline delta to the underlying chart, definition, table row, and evidence boundary;
- understand how realistic workloads differ from toy prompts;
- copy a safe, constrained public command and understand what it will measure;
- distinguish observation from causation, capacity, and production certification.

## Design thesis

Episode 00 supplies the evidence grammar: full tables, metric definitions, detailed plots, and a sense that nothing is being hidden.

Episode 01 supplies the editorial grammar: a memorable opening, confident typography, a measured-load control, direct answers, progressive disclosure, and strong negative space.

The redesign should combine them as an **editorial instrument**:

- a concise opening with one defensible result above the fold;
- a persistent but quiet experiment spine showing episode, load, baseline, and evidence state;
- linked metric views where a headline, chart, definition, table row, and interpretation update together;
- progressive depth: answer first, mechanism second, exact evidence third;
- motion that explains state changes rather than decorating the page;
- full raw-looking public tables available on demand without forcing every reader through them.

Do not make a mosaic of rounded cards. Prefer full-width editorial bands, ruled measurement surfaces, aligned columns, typographic hierarchy, and one primary interactive workspace.

The strongest evidence-led publication story is:

> The throughput lead changes with load. Faster aggregate output does not guarantee a better experience.

Do not use “the queue changes the winner.” The recorded observations do not establish queue causation or a universal engine winner.

## Proposed journey

### 1. Arrival: result first

The first viewport is one composition, not a dashboard grid.

- Product/series identity and Episode 01 context.
- One sentence stating the experiment.
- One defensible comparative finding.
- A compact confidence/evidence label: recorded observation, matched load, capacity not established.
- A visible affordance to begin moving through measured loads.

The current giant Episode 01 headline should be reduced enough that the first result or interactive control is visible without a full-screen scroll.

### 2. Sweep: explore load as a story

The user moves across the recorded 12, 16, and 24-user points with a ruler, drag control, keyboard arrows, or direct selection. Transitions should interpolate position and emphasis, but never fabricate unmeasured values.

At every selected point, update together:

- the direct-answer sentence;
- output throughput;
- TTFT p50 and p95;
- TPOT p50;
- decode p10 against the declared threshold;
- error rate and valid sample counts;
- running and waiting requests;
- GPU utilization, memory, and power when comparable;
- a concise explanation of what changed relative to the selected baseline.

Episode 01 needs two explicit, mutually exclusive comparison modes:

- **Compare deployments at this load:** SGLang versus vLLM at the selected measured load.
- **Compare loads within each deployment:** selected load versus a pinned recorded-load baseline.

Every delta must declare its operands. Keep 12, 16, and 24 as discrete selections; do not imply continuous or interpolated measurements. For three points, prefer one compact segmented control over both large buttons and a redundant slider.

Episode 00 is different: input length and concurrency change together. Its workload points must remain categorical. A common visual shell must not turn Episode 00 into a numeric load sweep or invite cross-episode performance comparisons between different models, hardware, or protocols.

### 3. Explain: reveal the mechanism

Selecting or focusing a metric opens a linked explanation layer:

- plain-language definition;
- better direction and unit;
- comparison equation and baseline;
- client-visible, engine-native, or GPU evidence source;
- one-line interpretation;
- important caveat.

Charts should support hover, focus, and touch. A shared vertical cursor or selected-load marker should link related plots.

### 4. Verify: exact evidence

An expandable measurement ledger exposes Episode 00-style detail:

- one row per engine and measured load;
- exact public values, units, validity, and sample counts;
- unavailable values shown as unavailable with a reason, never as zero;
- row-to-chart linking and a copyable citation/state link;
- observed and not-established conclusions next to the data.

### 5. Try: constrained public binary

End with a small command composer, not a fake terminal playground. It should generate an allowlisted command using only safe public controls. Conceptual form:

```text
benchmark episode-0 --users 4
```

The final executable name and episode syntax must match the public distribution decision. The initial public surface should be intentionally small:

- episode selection from a published allowlist;
- users from a bounded allowlist or validated range;
- optional output directory;
- dry-run or explain mode;
- help/version.

Everything else stays behind curated episode manifests. The user should not receive internal profiles, deployment flags, engine recipes, endpoints, credentials, private corpus payloads, or provider automation.

The composer explains what the command will do, expected prerequisites, estimated duration/cost class when known, and where the resulting local report appears. It never executes provider purchases or remote infrastructure from the static website.

For the EOD publication, treat the command as a proposed contract unless an implementation and tests exist. The smallest credible first implementation is an offline reader of approved recorded evidence: accept only published episode IDs and recorded load values, print the same qualified result, and provide the matching shareable dashboard state. Fresh measurement is a later, separately engineered action on the reader's own infrastructure.

## Semantic comparison system

Color describes the direction of a metric, never engine identity.

| State | Color role | Meaning |
|---|---|---|
| Better | Green | The selected observation improved in that metric's declared direction. |
| Worse | Red | The selected observation regressed against the selected baseline. |
| Equivalent/neutral | Orange | The change is zero, inside a declared equivalence/display band, or contextual rather than directional. |
| Unavailable | Muted neutral | Evidence is missing or non-comparable, with a written reason. |

Example:

> SGLang recorded **27.5% more output** and **26.8% lower median TTFT** than vLLM.

Both `27.5%` and `26.8%` are green because more output and lower TTFT are improvements. A corresponding worse baseline delta may be red. Ties or changes inside the declared display band are orange.

Requirements:

- every comparison declares whether higher or lower is better;
- every delta names its baseline and load;
- color is paired with `+`/`−`, better/worse/unchanged text, and an icon or shape;
- engine series retain stable identities through labels, marker shapes, and line styles, not good/bad colors;
- thresholds and equivalence bands are visible and explained;
- never color an invalid or unavailable comparison as a win or loss.

## Visual system direction

Aim for a scientific editorial object from the near future, not neon cyberpunk.

- Preserve the dark graphite, warm paper, mint, orange-red, and amber family already established by Episode 00.
- Use two type voices at most: a condensed display face for claims and a highly readable text/data face for analysis.
- Use thin rules, calibration marks, restrained grids, monospaced numerals, and deliberate asymmetry.
- Let negative space separate narrative phases; let density appear only when the reader asks for evidence.
- Avoid generic gradients, glowing glass cards, decorative blobs, excessive rounded containers, icon-circle feature grids, and ornamental dashboards.
- Light and Dark are equal designs, not an inversion afterthought.

## Motion and fluidity

Motion must teach the system:

- selected-load transitions move one shared cursor through every linked plot;
- changed values roll or crossfade while the unit and context stay anchored;
- cause/effect annotations draw in after the data settles;
- table rows briefly highlight when their chart point is selected;
- episode transitions preserve the reader's conceptual location: question, experiment, evidence, or conclusion;
- reduced-motion mode replaces movement with immediate state changes and emphasis.

Avoid continuous ambient animation, parallax for its own sake, springy dashboard cards, or motion that implies interpolation between unmeasured points.

## Information architecture

```text
Episodes
├── Episode overview
│   ├── What / why / how
│   ├── One recorded answer
│   └── Evidence status
├── Interactive experiment
│   ├── Measured-load sweep
│   ├── Linked metric story
│   └── Mechanism annotations
├── Evidence ledger
│   ├── Exact measurement table
│   ├── Definitions and provenance class
│   └── Observed / not established
├── Methodology
│   ├── Workload population
│   ├── Session/request anatomy
│   ├── Validity gates
│   └── Static publication boundary
└── Try it
    ├── Constrained command composer
    ├── Public binary/GitHub access
    └── Local result import path
```

On mobile, this becomes a guided vertical story with a sticky compact load selector and metric drawer. Do not merely stack the desktop layout.

## Static data architecture

The public site stays static.

VictoriaMetrics and Grafana are build-time evidence tools only. Approved metrics are imported locally, reconciled to exact measurement windows, validated, transformed through a positive allowlist, privacy-scanned, and emitted as versioned static JSON. The browser never queries VictoriaMetrics, Grafana, private endpoints, or raw exports.

The future public schema may add synchronized time-series summaries, but only when they are:

- downsampled or aggregated for the declared view;
- stripped of private labels and identifiers;
- bound to a valid public run and exact time window;
- unit-normalized and definition-compatible;
- small enough for offline static delivery;
- accompanied by availability and reason fields.

Do not expose the currently committed synchronized traces as a new EOD feature until their rate/count/window semantics are reconciled. In particular, request-rate samples must reconcile with declared request totals and measurement duration. Keep the scalar comparisons central for the initial publication.

## Privacy and scientific guardrails

Never expose:

- internal profile names or configuration matrices;
- engine versions, model revisions, optimization recipes, launch flags, or environment variables;
- private organization/tool/sponsor names in the public methodology;
- endpoints, credentials, container images, internal paths, run IDs, request IDs, or provider identifiers;
- raw prompts, completions, tool schemas, payloads, result bodies, labels, logs, exports, or receipts;
- invalid 14-user evidence or any other non-public arm.

Never claim:

- engine-only causation from a deployment comparison;
- capacity when the declared capacity procedure did not establish it;
- statistical significance without a defined analysis;
- production certification or universal ranking;
- interpolated performance between recorded load points.

## UI states that must be designed

| Feature | Default/success | Unavailable/partial | Error/invalid |
|---|---|---|---|
| Episode selector | Published episodes plus clearly labeled planned episodes | Planned episode explains what will be measured | Broken/missing manifest fails closed with a plain recovery path |
| Load sweep | Recorded points selectable | Missing point visibly unavailable | Invalid point excluded from comparative language |
| Metric view | Value, unit, direction, baseline, evidence state | Unavailable plus reason | Definition mismatch blocks delta |
| Evidence ledger | Exact public rows | Missing cells say unavailable | Privacy/schema failure prevents publication |
| Command composer | Valid allowlisted command | Unsupported option explains allowed choices | No shell execution and no silent coercion |
| Local result import | Sanitized supported report renders locally | Unsupported fields ignored with explanation | Malformed/private content rejected before rendering |

## Accessibility and responsive requirements

- Full keyboard operation for episode, load, metric, disclosure, and command controls.
- Visible focus and stable focus after transitions.
- Screen-reader announcements describe selected load and comparison change without reading every chart point.
- Minimum 44 px touch targets.
- WCAG AA contrast in Light and Dark.
- Color-independent better/worse/neutral encoding.
- Reduced-motion support with no loss of information.
- No document-level overflow at 1440, 1280, 768, and 390 px and at 200% zoom.
- Tables may scroll locally with sticky row/column context.

## What to retain

From Episode 00:

- exact tables and evidence density;
- clear metric units and definitions;
- multiple views of client, engine, and GPU behavior;
- sober scientific tone.

From Episode 01:

- strong series identity and typography;
- measured-load interaction;
- direct-answer copy;
- progressive disclosure;
- explicit evidence boundary;
- negative space and restraint.

## What to redesign

- Bring the first defensible result into the first viewport.
- Replace route-level visual discontinuity with one episode system.
- Link all charts, deltas, definitions, and table rows through a shared selected-load state.
- Turn the evidence table into an interactive ledger rather than a detached appendix.
- Make metric direction and baseline immediately legible.
- Make the episode picker feel like moving through a scientific series, not website navigation.
- Separate public exploration from internal lab/operator tools.
- Connect the article/post narrative to stable, shareable dashboard states.
- Label Methodology request traces and session replay visibly as schematic/conceptual wherever they are not measured evidence.
- Separate a declared quality/performance gate from whether a given release actually passed it.
- Use “simulated users” and “session slots” precisely; session slots are not necessarily simultaneous active requests.

## Independent Astra Ultra review outcomes

The separate Astra Ultra session reviewed both repositories and the live site at desktop and 390 px without editing files. Its recommendations are incorporated above. The UI/UX reviewer should preserve these decisions:

- Build an interactive research article with an evidence explorer inside it.
- Use the three disclosure levels **Read → Explore → Audit**.
- Put one qualified finding and the first useful control in the opening viewport.
- Keep Episode 00 categorical while sharing the visual shell.
- Separate cross-engine comparison from within-engine load comparison.
- Encode episode, load, comparison mode, baseline, and selected metric in shareable URL state.
- Use color for metric direction only; use names, marker shapes, and line styles for engine identity.
- Keep raw values neutral unless a visible baseline makes a directional comparison valid.
- Treat queue size, GPU utilization, memory, and power as contextual unless the study declares a defensible direction.
- Keep threshold attainment separate from improvement versus baseline.
- Withhold unreconciled time-series traces from the EOD release.
- Do not present the proposed `episode` CLI as shipped functionality until its offline evidence-reader contract is implemented and tested.

## Deliverables requested from the UI/UX reviewer

Return design recommendations only. Do not edit application source.

1. A blunt critique of the current Episode 00, Episode 01, episode index, and methodology journey.
2. A recommended information architecture and first-screen hierarchy.
3. Desktop and mobile wireframe descriptions for the fused episode shell.
4. The interaction specification for load selection, metric linking, evidence disclosure, and command composition.
5. A concrete visual-system direction with typography, spacing, color roles, rules, and surface behavior.
6. A motion specification including reduced-motion equivalents.
7. A semantic metric-color specification validating the green/red/orange rules above.
8. Accessibility and responsive risks.
9. What to remove because it looks generated, decorative, or redundant.
10. A prioritized implementation sequence that Codex can execute without exposing private IP or destabilizing the publication branch.

## Separate functional/product review questions

Keep these distinct from visual design:

- What is the smallest safe public binary contract?
- Should public runs generate a local static report compatible with this dashboard?
- Which metric families add explanatory value beyond the current public aggregate points?
- How should a user import their own sanitized result without uploading it?
- Which episode parameters belong in manifests rather than CLI flags?
- What can ship for today's publication versus a later product release?

## Not in scope for the design pass

- changing the benchmark algorithm;
- publishing private source data or operational configurations;
- provisioning or purchasing GPU infrastructure;
- exposing a live metrics service on the internet;
- rewriting the dashboard before a design direction is approved;
- changing scientific claims to improve marketing impact.

## Acceptance test for the design

The design is ready for implementation when a new reader can:

1. identify the experiment and one result in five seconds;
2. select a measured load without mistaking the control for interpolation;
3. identify better, worse, neutral, invalid, and unavailable states without relying on color alone;
4. trace a headline delta to an exact public value and metric definition;
5. understand what was observed and what was not established;
6. copy a safe public command without learning internal deployment IP;
7. use the full experience offline and on mobile;
8. recognize the site as Token by Token rather than a generic AI dashboard.
