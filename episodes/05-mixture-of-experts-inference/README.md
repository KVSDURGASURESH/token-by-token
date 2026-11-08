# Episode 05 — Mixture-of-experts inference

## What mixture of experts changes

A dense transformer sends every token through the same feed-forward weights. A mixture-of-experts layer adds a router: for each token, the router scores a bank of expert feed-forward networks, selects a small subset, and combines their outputs. The unselected experts remain inactive for that token.

The tested Qwen3-30B-A3B checkpoint was configured with 128 routed experts and eight selected per token. Sparse activation changes the per-token compute path; it does not make the remaining model weights disappear from GPU memory. This architecture explains the question, not the measured result: the dense-versus-MoE numbers below compare two specific checkpoints under one fixed serving and workload contract and do not establish a universal architecture multiplier.

Leg 1 asks what enabling batch invariance changes when the checkpoint and requests are held fixed. Qwen3-30B-A3B ran in BF16 on one H200 with tensor parallelism 1 and 16 concurrent requests. The workloads were short structured responses, long prefill and output-heavy structured responses. Timing uses eight paired blocks per engine and excludes warmup, cache priming and route diagnostics.

| Engine | Valid primary tasks | Exact output pairs | Mean valid output tokens/s, OFF → ON |
| --- | ---: | ---: | ---: |
| SGLang 0.5.21 | 1,536 / 1,536 | 768 / 768 | 1,709.69 → 1,090.69 |
| vLLM 0.32.0 | 1,524 / 1,536 | 764 / 768 | 1,636.27 → 1,025.93 |

SGLang passed the task-validity and output agreement gates. Its paired difference was −619.00 valid output tokens/s, with a 95% paired block bootstrap interval of [−624.22, −614.00]. The vLLM comparison is descriptive because 12 output-heavy primary responses failed the task validator. Engine order was sequential, so the results support within-engine comparisons.

## Leg 2 — Dense vs. MoE under constrained JSON

The R5 comparison ran Qwen3-32B dense and Qwen3-30B-A3B MoE sequentially on one H200 with SGLang 0.5.21, BF16, tensor parallelism 1 and 16 concurrent requests. Both arms used identical per-workload JSON schemas and exact answer checks. Both passed all 60 smoke and pilot requests. All 1,536 primary tasks passed across eight paired blocks.

| Metric | Dense | MoE |
| --- | ---: | ---: |
| Mean block valid requests/s | 1.65 | 5.07 |
| Mean block valid output tokens/s | 548.35 | 1,683.34 |
| Valid primary tasks | 768 / 768 | 768 / 768 |

MoE delivered 3.07× the valid requests per second. The paired mean difference was 3.4218 valid requests/s, with a paired 95% bootstrap interval of [3.4101, 3.4342]. This result applies to the two checkpoints under the measured load and JSON constraints.

| Workload | Dense p95 TTFT ms | MoE p95 TTFT ms | Dense p95 end-to-end ms | MoE p95 end-to-end ms |
| --- | ---: | ---: | ---: | ---: |
| Short structured | 1,043.94 | 210.05 | 1,384.45 | 307.37 |
| Long prefill | 1,043.95 | 210.53 | 3,191.93 | 660.41 |
| Output heavy | 1,040.61 | 209.40 | 26,964.38 | 8,966.41 |

Each latency cell has 256 primary requests. Two earlier attempts stopped before primary traffic because responses violated the exact JSON contract. The first stopped at dense smoke with 4/6 valid. R4 clarified long prefill and stopped at dense pilot with 22/24 valid. R5 completed export and permanent pod deletion. R5 cost $4.61 modeled, and the full Episode 05 campaign cost $19.47 modeled through cleanup. Provider billing is unsettled.

## Rehearse the public client

From a checkout with Python 3.12–3.14, install the public client and run its local fixture.

```sh
python -m pip install ./client
token-by-token episode 5 selftest --offline --users 2 --seed 42 \
  --output ./episode-05-rehearsal.tbt.zip --format json
token-by-token evidence verify ./episode-05-rehearsal.tbt.zip --format json
```

The self-test generates synthetic evidence for the public client and bundle verifier. The measurements above were produced by the experiment's private execution harness.
