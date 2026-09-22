# Token by Token — Inference Lab — Episode 0

**Token by Token — Inference Lab** is a local-first framework for learning model
serving through repeatable experiments. We test changes against a use case's
quality, latency, memory and cost targets, then combine and retest promising
settings. This package implements the single-GPU foundation.

Episode 0 asks one narrow question: under this recorded synthetic closed-loop
workload, how did vLLM 0.29.0 and SGLang 0.5.20 behave while serving
Qwen/Qwen2.5-32B-Instruct on one recorded NVIDIA H100 80GB HBM3 per run?

This candidate repository contains three deliberately separate workflows:

1. **Fixture demo:** rebuild a zero-cost bundle from the included sanitized
   aggregate study. This is deterministic local software exercise, not a new
   benchmark result.
2. **Historical aggregate inspection:** verify and view the checksum-bound
   Episode 0 snapshot. It contains aggregate evidence from earlier paid runs,
   not request payloads or raw per-request observations.
3. **New measurement:** a complete operator path for a fresh Runpod Pod,
   runtime startup, deterministic endpoint traffic, runtime/GPU telemetry,
   normalization, evidence capture, and verified deletion. It requires a fresh
   fully bound plan, immutable image digest, maximum charge, and the owner's
   exact approval before any resource creation.

Cloning or running this repository authorizes no provider call, resource
creation, purchase, or publication.

| I want to... | Start here | Provider cost |
|---|---|---:|
| Explore the workflow and dashboard | [Zero-cost quickstart](#zero-cost-quickstart), then [Native dashboard](#native-dashboard) | $0 |
| Inspect the recorded H100 80GB study | [Native dashboard](#native-dashboard) | $0 |
| Produce a fresh GPU measurement | [Runpod setup and GPU selection](docs/runpod-setup.md), then [live-run procedure](docs/live-run.md) | Paid, only after plan approval |

Episode 0 develops the serving foundation. The dashboard is the interactive,
source-backed view of the checked-in aggregate study. Read the [results](docs/results.md),
[cost evidence](docs/cost-evidence.md), [experiment roadmap](docs/roadmap.md) and
[three capstone charters](docs/capstone-projects.md) for the evidence and planned scope.

## What Episode 0 records

The retained study uses BF16, a 16,384-token context, prefix caching and chunked
prefill on both runtimes, and six input/concurrency cells with two or three
repetitions per cell. The public snapshot reports 936 successful requests and
zero recorded failures. That count is not a reliability or quality claim.

The 8192-token, concurrency-32 cell recorded 57.5 versus 43.7 delivered output
tokens/s and median TTFT of 47.9 versus 88.3 seconds for vLLM versus SGLang.
Those arms did unequal delivered work: mean outputs were 99.89 versus 128.00
tokens per successful request under the same 128-token cap, and stop reasons
were unavailable. The comparison therefore does not establish equal-output
efficiency. Tail statistics are descriptive, with only two independent stress
repetitions and no uncertainty estimate or predeclared SLO goodput.

One-second GPU and runtime-native samples are supporting observations. Native
occupancy denominators are not proven comparable across runtimes, and the
samples do not establish cause, sustained saturation, or simultaneous peaks.
The public snapshot lacks immutable runtime image digests, machine/topology
identity, tokenizer digest, exact harness commit, arm order, raw repetitions,
stop reasons, and output-length distributions. It is exploratory evidence, not
a production-capacity result or a universal runtime ranking.

The combined recorded debit was approximately USD 2.19. Per-run cost allocation
is unavailable. The snapshot retains historical cleanup evidence; it is not a
provider-side recheck performed by this repository.

## Zero-cost quickstart

Requirements: Python 3.12. The commands below use only the standard library,
do not use credentials, and do not contact a provider.

Clone or download the repository, open a terminal in its root directory, and
run:

```bash
python3 scripts/verify_bundle.py data/public
python3 scripts/rehearse_workflow.py --output /tmp/inference-lab-episode-0
python3 scripts/verify_bundle.py /tmp/inference-lab-episode-0
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The rehearsal output must be a new or empty directory. It is labeled
`fixture_zero_cost`, records zero provider attempts and resources, and compiles
a deliberately nonapprovable plan with zero cost. It reuses the included
historical aggregate values so readers can exercise the evidence pipeline.

## Native dashboard

The React/TypeScript dashboard opens on the same normalized historical study as
`data/public/dashboard/latest.json`. After normalizing a new private run, choose
**Open local results** (`#local-results`) to inspect a normalized benchmark JSON
directly in the browser. You may also open its matching runtime
summary JSON; GPU summaries are not accepted by this reader. Files stay local
to the page and are not uploaded. The reader keeps each row's `cell_id` and
`repetition`, and it does not attach the historical telemetry panels to newly
imported results.

Dashboard requirements: Node.js 22.12 or newer (CI uses Node 22) and npm.

```bash
npm --prefix dashboard ci
npm --prefix dashboard run check
npm --prefix dashboard run build
npm --prefix dashboard run dev
```

Open the loopback URL printed by Vite. `npm ci` may need registry access on a
fresh machine; the Python fixture and bundle verifier need no third-party Python
packages. The dashboard is read-only and contains no provisioning control.

## Run a new measurement

Use the canonical [Runpod setup and GPU selection](docs/runpod-setup.md) guide.
It links the current Runpod console and official documentation, explains the
recorded H100 80GB/Qwen 32B BF16 path and smaller-model options, and gives the
exact template, SSH, storage, port, approval, and teardown sequence. The
ordered [live-run procedure](docs/live-run.md) owns the commands after approval;
[execution-plan authoring](docs/execution-plan-authoring.md) owns every field in
the digest-bound one-runtime plan.

The historical container images and Runpod template IDs are unknown. The
[recommended runtime profile](config/recommended-h100-qwen32b.json) is explicitly
for a future run; it does not retroactively identify the images used for the
recorded Episode 0 data. Each runtime arm needs its own approved plan and Pod,
followed by permanent deletion and billing reconciliation. Running local
documentation or validation commands grants no spend approval.

## Evidence layers

| Layer | What it proves | What it does not prove |
|---|---|---|
| `data/public/` | Integrity and internal consistency of the reviewed sanitized aggregate snapshot | Statistical validity, missing provenance, or reproducibility of a paid GPU run |
| Fixture rehearsal | The local compiler, asset builder, dashboard data staging, and verifier work together without provider calls | A new measurement or independent reproduction |
| New paid run | Only evidence produced under a newly approved digest-bound plan | Permission to publish, or claims beyond the approved protocol |

## Capability map

| Capability | Status | Boundary |
|---|---|---|
| Checksum and semantic verification | Implemented | Rejects drift, unsafe paths, sensitive patterns, inconsistent counts, and dashboard divergence |
| Zero-cost fixture rehearsal | Implemented | Replays sanitized historical aggregates; never contacts a provider |
| Client TTFT, TPOT, ITL, E2E, throughput, failures, goodput calculations | Implemented | Goodput is unavailable without a declared SLO contract |
| OpenAI-compatible streaming client | Implemented source | Requires a one-runtime execution-ready plan, pinned Transformers 5.17.0, and an operator-host SSH tunnel; excluded from CI |
| Loopback runtime metrics collection | Implemented source | vLLM/SGLang metric names remain runtime-specific |
| GPU CSV summarization and normalized publication assets | Implemented | Aggregates only; raw measurements stay private |
| Native dashboard | Implemented | Historical view plus a browser-local importer for normalized new-run results; imported rows retain cell/repetition identity |
| Runpod Pod creation | Operator command after approval | Current CLI help and the approved plan remain authoritative; the project never auto-creates in CI |
| Deadline and budget watchdogs | Implemented for the documented local-only fallback | Provider-enforced readable termination is preferred; degraded mode needs separate risk acknowledgement |
| Permanent Pod deletion proof | Implemented for local-only watchdog mode; documented for all runs | A stop is not deletion; inventory absence and direct `not_found` are required |
| Open-loop SLO goodput, eBPF attribution, TGI/TensorRT-LLM arms, TP/PP/DP studies, cache-aware routing | Proposed | No Episode 0 measurements support these claims |
| Reproduction-grade provenance and randomized paired allocations | Proposed | The current live path produces independent one-runtime arms, not paired same-GPU evidence |

The client-side tokenizer dependency remains an environment input and must be
pinned in the execution plan along with the exact Python, Transformers, and
tokenizer versions. Runtime images are version-tagged in the recommended
profile but become execution inputs only after OCI digest resolution and review.

## Metric contract

- **TTFT:** actual request send to first non-empty streamed content delta.
- **TPOT:** first-to-last content span divided by exact post-first output tokens.
- **Client ITL:** gaps between non-empty streamed content deltas; it is not server
  token latency.
- **E2E:** send through validated terminal stream and exact usage.
- **Delivered output rate:** successful output tokens divided by measured cell
  wall time.
- **Goodput:** SLO-qualifying output tokens divided by the same wall time; it is
  unavailable without a nonempty SLO contract.

See [docs/metric-definitions.md](docs/metric-definitions.md) for the complete
sample, percentile, telemetry, and comparison rules.

## Ownership and licensing status

This is a local publication candidate. No `LICENSE` or data license is included
because ownership, dependency attribution, and license compatibility have not
yet been confirmed. No permission to copy, modify, or redistribute is granted
by this candidate beyond rights that apply independently. Before a public push,
the owner must choose and add explicit code, data, and documentation terms;
confirm authorship of every copied file; preserve third-party notices; and
verify that model weights, tokenizer files, vendor documentation, and marks are
not redistributed or relicensed.

The model repository and exact recorded revision are referenced as provenance;
model artifacts are not included.

## Contributing and citation

Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing an experiment. Until
the licensing decision is complete, this candidate should not be published or
used to solicit external contributions. The owner must also choose the actual
repository destination before release. Citation and community-policy files can
be added when their real authorship and contact details are known; this
candidate does not invent them.
