<p align="center">
  <img src="assets/token-by-token.svg" alt="Token by Token" width="96">
</p>

# Token by Token

**Inference Lab** is a hands-on series for learning how LLM inference works
and choosing a serving configuration that fits a use case. An interactive
assistant needs a fast first token; a batch job needs useful work per dollar;
a long-context application needs room for its KV cache. One benchmark score
cannot answer all three questions.

We work through the concepts, test optimizations in sequence, and measure their
effects against declared quality, latency, memory, throughput, and cost targets.
Promising settings are then combined and retested against the baseline. Each
episode records what its evidence supports and what remains unknown.

The repository is local-first: you can inspect retained public evidence,
rehearse the measurement workflow, and exercise the public harness without
renting a GPU. The hosted study dashboard is available at
[tokenbytoken.org](https://tokenbytoken.org). A fresh provider measurement is a
separate, paid workflow that requires a
fully bound plan and the owner's exact approval before any resource is created.

An [unreleased public-client candidate](client/README.md) now describes every
Episode 00–16 contract and runs a deterministic offline self-test that writes a
locally verifiable evidence bundle. It costs $0 and makes no provider call. The
self-test validates client plumbing only; it is not benchmark evidence, and
real GPU runs remain unavailable. An optional local AgentBench binary now
exercises the actual coordinator against a loopback mock. Its boundary and
limits are tracked in the [local wrapper implementation status](docs/agentbench-wrapper-implementation.md).

## Episodes

<!-- BEGIN EPISODE INDEX -->
| Episode | Experiment | Status | Evidence |
|---:|---|---|---|
| 0 | [Warm-up](episodes/00-warm-up/README.md) | Available | Exploratory recorded study |
| 1 | [Measure what matters](episodes/01-measure-what-matters/README.md) | Available | Recorded exploratory H200 runtime comparison at tested loads; maximum sustainable rate not measured |
| 2 | Equal-work runtime baseline | Planned | Planned — no measurements |
| 3 | Prefix reuse | Planned | Planned — no measurements |
| 4 | Batching, scheduling and mixed traffic | Planned | Planned — no measurements |
| 5 | Attention kernels and precision | Planned | Planned — no measurements |
| 6 | Speculative decoding and structured outputs | Planned | Planned — no measurements |
| 7 | Parallelism within one node | Planned | Planned — no measurements |
| 8 | Parallelism across nodes | Planned | Planned — no measurements |
| 9 | Prefill/decode disaggregation and cache-aware routing | Planned | Planned — no measurements |
| 10 | Slurm and Kubernetes orchestration | Planned | Planned platform study — no measurements |
| 11 | Model internals: weights to optimization | Planned | Planned companion study — no measurements |
| 12 | LoRA and QLoRA with held-out evaluation | Planned | Planned companion study — no measurements |
| 13 | SYSTEM 1 and LLMs on labeled decision tasks | Planned | Planned companion study — no measurements |
| 14 | Packaging, accelerator preflight and memory containment | Planned | Planned — no measurements |
| 15 | Saturation, SLO and cost | Planned | Planned — no measurements |
| 16 | Release gates, recovery and capstone synthesis | Planned | Planned capstone synthesis — no measurements |
<!-- END EPISODE INDEX -->

The [three capstone projects](docs/capstone-projects.md) explain where these
experiments lead. The [canonical roadmap](docs/roadmap.md) owns the planned sequence. Future
topics are proposals until an episode publishes evidence; they are not results
or authorization to spend.

## Start here

The repository is public at
[`KVSDURGASURESH/token-by-token`](https://github.com/KVSDURGASURESH/token-by-token).
The commands below take you from a fresh clone to the checked-in results and a
repeatable zero-cost harness rehearsal. Run them in a POSIX
shell on macOS, Linux, or WSL.

### 1. Clone and check prerequisites

```bash
git clone https://github.com/KVSDURGASURESH/token-by-token.git
cd token-by-token
python3 --version
node --version
npm --version
```

Use Python 3.12 or newer and Node.js 22.12 or newer in the Node 22.x line; npm
comes with Node.js. CI tests Python 3.12 and Node 22. If `python3 --version`
reports an older Python, set `PYTHON_BIN` to an installed 3.12+ executable
(for example, `export PYTHON_BIN=python3.12`) before the next block.

### 2. Verify the recorded data and rehearse the workflow

```bash
PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ is required"'
"$PYTHON_BIN" scripts/verify_bundle.py data/public
REHEARSAL_DIR="$(mktemp -d "${TMPDIR:-/tmp}/inference-lab-episode-0.XXXXXX")"
printf '%s\n' "$REHEARSAL_DIR"
"$PYTHON_BIN" scripts/rehearse_workflow.py --output "$REHEARSAL_DIR"
"$PYTHON_BIN" scripts/verify_bundle.py "$REHEARSAL_DIR"
"$PYTHON_BIN" -m venv .venv
. .venv/bin/activate
python -m pip install '.[test]'
python -m unittest discover -s tests -p 'test_offline_workflow.py' -v
```

The two verifier commands should report JSON containing `"ok":true`; the
rehearsal prints a one-line JSON result containing
`"classification":"fixture_zero_cost"`,
`"paid_resources_created":0`, and `"provider_attempts":0`. The focused offline
tests should finish with `OK`. The full operator test suite additionally needs
the locked live dependency set; see [CONTRIBUTING.md](CONTRIBUTING.md).
The unique temporary directory makes the block safe to run
again in the same shell.

`data/public/` is the checksum-bound, sanitized snapshot of the recorded
historical measurement. `$REHEARSAL_DIR/` is newly generated fixture output: it
reuses sanitized aggregates to exercise the workflow, makes no provider call,
creates no paid resource, records no new measurement, and compiles a
deliberately nonapprovable zero-cost plan.

### 3. Explore the dashboard and run the public client

Open the production dashboard at [tokenbytoken.org](https://tokenbytoken.org)
to read the recorded studies and methodology. Its application and deployment
source are maintained privately so this public repository can stay focused on
the runnable harness, experiment contracts, verification tools, attribution,
and sanitized evidence under `data/public/` and `public-data/`.

To try the isolated client, follow its
[source quick start](client/README.md#quick-start-from-source). The client has
its own package boundary, tests, threat model, locked standalone build, and
release checklist. No binary or package-registry release has been published.

For an Episode 1 first run from this checkout, use the active Python 3.12+
virtual environment from step 2:

```bash
python -m pip install ./client
EPISODE1_DIR="$(mktemp -d "${TMPDIR:-/tmp}/inference-lab-episode-1.XXXXXX")"
token-by-token episode 1 describe
token-by-token capabilities --episode 1
token-by-token episode 1 selftest --offline --users 16 --seed 42 \
  --output "$EPISODE1_DIR/episode-01.tbt.zip"
token-by-token evidence verify "$EPISODE1_DIR/episode-01.tbt.zip"
```

The result must say `synthetic_mock`. This tests installation, the client, and
bundle verification without a GPU or provider call. `capabilities` reports
real execution as unavailable; this command does not measure Episode 1 latency
or run AgentBench. The [recorded Episode 1 study](episodes/01-measure-what-matters/README.md)
is a separate exploratory result.

Continue with [Episode 0](episodes/00-warm-up/README.md) to inspect the retained
study and understand the experiment's limits. The Episode 0
[local-exploration notes](episodes/00-warm-up/README.md#explore-it-locally)
explain what the fixture and recorded evidence can establish. The hosted
[episode index](https://tokenbytoken.org/episodes/) is the default reading path.

Episode 01 is the recorded H200 deployment comparison. Open
[`Episode 01`](https://tokenbytoken.org/episodes/01-measure-what-matters/) to explore the matched 12,
16, and 24-user evidence, or [`Methodology`](https://tokenbytoken.org/methodology/)
to see how realistic multi-turn sessions, protocol gates, and aligned client,
engine, and GPU measurements become a public result. Both pages are static and
work in Light or Dark mode.

For a zero-GPU streamed request race, use the Episode 1
[Quick test](docs/episode-1-preparation/quick-test.md). The supported path is the
operator CLI; it is separate from this static public dashboard. Quick-test
results are interactive diagnostics, not the ShareGPT/GSM8K benchmark evidence
defined for Episode 1. Use `scripts/quick-test request` or
`scripts/quick-test compare` against the loopback bridge described there.
For a second-machine checkout, follow the concise
[Episode 1 remote handoff](docs/episode-1-preparation/remote-handoff.md). Agents
resuming work across machines should start with the repository's timestamped
[cross-machine handoff log](handoffs/README.md).

## Evidence and spending boundary

The checked-in public data is a sanitized aggregate snapshot. It is useful for
learning and exploratory analysis; it does not recover missing provenance or
turn the historical study into a reproducible production benchmark. Cloning or
running this repository authorizes no provider call, purchase, resource
creation, publication, or redistribution.

A new paid run must follow the canonical [Runpod setup](docs/runpod-setup.md),
[live-run procedure](docs/live-run.md), and
[execution-plan authoring guide](docs/execution-plan-authoring.md). Each run
needs an immutable image digest, maximum charge, exact approval, permanent
deletion of every created resource, and provider-side verification of deletion.

### Static publication lifecycle

The metrics import is a one-time construction step for each approved evidence
release. Local VictoriaMetrics and Grafana are used to validate the source
windows and produce the allowlisted aggregate document; they are not website
dependencies. Ordinary builds and every public page use only the committed
`public-data/site-v2/episode-1.json`. The raw metrics export, private
reports, receipts, containers, and dashboards are neither published nor needed
again unless the approved source evidence changes.

Rebuild and verify the committed public site with:

```bash
python3 -m unittest tests.test_static_evidence_pipeline tests.test_episode1_public_evidence tests.test_publication_privacy
python3 scripts/check_publication_privacy.py --root .
python3 scripts/check_public_repository_boundary.py
python3 scripts/update_episode_index.py --check
```

When—and only when—an approved private evidence release changes, regenerate the
static document locally with `scripts/build_static_benchmark_evidence.py`. Pass
the three private run directories by evidence role, the successful validation
receipts, the public schema, and the public output path. Then run the entire
sequence above. Never commit the private inputs or receipts. The exact local QA
record is in
[docs/validation/2026-10-06-static-site-qa.md](docs/validation/2026-10-06-static-site-qa.md).

## Contributing and licensing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing an episode or
experiment. Original repository materials are available under the
[MIT License](LICENSE); see [OWNERSHIP.md](OWNERSHIP.md) for its scope and the
third-party boundaries.

## Hosted dashboard boundary

The production dashboard is hosted at [tokenbytoken.org](https://tokenbytoken.org).
Its UI, SEO build, deployment configuration, and editorial production assets
are maintained in a private repository. This repository intentionally publishes
the portable harness and the allowlisted static evidence under
`public-data/site-v2/`. Those projections omit serving profiles, private
endpoints, credentials, raw request payloads, and private deployment recipes.

Changes to public evidence must pass the privacy scanner, schema and bundle
verification, and `scripts/check_public_repository_boundary.py`. The private
dashboard imports only an allowlisted copy pinned to a reviewed public commit.

### Privacy-first reader analytics

Reader analytics is disabled unless the private production build receives the
approved tracker configuration and explicit production-domain allowlist. The
event contract permits aggregate page/section views, fixed scroll depths, and
named interface actions; it excludes free-form input, exact pointer capture,
session replay, and distinct-user profiling.

The integration asks Umami to respect the browser Do Not Track preference and
uses its cookie-free tracker. Hosting and configuration still need an owner
privacy review: select the intended data region, sign a DPA when applicable,
set retention and access controls, and update the public privacy notice before
production collection. See `docs/analytics.md` for the event contract and
deployment checklist.

Dashboard deployment and production verification are managed separately from
the public harness release process.
