# Episode 1 — Measure What Matters

> **Planning package only.** The checked-in dashboard data is a local synthetic
> contract fixture, not a provider measurement. No GPU was used, no provider
> charge was incurred, and nothing here authorizes a paid run.

Episode 1 turns the first two stages of the [Inference Lab
roadmap](../../docs/roadmap.md) into a concrete protocol: define the work and
quality contract, then compare equal work across vLLM 0.29.0 and SGLang 0.5.20.
The candidate is Qwen2.5-32B-Instruct at BF16 on one H100 80GB, but hardware,
images, launch compatibility, availability, pricing and deletion safeguards
remain unverified provider inputs.

## What is fixed

- Three counterbalanced runtime pairs, each arm using a fresh runtime process.
- Fixed-output cells at 512 input tokens / 128 output tokens / concurrency 1
  and 2,048 / 128 / concurrency 4.
- A 24-task natural-stop quality cell, with schema validity and semantic
  correctness reported separately.
- 528 measured requests plus 72 declared warmups, deterministic seed
  `20260923`, prefix reuse disabled, BF16 weights and KV cache, and no
  quantization, speculation, adapters or constrained decoding.
- Raw monotonic stream timestamps, explicit failure denominators, request and
  token goodput, and per-block primary summaries. p99 is not a headline metric.

The machine-readable contract is
[`fixtures/episode1/episode1-planning.json`](../../fixtures/episode1/episode1-planning.json).
Its `execution_ready` field is `false` and its approval phrase is `null`.

## Inspect without a GPU

From `dashboard/`, run `npm ci` and `npm run dev`, then open
`http://127.0.0.1:5173/#episode-1`. The large warning and every chart identify
the data as a local fixture. The fixture deliberately retains one unsent request
per cell and a semantic failure so the UI and exporter cannot hide denominator
failures.

The provider-free checks are:

```bash
python3 -m pip install '.[test]'
PYTHONPATH=src python3 -m unittest \
  tests.test_episode1_contract \
  tests.test_episode1_schema_conformance \
  tests.test_episode1_sse_loopback \
  tests.test_episode1_runner_loopback

python3 scripts/prepare_episode1_fixture.py \
  --output fixtures/episode1 \
  --raw-directory /tmp/episode1-private-evidence
```

With the pinned public tokenizer assets prepared as described in the
[tokenizer preflight](../../docs/episode-1-preparation/tokenizer-preflight.md),
the complete 72-warmup/528-measured schedule can be rehearsed through real
loopback HTTP/SSE transport and six fresh local server processes:

```bash
python3 scripts/run_episode1_loopback_rehearsal.py \
  --plan fixtures/episode1/episode1-planning.json \
  --prompt-evidence /tmp/episode1-prompt-evidence.json \
  --material-manifest fixtures/episode1/material-manifest.fixture.json \
  --tokenizer-directory /tmp/episode1-tokenizer-assets \
  --raw-directory /tmp/episode1-loopback-UNIQUE \
  --public-output /tmp/episode1-loopback-public.json
```

The raw directory must be new or empty; the rehearsal refuses to overwrite
prior evidence. It verifies the prompt/template/tokenizer and sorted material
hash bindings before traffic, warms all three shapes before measuring a block,
and retains a hash-chained process/boundary record. This proves the local
transport/parser/scheduler path only. It does not launch vLLM or SGLang or
verify GPU flags. The dedicated compiler, provider adapter, fresh-process
supervisor and execution entry point are implemented, but they correctly
refuse execution without the private build attestation, provider observations,
authorization receipt and bound approvals.

The raw synthetic request records are intentionally written outside the
repository. Each private request is validated against the closed observation
contract before persistence; the public plan, phase-ledger envelope and
aggregate have versioned schemas under [`schemas/`](../../schemas/). Public
fixtures contain only deterministic, sanitized aggregates.

`PACKAGE-MANIFEST.sha256` remains the retained Episode 0 package inventory; it
is intentionally not reused as the Episode 1 material inventory.
Episode 1 material bindings live in
[`material-manifest.fixture.json`](../../fixtures/episode1/material-manifest.fixture.json).

## Tomorrow's run gates

A paid run is blocked until all of the following are resolved and bound into a
new private execution plan:

1. derived `linux/amd64` image digests for both runtimes and verified H100
   driver/CUDA compatibility, especially the SGLang 0.5.20 lane;
2. source-verified effective launch flags, loopback streaming smoke checks,
   tokenizer/template proof and fresh-process orchestration;
3. a current exact H100 offer, location, stock, price, complete maximum charge
   and minimum final balance;
4. a supported provider-enforced permanent-deletion deadline that can be read
   back, or a separately accepted and validated local-watchdog degraded mode;
5. the owner's exact digest-bound spending approval for that current plan.

Read the active manifest and compiled plan in full before any experiment. The
[operator preflight](../../docs/episode-1-preparation/operator-preflight.md),
[runtime preflight](../../docs/episode-1-preparation/runtime-preflight.md), and
[remote handoff](../../docs/episode-1-preparation/remote-handoff.md) are the
handoff. Do not create a Pod, endpoint, volume or other paid resource from this
guide.
