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
licenses. If you have access, clone it and run the zero-cost fixture checks:

```bash
git clone https://github.com/KVSDURGASURESH/token-by-token.git
cd token-by-token
python3 scripts/verify_bundle.py data/public
python3 scripts/rehearse_workflow.py --output /tmp/inference-lab-episode-0
python3 scripts/verify_bundle.py /tmp/inference-lab-episode-0
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Requirements: Python 3.12. These commands use only the standard library, do
not use credentials, and do not contact a provider. The rehearsal output must
be a new or empty directory. It is labeled `fixture_zero_cost`, records zero
provider attempts and resources, and compiles a deliberately nonapprovable
plan with zero cost.

Continue with [Episode 0](episodes/00-warm-up/README.md) to inspect the retained
study, start the [local dashboard](episodes/00-warm-up/README.md#explore-it-locally),
and understand the experiment's limits. Once the dashboard is running, its
[episode index](http://127.0.0.1:5173/#episodes) is the default home.

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

## Contributing and licensing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing an episode or
experiment. No `LICENSE` or data license is included yet, so external
contribution and public redistribution remain pending the owner's licensing
decision.
