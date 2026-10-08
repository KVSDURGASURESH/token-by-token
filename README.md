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
rehearse the measurement workflow, and run the dashboard without renting a
GPU. A fresh provider measurement is a separate, paid workflow that requires a
fully bound plan and the owner's exact approval before any resource is created.

## Episodes

<!-- BEGIN EPISODE INDEX -->
| Episode | Experiment | Status | Evidence |
|---:|---|---|---|
| 0 | [Warm-up](episodes/00-warm-up/README.md) | Available | Exploratory recorded study |
| 1 | [Measure what matters](episodes/01-measure-what-matters/README.md) | Available | Recorded exploratory H200 runtime comparison — capacity not established |
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
| 13 | Jev and LLMs on labeled decision tasks | Planned | Planned companion study — no measurements |
| 14 | Packaging, accelerator preflight and memory containment | Planned | Planned — no measurements |
| 15 | Saturation, SLO and cost | Planned | Planned — no measurements |
| 16 | Release gates, recovery and capstone synthesis | Planned | Planned capstone synthesis — no measurements |
<!-- END EPISODE INDEX -->

The [three capstone projects](docs/capstone-projects.md) explain where these
experiments lead. The [canonical roadmap](docs/roadmap.md) owns the planned sequence. Future
topics are proposals until an episode publishes evidence; they are not results
or authorization to spend.

## Start here

The repository currently exists at
[`KVSDURGASURESH/token-by-token`](https://github.com/KVSDURGASURESH/token-by-token)
and remains private while the owner chooses code, data, and documentation
licenses. If you have access, clone it and run the zero-cost fixture checks:

```bash
git clone https://github.com/KVSDURGASURESH/token-by-token.git
cd token-by-token
python3 scripts/verify_bundle.py data/public
python3 scripts/rehearse_workflow.py --output /tmp/inference-lab-episode-0
python3 scripts/verify_bundle.py /tmp/inference-lab-episode-0
python3 -m pip install '.[test]'
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Requirements: Python 3.12; the test extra installs the pinned JSON Schema
validator. These commands do not use credentials or contact a provider. The rehearsal output must
be a new or empty directory. It is labeled `fixture_zero_cost`, records zero
provider attempts and resources, and compiles a deliberately nonapprovable
plan with zero cost.

Continue with [Episode 0](episodes/00-warm-up/README.md) to inspect the retained
study, start the [local dashboard](episodes/00-warm-up/README.md#explore-it-locally),
and understand the experiment's limits. Once the dashboard is running, its
[episode index](http://127.0.0.1:5173/#episodes) is the default home.

Episode 01 is the recorded H200 deployment comparison. Open
[`#episode-1`](http://127.0.0.1:5173/#episode-1) to explore the matched 12,
16, and 24-user evidence, or [`#methodology`](http://127.0.0.1:5173/#methodology)
to see how realistic multi-turn sessions, protocol gates, and aligned client,
engine, and GPU measurements become a public result. Both pages are static and
work in Light or Dark mode.

For a zero-GPU streamed request race, use the Episode 1
[Quick test](docs/episode-1-preparation/quick-test.md). Its browser and CLI use
the same versioned configuration and runner. Quick test results are interactive
diagnostics, not the ShareGPT/GSM8K benchmark evidence defined for Episode 1.
Run `scripts/quick-test demo` to bootstrap and launch the dashboard, then use
`scripts/quick-test request` or `scripts/quick-test compare` from another
terminal against the same loopback bridge.
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
`dashboard/src/data/episode-1-public.v1.json`. The raw metrics export, private
reports, receipts, containers, and dashboards are neither published nor needed
again unless the approved source evidence changes.

Rebuild and verify the committed public site with:

```bash
python3 -m unittest tests.test_static_evidence_pipeline tests.test_episode1_public_evidence tests.test_publication_privacy
python3 scripts/check_publication_privacy.py --root .
npm --prefix dashboard ci
npm --prefix dashboard run check
npm --prefix dashboard run build
python3 scripts/check_publication_privacy.py --root dashboard/dist --files-only
node tests/dashboard_offline_acceptance.cjs dashboard/dist
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
experiment. No `LICENSE` or data license is included yet, so external
contribution and public redistribution remain pending the owner's licensing
decision.

## Public site v2 (local preview)

The public dashboard at `dashboard/index.html` is implemented in React in
`dashboard/src/PublicSite.tsx` with styles in `dashboard/src/public-site.css`.
Its recorded values come from the allowlisted static JSON under
`dashboard/src/data/site-v2/`, projected from the existing public evidence
files. These projections intentionally omit serving profiles, launch settings,
private endpoints, and engine versions. Update the projections when the
source evidence changes; review the resulting browser bundle with the
publication privacy check before release.

The approved design handoff is preserved in
`design/reference/claude-site-v2/`. Read its README and open the `.dc.html`
there for the visual and behavior reference. `support.js` is present only to
run that prototype locally and is not imported into the dashboard build.
The earlier local operator UI remains available at `dashboard/legacy.html`
during development; it is not part of the production Vite build.

```sh
npm --prefix dashboard ci
npm --prefix dashboard run check
npm --prefix dashboard run build
python3 scripts/check_publication_privacy.py --root dashboard/dist --files-only
node tests/dashboard_offline_acceptance.cjs dashboard/dist
```

For browser checks, start `npm --prefix dashboard run dev -- --port 4173`, then
run `node tests/dashboard_site_v2_acceptance.cjs http://127.0.0.1:4173/`.
The public site shows a Live dashboard link only when
`VITE_PUBLIC_GRAFANA_ENABLED=true` is explicitly set at build time. That
link points to the public base URL `https://graph.endlesstokens.ai`; it does
not contain a dashboard UID, credentials, or query parameters. Leave it
disabled until the owner verifies public, read-only access.

This branch is a local UI preview. Hosted development, staging, and production
behavior have not been verified or published from this work.
