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
<!-- END EPISODE INDEX -->

The [three capstone projects](docs/capstone-projects.md) explain where these
experiments lead. The [canonical roadmap](docs/roadmap.md) owns the planned sequence. Future
topics are proposals until an episode publishes evidence; they are not results
or authorization to spend.

## Start here

The repository currently exists at
[`KVSDURGASURESH/token-by-token`](https://github.com/KVSDURGASURESH/token-by-token)
and remains private while the owner chooses code, data, and documentation
licenses. If you have access, the commands below take you from a fresh clone to
the checked-in results, a repeatable zero-cost rehearsal, and the local
dashboard. Run them in a POSIX shell on macOS, Linux, or WSL.

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

Continue with [Episode 0](episodes/00-warm-up/README.md) to inspect the retained
study and understand the experiment's limits. The Episode 0
[local-exploration notes](episodes/00-warm-up/README.md#explore-it-locally)
explain what the fixture and recorded evidence can establish. Once the
dashboard is running, its [episode index](http://127.0.0.1:5173/#episodes) is
the default home.

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

## Contributors

Built with AI assistance from:

- **Claude** (Anthropic)
- **Codex** (OpenAI)

## Contributing and licensing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing an episode or
experiment. No `LICENSE` or data license is included yet, so external
contribution and public redistribution remain pending the owner's licensing
decision.
