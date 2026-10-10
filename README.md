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

An [unreleased public-client candidate](client/README.md) now describes every
Episode 00–16 contract and runs a deterministic offline self-test that writes a
locally verifiable evidence bundle. It costs $0 and makes no provider call. The
self-test validates client plumbing only; it is not benchmark evidence, and
hosted submission remains unavailable.

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
The commands below take you from a fresh clone to the checked-in results, a
repeatable zero-cost rehearsal, and the local dashboard. Run them in a POSIX
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
comes with Node.js. CI tests Python 3.12 and Node 22.

### 2. Verify the recorded data and rehearse the workflow

```bash
python3 scripts/verify_bundle.py data/public
REHEARSAL_DIR="$(mktemp -d "${TMPDIR:-/tmp}/inference-lab-episode-0.XXXXXX")"
printf '%s\n' "$REHEARSAL_DIR"
python3 scripts/rehearse_workflow.py --output "$REHEARSAL_DIR"
python3 scripts/verify_bundle.py "$REHEARSAL_DIR"
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install '.[test]'
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The two verifier commands should report JSON containing `"ok":true`; the
rehearsal prints a one-line JSON result containing
`"classification":"fixture_zero_cost"`,
`"paid_resources_created":0`, and `"provider_attempts":0`. The tests should
finish with `OK`. The unique temporary directory makes the block safe to run
again in the same shell.

`data/public/` is the checksum-bound, sanitized snapshot of the recorded
historical measurement. `$REHEARSAL_DIR/` is newly generated fixture output: it
reuses sanitized aggregates to exercise the workflow, makes no provider call,
creates no paid resource, records no new measurement, and compiles a
deliberately nonapprovable zero-cost plan.

### 3. Check, build, and start the dashboard

```bash
npm --prefix dashboard ci
npm --prefix dashboard run check
npm --prefix dashboard run build
npm --prefix dashboard run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

The check command should exit with no TypeScript errors, the build should end
with a successful Vite build, and the final command should print a local URL. Open
[http://127.0.0.1:5173/](http://127.0.0.1:5173/) in the same machine or WSL
environment. The dashboard reads its bundled snapshot from
`dashboard/src/data/latest.json`; the production build is written to
`dashboard/dist/`. Press **Ctrl-C** in the terminal to stop the development
server.

If port 5173 is already occupied, choose another loopback port and open the
matching URL:

```bash
npm --prefix dashboard run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

Then open [http://127.0.0.1:5174/](http://127.0.0.1:5174/).

If `npm ci` reports a registry or network error, confirm registry reachability
with `npm ping`, then retry when your network, VPN, proxy, or firewall permits
access. Do not use `sudo`, disable TLS checks, or change global npm security
settings to work around a failed install.

To try the isolated client instead, follow its
[source quick start](client/README.md#quick-start-from-source). The client has
its own package boundary, tests, threat model, locked standalone build, and
release checklist. No binary or package-registry release has been published.

Continue with [Episode 0](episodes/00-warm-up/README.md) to inspect the retained
study and understand the experiment's limits. The Episode 0
[local-exploration notes](episodes/00-warm-up/README.md#explore-it-locally)
explain what the fixture and recorded evidence can establish. Once the
dashboard is running, its [episode index](http://127.0.0.1:5173/#episodes) is
the default home.

Episode 01 is the recorded H200 deployment comparison. Open
[`#episode-1`](http://127.0.0.1:5173/#episode-1) to explore the matched 12,
16, and 24-user evidence, or [`#methodology`](http://127.0.0.1:5173/#methodology)
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
experiment. Original repository materials are available under the
[MIT License](LICENSE); see [OWNERSHIP.md](OWNERSHIP.md) for its scope and the
third-party boundaries.

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

### Privacy-first reader analytics

Analytics is disabled by default. To enable the optional Umami integration,
copy `dashboard/analytics.env.example` to the deployment environment and set the
tracker URL, website ID and an explicit production-domain allowlist before
building. The public bundle records aggregate page/section views, fixed scroll
depths and named interface actions such as opening the evidence lab. It does
not assign a distinct user ID, record free-form input, capture exact pointer
coordinates, replay sessions or load an analytics script when the variables
are absent.

The integration asks Umami to respect the browser Do Not Track preference and
uses its cookie-free tracker. Hosting and configuration still need an owner
privacy review: select the intended data region, sign a DPA when applicable,
set retention and access controls, and update the public privacy notice before
production collection. See `docs/analytics.md` for the event contract and
deployment checklist.

This branch is a local UI preview. Hosted development, staging, and production
behavior have not been verified or published from this work.
