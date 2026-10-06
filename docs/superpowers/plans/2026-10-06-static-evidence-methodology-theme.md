# Static Evidence, Methodology, and Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Keep every checkbox current; do not mark a task complete until its listed verification passes.

**Goal:** Turn the final private benchmark package into a privacy-safe, fully static Episode 01 experience, add an interactive public methodology page, and ship a site-wide Light/Dark theme without exposing internal benchmark or serving-profile intellectual property.

**Architecture:** A local-only evidence pipeline restores and validates private telemetry, then emits one schema-constrained, byte-stable public JSON document. The React dashboard reads only that document. A shared theme controller and a new methodology route sit above the existing episode experiences. Source and compiled-asset privacy gates fail closed before publication.

**Tech Stack:** Python 3.12, JSON Schema, `unittest`/pytest, VictoriaMetrics import API, PromQL query API, React 19, TypeScript 7, Vite 8, SVG/CSS, Node contract tests, Playwright 1.63

**Spec:** `docs/superpowers/specs/2026-10-06-static-evidence-methodology-theme-design.md`

## Progress overview

**Current:** Complete — implementation, independent review, verification, and handoff recorded

- [x] 1. Freeze the public evidence contract and write failing pipeline tests
- [x] 2. Build and validate the local-only VictoriaMetrics evidence importer
- [x] 3. Generate the deterministic, privacy-safe Episode 01 data bundle
- [x] 4. Remove internal profile/configuration material from Episode 01
- [x] 5. Build the interactive methodology page
- [x] 6. Add persistent Light/Dark themes across every public route
- [x] 7. Add compiled-bundle privacy and offline-publication gates
- [x] 8. Run responsive, accessibility, preservation, and visual QA
- [x] 9. Reconcile documentation, record evidence, and complete final review

## Non-negotiable constraints

- Public engine names may be `vLLM` and `SGLang`; engine versions may not be published.
- Do not publish the benchmark tool name, sponsor/organization name, internal profile names, optimization recipes, launch flags, environment variables, container images, package builds, endpoints, local paths, usernames, commits, run IDs, request IDs, or machine/provider identifiers.
- Do not publish prompts, completions, tool schemas, payloads, results, raw labels, raw `.gz`, Parquet, JSONL, logs, manifests, or Grafana exports.
- The private 14-user profile is not a public result. It may validate the importer only and must never appear in generated JSON or compiled assets.
- Public Episode 01 uses only the matched valid `vLLM`/`SGLang` observations at 12, 16, and 24 users.
- A result invalidated by error rate above 1%, incomplete measurement, missing coherence/provenance, or an incompatible definition cannot support a comparative claim.
- Missing evidence is `Unavailable` with a reason, never zero.
- VictoriaMetrics and Grafana are local build-time tools. The published site must work from static assets with all network access blocked.
- Preserve Episode 00, the Session Field Note, all existing route hashes, and every archived design concept.
- Use Episode 00's semantic color system. Green means improvement, red/orange means regression, and amber means neutral/contextual in both themes.
- Keep unrelated user changes in `tests/dashboard_planner_acceptance.cjs`, `tests/dashboard_series_acceptance.cjs`, and `docs/publication-drafts/` untouched.

---

## Task 1: Freeze the public evidence contract and write failing pipeline tests

**Files:**
- Create: `schemas/public-inference-evidence.v1.schema.json`
- Create: `tests/fixtures/private-evidence-minimal.json`
- Create: `tests/test_static_evidence_pipeline.py`
- Create: `scripts/build_static_benchmark_evidence.py`

**Interfaces:**
- Input: private reports/tables selected explicitly by command-line path.
- Output: `dashboard/src/data/episode-1-public.v1.json` conforming exactly to `schemas/public-inference-evidence.v1.schema.json`.
- Exit status: `0` only for complete, deterministic, privacy-compliant evidence; non-zero without emitting partial output.

- [x] **Step 1.1: Add a failing schema/generator test**

Create `tests/test_static_evidence_pipeline.py` using `unittest`. Load the generator by file path, invoke `build_public_document(...)` with the synthetic fixture, and assert:

```python
self.assertEqual(document["schema_version"], "public-inference-evidence.v1")
self.assertEqual([arm["engine"] for arm in document["arms"]], ["vLLM", "SGLang"])
self.assertEqual(document["levels"], [12, 16, 24])
self.assertNotIn("profile", json.dumps(document).lower())
self.assertNotIn("configuration", json.dumps(document).lower())
self.assertNotIn("version", json.dumps(document).lower())
```

The fixture must use fictional documentation-only paths/IDs and include one deliberately excluded private arm so the test proves positive selection rather than deletion-based sanitization.

- [x] **Step 1.2: Verify the test fails for the missing implementation**

Run:

```bash
python -m unittest tests.test_static_evidence_pipeline -v
```

Expected: FAIL because the schema and generator do not exist.

- [x] **Step 1.3: Define the strict public schema**

Create a Draft 2020-12 schema with `additionalProperties: false` at every object boundary. Allow only:

```text
schema_version, study, methodology, metric_definitions,
levels, arms, synchronized_series, limitations
```

Each arm contains `engine`, visual identity, and measured points. Each point contains only public load/session counts, validity counts, and approved readings for:

```text
output_tps, ttft_p50_ms, ttft_p95_ms, tpot_p50_ms,
decode_p10_tps, error_rate_pct, running_requests_mean,
waiting_requests_mean, cache_context, gpu_utilization_pct,
gpu_memory_gib, gpu_power_w
```

Every reading is `{available, value, unit, reason, evidence_state}`. Require `value: null` when unavailable and a non-empty reason. Restrict `engine` to `vLLM|SGLang` and levels to `12|16|24`.

- [x] **Step 1.4: Implement pure validation and deterministic serialization**

In `scripts/build_static_benchmark_evidence.py`, implement:

```python
def build_public_document(source: Mapping[str, object]) -> dict[str, object]: ...
def validate_public_document(document: Mapping[str, object], schema: Mapping[str, object]) -> None: ...
def serialize_public_document(document: Mapping[str, object]) -> bytes: ...
def write_if_valid(document: Mapping[str, object], schema_path: Path, output_path: Path) -> None: ...
```

Use a positive field map and `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"`. Write to a sibling temporary file and replace the destination only after schema and privacy validation succeed.

- [x] **Step 1.5: Add scientific validation cases**

Tests must reject:

- any engine besides the two public labels;
- any point outside 12/16/24;
- error rate above 1% presented as valid;
- averaged percentile inputs;
- unavailable values represented as zero;
- private 14-user evidence;
- non-finite values or negative counts;
- duplicate engine/load pairs;
- extra top-level or nested keys;
- output differences across two identical builds.

- [x] **Step 1.6: Run and commit the contract slice**

Run:

```bash
python -m unittest tests.test_static_evidence_pipeline -v
python -m pytest tests/test_static_evidence_pipeline.py -q
```

Expected: PASS.

Commit:

```bash
git add schemas/public-inference-evidence.v1.schema.json tests/fixtures/private-evidence-minimal.json tests/test_static_evidence_pipeline.py scripts/build_static_benchmark_evidence.py
git commit -m "feat: define public inference evidence contract"
```

---

## Task 2: Build and validate the local-only VictoriaMetrics evidence importer

**Files:**
- Create: `scripts/validate_benchmark_metrics.py`
- Create: `tests/test_validate_benchmark_metrics.py`
- Modify: `.gitignore`
- Runtime-only output: `.artifacts/private-evidence/receipt.json` (ignored, never committed)

**Interfaces:**
- Input: explicit native VictoriaMetrics `.gz` export, export manifest, declared UTC window, and loopback VictoriaMetrics URL.
- Internal output: value-free local receipt with checksums, counts, validation states, and query names.
- Public output: none. This tool must never write into `dashboard/`.

- [x] **Step 2.1: Write failing tests around import isolation**

Use an in-process HTTP test server to assert that the validator:

- refuses non-loopback VictoriaMetrics URLs;
- verifies the compressed-file checksum before upload;
- posts bytes only to the native import endpoint;
- queries only the declared time range;
- detects manifest series/sample mismatches;
- rejects missing client/engine/GPU metric families when declared;
- deduplicates returned samples by metric identity and timestamp;
- detects counter resets and out-of-window samples;
- records categories, not private values, in errors.

- [x] **Step 2.2: Implement the validation client**

Implement these boundaries:

```python
@dataclass(frozen=True)
class ImportSpec:
    archive: Path
    manifest: Path
    start: datetime
    end: datetime
    namespace: str

def assert_loopback_url(url: str) -> None: ...
def verify_export(spec: ImportSpec) -> VerifiedExport: ...
def import_native_export(spec: ImportSpec, victoria_url: str) -> ImportResult: ...
def run_validation_queries(spec: ImportSpec, victoria_url: str) -> ValidationResult: ...
def write_private_receipt(result: ValidationResult, receipt_path: Path) -> None: ...
```

Use `urllib.request` from the standard library. Do not log query results, label values, URLs with query strings, or matched content.

- [x] **Step 2.3: Ignore all local receipts and restored data**

Add only these targeted patterns to `.gitignore`:

```text
.artifacts/private-evidence/
.artifacts/victoriametrics-restore/
```

- [x] **Step 2.4: Run unit tests**

Run:

```bash
python -m unittest tests.test_validate_benchmark_metrics -v
```

Expected: PASS without Docker or network access.

- [x] **Step 2.5: Perform the real local import and exact-window validation**

For each final public source run, execute the validator against the existing loopback VictoriaMetrics container and save the ignored receipt. Import the private third profile only under a separate internal namespace to exercise exclusion, never as a public arm.

Confirm in the receipt:

- checksum matches the source manifest;
- imported series/sample count matches the source manifest;
- required client/engine/GPU families are present;
- exact-window aggregate queries reconcile with per-level report tables;
- no out-of-window samples or unhandled counter resets remain.

- [x] **Step 2.6: Inspect the existing local Grafana dashboards**

Set each dashboard to the declared UTC measurement window and check client, engine, and GPU panels for gaps, obvious time shifts, and reset artifacts. Record only pass/fail panel categories in the private receipt.

- [x] **Step 2.7: Commit the importer**

```bash
git add .gitignore scripts/validate_benchmark_metrics.py tests/test_validate_benchmark_metrics.py
git commit -m "feat: validate private benchmark metrics locally"
```

---

## Task 3: Generate the deterministic, privacy-safe Episode 01 data bundle

**Files:**
- Create: `dashboard/src/data/episode-1-public.v1.json`
- Create: `tests/test_episode1_public_evidence.py`
- Modify: `scripts/build_static_benchmark_evidence.py`
- Remove after migration: `dashboard/src/data/episode-1-instrument.json`

- [x] **Step 3.1: Add reconciliation tests against approved source aggregates**

The test validates the committed public bundle against a checked-in expectation map. Production generation accepts only explicit private run directories and passed local validation receipts. Assert exact values for every public engine/load/metric cell and ensure the 14-user profile is absent.

- [x] **Step 3.2: Add public claim-state derivation**

Derive these states without free-form source copy:

```text
measured, threshold_met, threshold_missed, invalid_level,
unavailable, not_established
```

Encode the declared decode threshold as `20 tok/s`, state that TTFT is reported but not gated, and keep capacity as `not_established` wherever source requirements were skipped or unmet.

- [x] **Step 3.3: Generate synchronized static series**

Emit aligned client, engine-native, and GPU series for the same declared windows. Deterministically downsample only when necessary; preserve first/last points and discontinuities. Never average published percentiles or coerce incompatible runtime-native gauges into one definition.

- [x] **Step 3.4: Generate and validate the public JSON**

Run the generator using the accepted final private source and Task 2 receipt. The committed JSON must contain no source path or private identifier and must be byte-identical on the second run.

- [x] **Step 3.5: Run reconciliation and schema tests**

```bash
python -m unittest tests.test_static_evidence_pipeline tests.test_episode1_public_evidence -v
python scripts/check_publication_privacy.py --root dashboard/src/data --files-only
```

Expected: PASS.

- [x] **Step 3.6: Commit the approved bundle**

```bash
git add dashboard/src/data/episode-1-public.v1.json tests/test_episode1_public_evidence.py scripts/build_static_benchmark_evidence.py
git rm dashboard/src/data/episode-1-instrument.json
git commit -m "data: publish sanitized episode 01 evidence"
```

---

## Task 4: Remove internal profile/configuration material from Episode 01

**Files:**
- Modify: `dashboard/src/instrument/evidence.ts`
- Modify: `dashboard/src/Episode1Instrument.tsx`
- Modify: `dashboard/src/instrument/LinkedMetricInstrument.tsx`
- Modify: `dashboard/src/instrument/EpisodeShell.tsx`
- Modify: `dashboard/src/styles.css`
- Modify: `tests/dashboard_instrument_contract.cjs`
- Modify: `tests/dashboard_instrument_acceptance.cjs`

- [x] **Step 4.1: Write failing public-copy and privacy assertions**

Assert that Episode 01 renders:

- arm labels exactly `vLLM` and `SGLang`;
- loads 12, 16, and 24;
- decode p10 and its 20 tok/s threshold;
- TTFT, TPOT, throughput, completion validity, queue trends, and GPU telemetry;
- provenance copy: `Aggregated from aligned client, engine, and GPU measurements; static publication bundle.`;
- `Recorded deployment comparison` and `Capacity not established` boundaries.

Assert that no configuration matrix, profile, version, flags, run IDs, paths, organization/tool names, or private 14-user result appears in DOM text.

- [x] **Step 4.2: Replace the evidence adapter input and types**

Import `episode-1-public.v1.json`. Remove `configuration` from `EvidenceArm`. Add metric definitions for `decode_p10_tps`, `running_requests`, and `waiting_requests`. Preserve metric direction and unavailable reasons from the static document.

- [x] **Step 4.3: Replace configuration UI with an evidence-boundary panel**

Remove the public configuration matrix. Render only:

- public engine identity;
- deployment-comparison caveat;
- measured-window protocol;
- observed/not-established split;
- threshold basis and limitations.

- [x] **Step 4.4: Add decode p10 threshold visualization**

Render the measured value, threshold line, pass/miss label, and a sentence explaining: “p10 means 90% of valid requests decoded at least this fast.” Use shape/text plus color.

- [x] **Step 4.5: Run UI contract and build checks**

```bash
node tests/dashboard_instrument_contract.cjs
npm run check --prefix dashboard
npm run build --prefix dashboard
```

Expected: PASS.

- [x] **Step 4.6: Commit the Episode 01 migration**

```bash
git add dashboard/src/instrument/evidence.ts dashboard/src/Episode1Instrument.tsx dashboard/src/instrument/LinkedMetricInstrument.tsx dashboard/src/instrument/EpisodeShell.tsx dashboard/src/styles.css tests/dashboard_instrument_contract.cjs tests/dashboard_instrument_acceptance.cjs
git commit -m "feat: publish privacy-safe episode 01 study"
```

---

## Task 5: Build the interactive methodology page

**Files:**
- Create: `dashboard/src/MethodologyPage.tsx`
- Create: `dashboard/src/methodology/RequestAnatomy.tsx`
- Create: `dashboard/src/methodology/SessionReplay.tsx`
- Create: `dashboard/src/methodology/EvidenceViews.tsx`
- Modify: `dashboard/src/App.tsx`
- Modify: `dashboard/src/styles.css`
- Create: `tests/dashboard_methodology_contract.cjs`
- Create: `tests/dashboard_methodology_acceptance.cjs`

- [x] **Step 5.1: Write failing route/content tests**

At `#methodology`, assert one H1, seven chapter controls, the 50/30/20 workload population, request-anatomy layers, the two-session replay, protocol gates, three synchronized evidence views, metric definitions, and the observed/not-established boundary.

- [x] **Step 5.2: Build the editorial page shell**

Use the existing ruled grid, Oswald display face, and Episode 00 palette. Add a sticky vertical chapter rail above 900px and horizontal scrollable chapter controls below it. Do not introduce card-grid dashboard styling.

- [x] **Step 5.3: Implement Request Anatomy**

Use accessible buttons to reveal six layers: system instructions, tool definitions, conversation history, tool calls/results, current instruction, expected output. Show anonymized token-shape bands only; no content excerpts.

- [x] **Step 5.4: Implement the scrub-controlled Two-session replay**

Use an `<input type="range">` with a textual ordered-list equivalent. The discrete stages are:

```text
instruction → generation → tool call → tool gap → tool result
→ accumulated context → next generation → human gap
```

Do not autoplay. Under `prefers-reduced-motion: reduce`, disable interpolation and update immediately.

- [x] **Step 5.5: Implement protocol and synchronized-evidence sections**

Render coherence → smoke → warm-up → measured window → validity → threshold → report. Align client-visible, engine-native, and GPU lanes over one time ruler ending at “static approved aggregates.”

- [x] **Step 5.6: Add plain-language definitions and evidence boundary**

Distinguish TTFT from server queue time, TPOT from decode tok/s, per-request versus whole-server measures, completion validity versus correctness, and comparable outcomes versus contextual telemetry.

- [x] **Step 5.7: Run methodology tests at 1440, 768, and 390 px**

```bash
node tests/dashboard_methodology_contract.cjs
node tests/dashboard_methodology_acceptance.cjs http://127.0.0.1:5173/
```

Expected: PASS, no horizontal overflow, and full keyboard operation.

- [x] **Step 5.8: Commit the methodology route**

```bash
git add dashboard/src/MethodologyPage.tsx dashboard/src/methodology dashboard/src/App.tsx dashboard/src/styles.css tests/dashboard_methodology_contract.cjs tests/dashboard_methodology_acceptance.cjs
git commit -m "feat: explain the benchmark methodology interactively"
```

---

## Task 6: Add persistent Light/Dark themes across every public route

**Files:**
- Create: `dashboard/src/theme.ts`
- Create: `dashboard/src/ThemeSwitch.tsx`
- Modify: `dashboard/index.html`
- Modify: `dashboard/src/App.tsx`
- Modify: `dashboard/src/styles.css`
- Create: `tests/dashboard_theme_contract.cjs`
- Create: `tests/dashboard_theme_acceptance.cjs`

- [x] **Step 6.1: Write failing behavior tests**

Assert:

- no stored choice follows `prefers-color-scheme`;
- clicking Light/Dark applies `data-theme` on `<html>`;
- the explicit choice persists across reloads and routes;
- exactly one switch button has `aria-pressed="true"`;
- the control is top-right and keyboard operable;
- the bootstrap runs before the module script to prevent a theme flash.

- [x] **Step 6.2: Implement the pre-paint bootstrap**

Add a tiny inline script in `<head>` that reads `token-by-token-theme`, validates `light|dark`, otherwise reads system preference, and sets `document.documentElement.dataset.theme`. It must not perform network or telemetry calls.

- [x] **Step 6.3: Implement the React controller**

Expose:

```ts
export type Theme = "light" | "dark";
export function getInitialTheme(): Theme;
export function applyTheme(theme: Theme): void;
```

`ThemeSwitch` renders two adjacent buttons labelled Light and Dark and announces the active theme without relying on color.

- [x] **Step 6.4: Tokenize all public colors**

Move page, ink, muted ink, rule, panel, focus, positive, negative, and contextual colors to CSS variables. Derive light mode from the Episode 00 palette; do not introduce new semantic hues.

- [x] **Step 6.5: Verify every public route in both themes**

Test Episode 00, Episode 01, Session Field Note, methodology, and index at desktop and mobile widths. Check focus visibility, chart contrast, SVG labels, print behavior, and 200% zoom.

- [x] **Step 6.6: Commit the theme system**

```bash
git add dashboard/index.html dashboard/src/theme.ts dashboard/src/ThemeSwitch.tsx dashboard/src/App.tsx dashboard/src/styles.css tests/dashboard_theme_contract.cjs tests/dashboard_theme_acceptance.cjs
git commit -m "feat: add persistent light and dark themes"
```

---

## Task 7: Add compiled-bundle privacy and offline-publication gates

**Files:**
- Modify: `scripts/check_publication_privacy.py`
- Modify: `tests/test_publication_privacy.py`
- Create: `tests/dashboard_offline_acceptance.cjs`
- Modify: `.github/workflows/ci.yml` if that is the active workflow; otherwise modify the existing dashboard workflow found during implementation.

- [x] **Step 7.1: Add failing privacy regressions**

Add category-only tests for forbidden public benchmark/tool and sponsor names, profile/configuration keys, known private optimization terms, versions attached to engine labels, run/result identifiers, endpoint syntax, and absolute paths. Ensure error output never echoes the matched value.

- [x] **Step 7.2: Support explicit compiled-asset scanning**

Add `--include-dir dashboard/dist` or an equivalent explicit root list so normal source scans continue excluding generic `dist`, while the publication gate scans the generated JS/CSS/HTML bundle.

- [x] **Step 7.3: Add the offline browser test**

Build the site, serve `dashboard/dist`, abort every HTTP request not targeting the local static server, then visit every public hash. Assert charts and methodology content render with no failed external dependency.

- [x] **Step 7.4: Add CI ordering**

CI must execute:

```text
Python evidence/privacy tests
→ TypeScript check
→ Vite production build
→ compiled-bundle privacy scan
→ offline Playwright test
```

- [x] **Step 7.5: Run and commit publication gates**

```bash
python -m unittest tests.test_publication_privacy -v
npm run build --prefix dashboard
python scripts/check_publication_privacy.py --root dashboard/dist --files-only
node tests/dashboard_offline_acceptance.cjs dashboard/dist
```

Expected: PASS.

Commit:

```bash
git add scripts/check_publication_privacy.py tests/test_publication_privacy.py tests/dashboard_offline_acceptance.cjs .github/workflows
git commit -m "test: gate static publication privacy and offline use"
```

---

## Task 8: Run responsive, accessibility, preservation, and visual QA

**Files:**
- Modify only defects found in `dashboard/src/**`
- Modify only necessary acceptance tests under `tests/`
- Create: `docs/validation/2026-10-06-static-site-qa.md`
- Create screenshots under: `docs/dashboard-captures/static-evidence/`

- [x] **Step 8.1: Run the complete automated suite**

```bash
python -m pytest -q
npm run check --prefix dashboard
npm run build --prefix dashboard
for test in tests/dashboard_*_contract.cjs; do node "$test"; done
```

Then run all applicable Playwright acceptance scripts against one local server.

- [x] **Step 8.2: Verify preservation explicitly**

Confirm Episode 00, Session Field Note, canonical hash routes, fixture/lab routes, and all concept artifacts still render and retain their data. No route may silently redirect to Episode 01.

- [x] **Step 8.3: Run keyboard and reduced-motion QA**

Tab through navigation, theme switch, episode selection, load sweeper, request anatomy, and session replay. Verify visible focus, logical order, correct focus restoration, no keyboard traps, and reduced-motion behavior.

- [x] **Step 8.4: Capture both themes at all target widths**

Capture Episode 01 and methodology at 1440, 768, and 390 px in Light and Dark. Inspect typography, clipping, chart labels, semantic colors, overflow, sticky controls, and 200% zoom.

- [x] **Step 8.5: Run the source and compiled privacy scans one final time**

```bash
python scripts/check_publication_privacy.py --root .
python scripts/check_publication_privacy.py --root dashboard/dist --files-only
```

- [x] **Step 8.6: Record exact evidence**

Write the commands, pass/fail results, screenshot paths, inspected routes, browser widths, and known limitations in `docs/validation/2026-10-06-static-site-qa.md`. Do not copy private receipt contents.

- [x] **Step 8.7: Commit QA fixes and evidence**

```bash
git add dashboard/src tests docs/validation/2026-10-06-static-site-qa.md docs/dashboard-captures/static-evidence
git commit -m "test: verify the static benchmark experience"
```

---

## Task 9: Reconcile documentation, record evidence, and complete final review

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-10-06-static-evidence-methodology-theme-design.md`
- Modify: this plan
- Create or modify the current operational handoff under `handoffs/`

- [x] **Step 9.1: Document the one-time evidence lifecycle**

State clearly that VictoriaMetrics/Grafana are needed only when approved source evidence changes; ordinary builds and all public viewing use the committed static JSON alone.

- [x] **Step 9.2: Document reproducible public build commands**

Include schema tests, static generation, privacy scan, dashboard build, compiled scan, and offline test. Refer to private inputs by role, never by internal path or identifier.

- [x] **Step 9.3: Update status documents**

Mark the design spec implemented only after all verification passes. Check every completed item in this plan and leave incomplete work unchecked with a concise reason.

- [x] **Step 9.4: Review the complete diff**

```bash
git status --short
git diff --check
git diff --stat origin/codex/episode-1-local-prep...HEAD
git log --oneline --decorate -15
```

Confirm unrelated user changes were not staged or rewritten.

- [x] **Step 9.5: Request final code/design review and fix findings**

Review for scientific claims, privacy, accessibility, static/offline behavior, theme consistency, and preservation. Re-run affected tests after every fix.

- [x] **Step 9.6: Commit the handoff**

```bash
git add README.md docs/superpowers/specs/2026-10-06-static-evidence-methodology-theme-design.md docs/superpowers/plans/2026-10-06-static-evidence-methodology-theme.md handoffs
git commit -m "docs: hand off the static benchmark publication"
```

## Definition of done

- [x] Every progress-overview item and implementation step is checked.
- [x] Public source and compiled assets contain no prohibited internal material.
- [x] Episode 01 uses only valid matched 12/16/24-user evidence and makes no engine-only causal or capacity claim.
- [x] Methodology explains what, why, and how without naming the private tool or sponsor.
- [x] Light and Dark themes work on every public route without first-paint flash.
- [x] The production bundle works with all non-local network access blocked.
- [x] Episode 00, Session Field Note, legacy routes, and archived concepts are preserved.
- [x] Exact test/build/QA evidence is recorded, and any unverified external publishing step is labeled unverified.
