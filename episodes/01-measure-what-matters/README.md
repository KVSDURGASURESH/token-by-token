# Episode 1 — Measure What Matters

> **Recorded exploratory deployment comparison.** Capacity was not established,
> and the evidence does not isolate an engine-only causal effect.

Episode 1 asks what breaks first when two inference-engine deployments meet the
same H200 workload. It compares only the public engine identities `vLLM` and
`SGLang` at the matched measured levels of 12, 16, and 24 simulated users.
Serving profiles, software versions, launch flags, and optimization recipes are
intentionally withheld.

## What, why, and how

- **What:** client-visible latency, delivered output, completion validity,
  runtime queue context, and GPU telemetry aligned over the same recorded
  windows.
- **Why:** aggregate throughput alone can hide a worse request experience, and
  a runtime-native metric alone cannot establish a fair cross-engine result.
- **How:** replay realistic multi-turn sessions, apply warm-up and measured
  windows, reject invalid levels, and publish only allowlisted aggregates with
  explicit observed/not-established boundaries.

The declared decode gate is p10 ≥ 20 tok/s: 90% of valid requests must decode
at least that fast. TTFT remains reported evidence, not a capacity gate. All
comparisons are recorded deployment observations; they are not universal
engine rankings.

## Explore it locally

From `dashboard/`, install the locked dependencies and start the local site:

```bash
npm ci
npm run dev
```

Open:

- `http://127.0.0.1:5173/#episode-1` for the recorded Episode 01 evidence;
- `http://127.0.0.1:5173/#methodology` for request anatomy, session replay,
  protocol gates, and metric definitions;
- `http://127.0.0.1:5173/#episode-1-fixture` only for the preserved local UI
  fixture. Fixture values are not benchmark evidence.

The production site is static. It reads the committed sanitized evidence JSON
and does not contact VictoriaMetrics, Grafana, a provider, or the private source
repository.

## Reproduce the public build

```bash
python3 -m unittest tests.test_episode1_public_evidence tests.test_publication_privacy
python3 scripts/check_publication_privacy.py --root .
npm --prefix dashboard run check
npm --prefix dashboard run build
python3 scripts/check_publication_privacy.py --root dashboard/dist --files-only
node tests/dashboard_offline_acceptance.cjs dashboard/dist
```

The metrics-import pipeline is used again only when an approved private evidence
release changes. Private reports, raw telemetry, validation receipts, serving
profiles, and source content must never be committed or copied into the public
site.

## Evidence boundary

The page may support statements about the recorded matched measurements. It does
not establish capacity, task-solving quality, statistical significance,
production certification, a universal engine winner, or the effect of any
withheld configuration difference. A paid rerun still requires a separately
approved execution plan and does not follow from this guide.
