# Canonical execution-readiness handoff

Timestamp: 2026-10-02T21:27:47Z

Implementation owner: `/root/execution_readiness` using `gpt-5.6-sol` at medium
reasoning. Review budget was one initial 30-minute implementation/review round out of
a maximum of three. No commit or push was made. No paid provider action was performed.

## Delivered

- A fixed JSON launch bundle maps one-to-one to the existing
  `scripts/execute_episode1.py` production interface.
- A fail-closed controller exposes status, read-only preflight and asynchronous launch.
  The browser cannot provide commands, file paths or a provider adapter.
- Paid launch is disabled by default. Enabling it at server start does not bypass the
  exact digest/max-charge phrase, retained authorization source/receipt, freshness,
  source/build/material closure or production runner validation.
- The dashboard has a separate canonical launch route. The endpoint rehearsal console
  remains clearly noncanonical.
- Reordered endpoint-rehearsal results record `episode_numbering_version: episode-catalog.v2` and their
  `previous_episode`; historical results are not rewritten.

Execution-readiness owner files: `dashboard/src/App.tsx`,
`dashboard/src/CanonicalLaunch.tsx`, the canonical additions in
`dashboard/src/styles.css`, `docs/canonical-launch.md`,
`examples/canonical-launch-bundle.example.json`, `scripts/episode1_playground.py`,
`scripts/execute_episode1.py`, `src/runpod_benchmark/canonical_launch.py`, the
numbering-provenance additions in `src/runpod_benchmark/episode_suite.py`,
`tests/test_canonical_launch.py`, the related assertions in
`tests/test_episode_suite.py`, `tests/test_execute_episode1_cli_assembly.py`, and this
handoff/review log. Shared catalog and observability files remain owned by their
respective sibling implementations.

## Readiness by current episode number

| Current | Previous | Readiness | Missing boundary |
|---:|---:|---|---|
| 0 | 0 | Recorded exploratory study only | Not a canonical launch adapter |
| 1 | 1 | **Executable production adapter** | Runtime-bound plan/receipt/SKU/model/image/price inputs are intentionally supplied at launch time |
| 2 | 2 | Missing code | Reproducibility workload, reset and evidence adapter |
| 3 | 8 | Missing code | Native prefix-cache controls, reset and hit/miss capture |
| 4 | 9 | Missing code | Batching, scheduler and mixed-traffic workload/telemetry adapter |
| 5 | 10 | Missing code | Attention-backend and weight/KV precision validation adapter |
| 6 | 11 | Missing code | Speculative-decoding and structured-output workload/telemetry adapter |
| 7 | 12 | Missing code | Single-node DP/TP/PP/EP topology and collective adapter |
| 8 | 13 | Missing code | Multi-GPU topology/collective adapter |
| 9 | 14 | Missing code | Disaggregation/routing/cache-ownership adapter |
| 10 | 15 | Architecture choice, then code | Existing Slurm/Kubernetes cluster vs authorized temporary RunPod cluster |
| 11 | 3 | Missing code | TensorLab/model-internals instrumentation and workload |
| 12 | 4 | Missing code | LoRA/QLoRA training, checkpoint and quality capture |
| 13 | 5 | Architecture choice, then code | Real Jev API and supported version |
| 14 | 6 | Missing code | Packaging/build/release validation workload |
| 15 | 7 | Missing code | Canonical saturation/SLO/load/recovery workload |
| 16 | 16 | Missing code | Release-gate, rollback, recovery and capstone evidence adapter |

Runtime GPU/SKU, GPU count, model/revision, image digests, provider region/cloud,
price ceiling and exact owner approval are not missing implementation. They must be
bound into the current plan and authorization artifacts before a launch.

## Metrics contract for follow-on adapters

Common target panels are TTFT, TPOT and end-to-end p50/p95/p99; request and token
throughput; request/error counts and error rate; exact token ITL when instrumented;
client SSE inter-chunk cadence under a distinct name; GPU utilization, memory and
power; queue delay/depth; cache hit/eviction; cost and complete configuration/repeat
provenance. Episode-specific panels add scheduling fairness, quantization quality,
speculative acceptance, topology/collectives, routing/cache ownership, training and
checkpoint quality, packaging/recovery and saturation/SLO evidence.

The current rehearsal exporter is narrower: `inference_lab_<metric>` summary gauges
with labels `episode`, `suite_round`, `cell`, `profile`, `statistic`, plus
`inference_lab_requests_total` as a gauge with `status`. It measures client SSE
inter-chunk latency, not exact token ITL. It has no histogram/rate series and no remote
queue, cache or cost metrics. Local `nvidia-smi` values describe bridge-host visible
GPUs and are not endpoint-attributable. Dashboards must label these limitations rather
than infer unavailable metrics.

## Verification and next work

- Passed: `PYTHONPATH=src .venv/bin/python -m pytest -q
  tests/test_canonical_launch.py tests/test_episode_suite.py
  tests/test_episode1_orchestrator.py tests/test_execute_episode1_cli_assembly.py`
  — 25 tests.
- Passed: Python compilation of the controller and bridge; `git diff --check`.
- Passed: Docker TypeScript/Vite production build (35 modules) and local Chrome
  acceptance of `#canonical-launch`; the final DOM showed the canonical route current,
  `NOT CONFIGURED`, `not-configured`, paid launch disabled, and both actions disabled.
- Passed: no-bundle preflight and launch each returned HTTP 400 with the exact safe
  response `no canonical launch bundle was configured at server start`.
- The host `node_modules` tree is empty/incomplete; Docker is the frontend evidence.
- The observability owner subsequently reported consolidated-review fixes `CR-01` and
  `CR-04` resolved with five direct tests, compose/diff checks, a provisioned 23-panel
  Grafana dashboard and live VictoriaMetrics health. This handoff still claims only
  the execution slice; target-only metrics remain absent until their collectors exist.
- Next code phases should implement one real workload adapter at a time against the
  controller/production lifecycle extension points. Do not expand the prompt-rehearsal
  facade or call it canonical.
