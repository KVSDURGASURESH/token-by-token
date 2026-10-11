# Episode 01 Inference Instrument UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the production Inference Instrument shell, episode selector, pending Episode 01 experience, and linked field-note load comparison without changing or deleting the four design concepts.

**Architecture:** A typed evidence adapter owns comparison compatibility, metric availability, and delta semantics. Reusable React components render the episode shell, discrete load sweeper, linked metric instrument, and evidence boundaries; the existing Episode 01 fixture and session field note feed those components through separate adapters so their identities cannot be mixed.

**Tech Stack:** React 19, TypeScript 7, Vite 8, SVG, CSS, Node contract tests, Playwright acceptance tests

**Spec:** `docs/superpowers/specs/2026-10-06-episode-01-inference-instrument-design.md`

## Global Constraints

- Preserve Episode 00, Episode 01, the recorded field note, all legacy hashes, and all four design-spike artifacts.
- Episode 01 is an H200 SGLang-vs-vLLM experiment in draft state until matching validated evidence exists.
- The RTX PRO 6000/H200 vLLM session study remains a recorded exploratory field note.
- Use only the Episode 0 palette: `#080a0b`, `#111617`, `#171d1e`, `#f2f5ef`, `#9aa4a1`, `#283133`, `#465154`, `#ff6a38`, `#4bdcaf`, and `#f0ba4b`.
- Never interpolate between tested loads or tween through invented numerical values.
- Client-visible TTFT must not be labeled as server queue time.
- Missing metrics render unavailable with a reason, never as zero.
- The default comparison is the previous lower measured point; non-adjacent comparisons are explicitly pinned.
- Series identity uses labels, marker shape, and line style; status uses text, symbols, and color.
- Remote VictoriaMetrics ingestion is outside this UI slice; consume only repository evidence and explicit pending/unavailable states.

## Review Focus

- First measured load has no previous point: show a stable single-point comparison state without `NaN`, a fabricated delta, or broken SVG geometry.
- Selected arm lacks TPOT or native telemetry: keep the metric visible as unavailable with its reason and do not render a zero point.
- User switches from sweep to soak with a pinned comparison: reset the incompatible baseline and announce the new basis.
- Narrow viewport or 200% zoom: preserve episode identity, selected load, comparison basis, units, and primary controls without horizontal page overflow.
- Reduced-motion and rapid keyboard selection: settle on the latest recorded endpoint without queued animation or intermediate values.

---

## File structure

- Create `dashboard/src/instrument/evidence.ts`: normalized UI types, metric definitions, compatibility checks, delta calculation, and adapters for the session study and pending Episode 01.
- Create `dashboard/src/instrument/EpisodeShell.tsx`: episode selector, What/Why/How rail, state labels, chapter navigation, and Lab tools disclosure.
- Create `dashboard/src/instrument/LoadSweeper.tsx`: discrete pointer/button/keyboard selection and pin-comparison control.
- Create `dashboard/src/instrument/LinkedMetricInstrument.tsx`: synchronized SVG plots, measurement ruler, comparison brackets, readouts, explanations, and table equivalent.
- Create `dashboard/src/Episode1Instrument.tsx`: pending Episode 01 composition.
- Modify `dashboard/src/SessionCapacityStudy.tsx`: compose the field note with the shared shell and instrument while preserving detailed evidence sections.
- Modify `dashboard/src/App.tsx`: route identities and grouped reader/tool navigation.
- Modify `dashboard/src/data/episodes.json`: revise Episode 01 editorial metadata without claiming measurements.
- Modify `dashboard/src/styles.css`: Inference Instrument layout, motion, responsive rules, focus states, and reduced motion.
- Create `tests/dashboard_instrument_contract.cjs`: source/data/delta/identity contract.
- Create `tests/dashboard_instrument_acceptance.cjs`: browser interaction, accessibility, responsive, and local-only acceptance.
- Modify `tests/dashboard_session_study_acceptance.cjs`: preserve field-note evidence and legacy-route expectations.

### Task 1: Typed evidence adapter and comparison semantics

**Files:**
- Create: `dashboard/src/instrument/evidence.ts`
- Create: `tests/dashboard_instrument_contract.cjs`
- Modify: `dashboard/src/data/episodes.json`

**Interfaces:**
- Consumes: `dashboard/src/data/session-capacity-study.json`, `dashboard/src/data/episodes.json`
- Produces: `EvidenceStudy`, `EvidenceArm`, `MetricReading`, `MetricDefinition`, `ComparisonResult`, `adaptSessionStudy()`, `createPendingEpisode1()`, `previousMeasuredLoad()`, and `compareReadings()`.

- [ ] **Step 1: Write the failing identity and arithmetic contract**

Create `tests/dashboard_instrument_contract.cjs` with assertions that:

```js
const assert = require("node:assert/strict");
const fs = require("node:fs");

const episodes = JSON.parse(fs.readFileSync("dashboard/src/data/episodes.json", "utf8"));
const episode1 = episodes.episodes.find((entry) => entry.id === "episode-1");
assert.equal(episode1.title, "Measure what matters");
assert.equal(episode1.status, "draft");
assert.match(episode1.evidence, /results have not been imported/i);

const source = fs.readFileSync("dashboard/src/instrument/evidence.ts", "utf8");
assert.match(source, /previousMeasuredLoad/);
assert.match(source, /compareReadings/);
assert.match(source, /visible TTFT/);
assert.doesNotMatch(source, /TTFT.*server queue/i);
```

Add a small executable TypeScript-free fixture section to `evidence.ts` as exported constants only; the contract will inspect the source while TypeScript/build tests validate behavior in later steps.

- [ ] **Step 2: Run the contract and verify it fails**

Run: `node tests/dashboard_instrument_contract.cjs`  
Expected: FAIL because Episode 01 metadata and `evidence.ts` do not exist.

- [ ] **Step 3: Define normalized evidence types and metric vocabulary**

Implement these signatures in `dashboard/src/instrument/evidence.ts`:

```ts
export type EvidenceState = "recorded" | "draft" | "import-pending" | "planned";
export type MetricDirection = "higher" | "lower" | "contextual";

export type MetricReading = {
  available: boolean;
  value: number | null;
  unit: string;
  reason: string | null;
};

export type EvidencePoint = {
  load: number;
  label: string;
  readings: Record<string, MetricReading>;
};

export type EvidenceArm = {
  id: string;
  label: string;
  marker: "circle" | "diamond" | "square";
  lineStyle: "solid" | "dashed" | "dotted";
  points: EvidencePoint[];
};

export type EvidenceStudy = {
  id: string;
  kind: "episode" | "field-note";
  number: number | null;
  title: string;
  question: string;
  state: EvidenceState;
  what: string;
  why: string;
  how: string;
  loads: number[];
  arms: EvidenceArm[];
};

export type ComparisonResult = {
  available: boolean;
  absolute: number | null;
  relativePercent: number | null;
  reason: string | null;
};
```

Define canonical `METRICS` entries for `output_tps`, `ttft_p50`, `ttft_p95`, `tpot_p50`, `tpot_p95`, `invalid_rate`, `queue_depth`, `queue_wait`, `kv_occupancy`, `gpu_utilization`, `gpu_memory`, and `gpu_power`, each with label, explanation, unit, and direction.

- [ ] **Step 4: Implement adapters and pure comparison functions**

Implement:

```ts
export function previousMeasuredLoad(loads: number[], selected: number): number | null;
export function compareReadings(current: MetricReading, baseline: MetricReading): ComparisonResult;
export function adaptSessionStudy(): EvidenceStudy;
export function createPendingEpisode1(): EvidenceStudy;
```

`previousMeasuredLoad([2,4,8,16,32,64,100], 64)` returns `32`; at `2` it returns `null`. `compareReadings` suppresses relative change for unavailable readings and zero baselines. `adaptSessionStudy` exposes recorded output throughput, visible TTFT p50/p95, and invalid rate while marking TPOT and native telemetry unavailable with explicit reasons. `createPendingEpisode1` exposes the declared H200 runtime arms with no readings and draft state.

- [ ] **Step 5: Revise Episode 01 editorial metadata**

In `dashboard/src/data/episodes.json`, set Episode 01 to:

```json
{
  "id": "episode-1",
  "number": 1,
  "title": "Measure what matters",
  "status": "draft",
  "evidence": "H200 comparison planned; results have not been imported",
  "dashboardView": "episode1-instrument",
  "model": "Declared by imported run package",
  "hardware": "One H200 per measured arm — results pending",
  "runtimes": "vLLM · SGLang"
}
```

Retain existing guide, roadmap, template, and numbering fields.

- [ ] **Step 6: Run contract and TypeScript checks**

Run: `node tests/dashboard_instrument_contract.cjs && npm run check --prefix dashboard`  
Expected: PASS.

- [ ] **Step 7: Commit the adapter slice**

```bash
git add dashboard/src/instrument/evidence.ts dashboard/src/data/episodes.json tests/dashboard_instrument_contract.cjs
git commit -m "feat: add inference instrument evidence model"
```

### Task 2: Episode shell and navigation hierarchy

**Files:**
- Create: `dashboard/src/instrument/EpisodeShell.tsx`
- Modify: `dashboard/src/App.tsx`
- Modify: `dashboard/src/styles.css`
- Test: `tests/dashboard_instrument_acceptance.cjs`

**Interfaces:**
- Consumes: `EvidenceStudy`; current hash route; episode catalog.
- Produces: `EpisodeShell({ study, children, chapters })` and grouped navigation with `Episodes`, `Field notes`, `Methodology`, and `Lab tools`.

- [ ] **Step 1: Write the failing navigation acceptance**

Create `tests/dashboard_instrument_acceptance.cjs` using the existing Playwright launch pattern. For `#episode-1` assert:

```js
assert.equal(await page.getByRole("heading", { name: "Which changes improve serving on H200?" }).count(), 1);
assert.equal(await page.getByText("Draft · results pending", { exact: true }).count(), 1);
assert.equal(await page.getByRole("button", { name: /Choose episode/i }).count(), 1);
assert.equal(await page.getByText("What", { exact: true }).count(), 1);
assert.equal(await page.getByText("Why", { exact: true }).count(), 1);
assert.equal(await page.getByText("How", { exact: true }).count(), 1);
assert.equal(await page.getByText("H200 comparison planned; results have not been imported.", { exact: true }).count(), 1);
```

Assert only one navigation item has `aria-current="page"` and Lab tools is a disclosure rather than six peer links.

- [ ] **Step 2: Run the acceptance and verify it fails**

Run against the existing dev server: `node tests/dashboard_instrument_acceptance.cjs http://127.0.0.1:5173/`  
Expected: FAIL because the shell and revised route do not exist.

- [ ] **Step 3: Implement `EpisodeShell`**

The component renders:

```tsx
export function EpisodeShell({
  study,
  chapters,
  children,
}: {
  study: EvidenceStudy;
  chapters: Array<{ id: string; label: string }>;
  children: React.ReactNode;
}) { /* selector, state, What/Why/How, chapters, content */ }
```

The episode selector lists recorded, draft, and planned states. It uses a native button/disclosure, restores focus on Escape, and links to existing hash routes. Planned entries remain selectable and readable.

- [ ] **Step 4: Group production navigation in `App.tsx`**

Replace eight peer links with reader navigation and a `<details>` Lab tools group. Preserve all existing hashes. Ensure the current-page condition is exclusive for Episode 00, Episode 01, and `#session-study`.

- [ ] **Step 5: Add structural shell styles**

Add `instrument-*` classes using the existing palette variables. Build the 200-pixel rail/main layout and the compact mobile chapter navigation. Avoid new colors, gradients, rounded card grids, and ambient effects.

- [ ] **Step 6: Run TypeScript and navigation acceptance**

Run: `npm run check --prefix dashboard && node tests/dashboard_instrument_acceptance.cjs http://127.0.0.1:5173/`  
Expected: navigation assertions pass; later instrument assertions may remain pending until Tasks 3–4.

- [ ] **Step 7: Commit the shell slice**

```bash
git add dashboard/src/instrument/EpisodeShell.tsx dashboard/src/App.tsx dashboard/src/styles.css tests/dashboard_instrument_acceptance.cjs
git commit -m "feat: add episode instrument shell"
```

### Task 3: Discrete load sweeper and linked metric instrument

**Files:**
- Create: `dashboard/src/instrument/LoadSweeper.tsx`
- Create: `dashboard/src/instrument/LinkedMetricInstrument.tsx`
- Modify: `dashboard/src/styles.css`
- Modify: `tests/dashboard_instrument_acceptance.cjs`

**Interfaces:**
- Consumes: `EvidenceStudy`, selected arm, selected load, optional pinned baseline, and canonical metric IDs.
- Produces: `LoadSweeper`, `LinkedMetricInstrument`, accessible table output, and one polite selection summary.

- [ ] **Step 1: Add failing interaction assertions**

For `#session-study`, assert seven tested-load buttons and a slider with accessible text. Select 64 users and verify:

```js
assert.equal(await page.getByRole("slider", { name: /tested load/i }).getAttribute("aria-valuetext"), "64 simulated users, measured level 6 of 7");
assert.match(await page.getByLabel("Comparison summary").innerText(), /Compared with 32 users/);
assert.match(await page.getByLabel("Comparison summary").innerText(), /\+43\.7%.*output/s);
assert.match(await page.getByLabel("Comparison summary").innerText(), /\+150\.3%.*visible TTFT/s);
```

Pin 16 and assert the bounded observation includes `+3.2%` output and `+1,803.6%` visible TTFT. Select 2 and assert “First measured point; no previous comparison.”

- [ ] **Step 2: Run acceptance and verify it fails**

Run: `node tests/dashboard_instrument_acceptance.cjs http://127.0.0.1:5173/`  
Expected: FAIL on sweeper and linked comparison selectors.

- [ ] **Step 3: Implement `LoadSweeper`**

Use this controlled interface:

```ts
type LoadSweeperProps = {
  loads: number[];
  selected: number;
  baseline: number | null;
  pinned: boolean;
  onSelect(load: number): void;
  onPin(load: number | null): void;
};
```

Render discrete buttons plus an `input[type="range"]` whose values are indices, not loads. Arrow/Home/End behavior selects recorded endpoints only. The first point never calculates a previous delta.

- [ ] **Step 4: Implement `LinkedMetricInstrument`**

Use fixed horizontal positions for all measured loads. Render output throughput and visible TTFT as the primary aligned plots; render other available metrics as compact rows. The selected marker is solid, baseline marker outlined, and every plot directly labels the arm.

Provide visible metric explanations and a table containing exact arm, load, value, unit, baseline, absolute delta, relative delta, availability, and reason. Missing readings render `—` and their reason.

- [ ] **Step 5: Implement delta status without conflating identity**

Render `✓ Improved`, `↓ Regressed`, `≈ Within tolerance`, or `◇ Contextual change` only when the metric definition and declared tolerance permit it. Always include signed numbers and basis text. Use marker shapes and line style for arm identity.

- [ ] **Step 6: Add the measurement-ruler animation**

Animate only the selection overlay and comparison brackets for approximately 160 ms. Keep axes and points fixed. Add `prefers-reduced-motion: reduce` rules that remove travel and bracket reveals. Ensure rapid selection replaces the current transform rather than queuing animations.

- [ ] **Step 7: Run interaction and TypeScript tests**

Run: `npm run check --prefix dashboard && node tests/dashboard_instrument_acceptance.cjs http://127.0.0.1:5173/`  
Expected: all sweeper, comparison, first-point, and reduced-motion assertions pass.

- [ ] **Step 8: Commit the instrument slice**

```bash
git add dashboard/src/instrument/LoadSweeper.tsx dashboard/src/instrument/LinkedMetricInstrument.tsx dashboard/src/styles.css tests/dashboard_instrument_acceptance.cjs
git commit -m "feat: add linked inference measurement instrument"
```

### Task 4: Compose pending Episode 01 and recorded field note

**Files:**
- Create: `dashboard/src/Episode1Instrument.tsx`
- Modify: `dashboard/src/SessionCapacityStudy.tsx`
- Modify: `dashboard/src/App.tsx`
- Modify: `tests/dashboard_session_study_acceptance.cjs`
- Modify: `tests/dashboard_instrument_acceptance.cjs`

**Interfaces:**
- Consumes: `createPendingEpisode1()`, `adaptSessionStudy()`, `EpisodeShell`, `LoadSweeper`, and `LinkedMetricInstrument`.
- Produces: production `#episode-1` and additive `#session-study` experiences.

- [ ] **Step 1: Add failing composition assertions**

For Episode 01 assert that the planned vLLM/SGLang arms, method, and unavailable metric inventory are visible, while no measured performance number appears. For the field note assert that `Recorded measurements from synthetic session replay; selection generates no new data` appears and the legacy configuration/evidence tables remain present.

- [ ] **Step 2: Run both acceptance suites and verify failure**

Run:

```bash
node tests/dashboard_instrument_acceptance.cjs http://127.0.0.1:5173/
node tests/dashboard_session_study_acceptance.cjs http://127.0.0.1:5173/
```

Expected: FAIL on the new composition text and structure.

- [ ] **Step 3: Build the pending Episode 01 page**

Compose `EpisodeShell` with the question “Which changes improve serving on H200?”, the baseline/optimization-arm matrix, declared measurement contract, import-pending explanation, and missing-evidence inventory. Do not render result SVGs when there are no readings.

- [ ] **Step 4: Refactor the field note composition**

Move the load sweeper and linked instrument into the first viewport. Preserve matched soak, full sweep evidence, previous-study table, configuration matrix, evidence boundaries, and method footer below it. Replace “Watch the queue” language with “Watch the wait.”

Pass selected and pinned load state to every compatible plot and readout. Keep the 32-user failure anomaly visible.

- [ ] **Step 5: Route Episode 01 to the new component**

Render `Episode1Instrument` for `dashboardView === "episode1-instrument"`. Keep `Episode1Fixture` reachable through a methodology link or legacy fixture hash so the local contract artifact is preserved.

- [ ] **Step 6: Run composition tests**

Run:

```bash
npm run check --prefix dashboard
node tests/dashboard_instrument_contract.cjs
node tests/dashboard_instrument_acceptance.cjs http://127.0.0.1:5173/
node tests/dashboard_session_study_acceptance.cjs http://127.0.0.1:5173/
```

Expected: PASS.

- [ ] **Step 7: Commit the composition slice**

```bash
git add dashboard/src/Episode1Instrument.tsx dashboard/src/SessionCapacityStudy.tsx dashboard/src/App.tsx tests/dashboard_instrument_acceptance.cjs tests/dashboard_session_study_acceptance.cjs
git commit -m "feat: compose episode 1 inference experience"
```

### Task 5: Responsive, accessibility, and visual-regression hardening

**Files:**
- Modify: `dashboard/src/styles.css`
- Modify: `tests/dashboard_instrument_acceptance.cjs`
- Modify: `tests/dashboard_session_study_acceptance.cjs`

**Interfaces:**
- Consumes: completed production pages.
- Produces: verified 1440-, 768-, and 390-pixel layouts with reduced-motion and keyboard coverage.

- [ ] **Step 1: Add viewport and accessibility assertions**

At 1440, 768, and 390 pixels assert:

```js
assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), false);
assert.equal(await page.locator('[aria-live="polite"]').count(), 1);
assert.equal(await page.locator('.instrument-metric-explanation').count() >= 2, true);
assert.equal(await page.locator('.instrument-data-table').count(), 1);
```

Use keyboard input to move the sweeper, press Home/End, open and close the episode selector with Escape, and verify focus restoration. Emulate reduced motion and assert the selection overlay has no transition duration.

- [ ] **Step 2: Run acceptance and capture initial failures**

Run with screenshots:

```bash
DASHBOARD_SCREENSHOT_DIR=/tmp/token-by-token-instrument node tests/dashboard_instrument_acceptance.cjs http://127.0.0.1:5173/
```

Expected: any remaining overflow, focus, touch-target, or reduced-motion failures are reported with viewport-specific captures.

- [ ] **Step 3: Harden responsive styles**

Ensure primary plots stack on mobile, load controls wrap, the episode rail becomes compact chapter navigation, touch targets are at least 44 pixels, and primary charts do not require horizontal scrolling. Keep detailed appendix tables scrollable within labeled containers.

- [ ] **Step 4: Review screenshots and remove generic decoration**

Inspect all three captures. Remove redundant borders, repeated uppercase eyebrows, equal-weight boxed sections, non-informational hover effects, and decorative motion. Verify that the measurement ruler is the sole memorable animation.

- [ ] **Step 5: Run the complete dashboard verification set**

Run:

```bash
npm run build --prefix dashboard
node tests/dashboard_instrument_contract.cjs
node tests/dashboard_instrument_acceptance.cjs http://127.0.0.1:5173/
node tests/dashboard_session_study_contract.cjs
node tests/dashboard_session_study_acceptance.cjs http://127.0.0.1:5173/
node tests/dashboard_series_acceptance.cjs http://127.0.0.1:5173/
node tests/dashboard_planner_acceptance.cjs http://127.0.0.1:5173/
```

Expected: PASS with no page errors, no cross-origin requests, no viewport overflow, and unchanged legacy evidence.

- [ ] **Step 6: Commit the hardening slice**

```bash
git add dashboard/src/styles.css tests/dashboard_instrument_acceptance.cjs tests/dashboard_session_study_acceptance.cjs
git commit -m "test: harden inference instrument experience"
```

### Task 6: Documentation and implementation handoff

**Files:**
- Modify: `README.md`
- Modify: `docs/dashboard-captures/README.md`
- Create: `docs/episode-1-preparation/inference-instrument.md`

**Interfaces:**
- Consumes: verified UI routes and screenshots.
- Produces: discoverable contributor and evidence-state documentation.

- [ ] **Step 1: Document route identities and evidence boundaries**

Document Episode 00, Episode 01 draft, and the session field note as distinct entries. State that Episode 01 contains no H200 runtime result until a validated bundle is imported. Link the design spec and implementation plan.

- [ ] **Step 2: Document local verification**

Record exact commands from Task 5 and their outcomes. Label remote Episode 01 execution and VictoriaMetrics import unverified.

- [ ] **Step 3: Document screenshots and interaction**

Update the capture README with viewport, route, evidence source, and a description of the selected/baseline ruler behavior. Do not claim production readiness from local screenshots.

- [ ] **Step 4: Run documentation and final source checks**

Run:

```bash
rg -n "Episode 01|session field note|results have not been imported" README.md docs/episode-1-preparation/inference-instrument.md
git diff --check
npm run build --prefix dashboard
```

Expected: all required evidence-state language exists, diff check is clean, and build passes.

- [ ] **Step 5: Commit documentation**

```bash
git add README.md docs/dashboard-captures/README.md docs/episode-1-preparation/inference-instrument.md
git commit -m "docs: document inference instrument experience"
```

