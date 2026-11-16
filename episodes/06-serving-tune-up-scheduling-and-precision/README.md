# Episode 06 — Prefill interference and batch invariance

What happens when four long prompts arrive while eight replies are already streaming? On one H200, SGLang 0.5.21 and Qwen3-30B-A3B in BF16, a burst added **12.8 ms** to the longest visible pause at a 512-token prefill chunk budget, and **70.4 ms** at 4,096 tokens. Across eight matched blocks, the smaller setting cut the burst penalty by **57.6 ms** (95% paired-block bootstrap interval 54.9–60.1 ms). The arriving prompts reached their first visible text in a median **629 vs. 353 ms**, respectively, over 32 arrivals per setting.

## How it was measured

Prefill processes incoming prompt tokens. Decode extends active replies by generating output tokens. SGLang's mixed scheduling lets these two kinds of work share scheduling iterations. The main study compared two chunk budgets, each with and without a four-prompt burst. Each block included all four conditions. Each cell processed eight active streams with 1,024 input and 1,024 output tokens. An incoming prompt contained 6,144 input tokens and generated 32. TP1, FlashAttention 3, an 8,192-token context limit, a 32-running-request limit and the cache-disabled policy were fixed. All 320 primary requests had valid terminal streams.

For each existing reply, take its longest gap between adjacent visible content events intersecting the two-second observation window. Average the eight reply gaps for a cell. Subtract the no-burst cell mean from the burst cell mean within each chunk setting and block. Compare the two differences and resample complete blocks for the uncertainty interval. The arrival first-content comparison uses individual requests and is descriptive.

## What the trace adds

A separate one-GPU SGLang OFF/ON capture matched ten decode steps with 154 decoded tokens per arm. Mean annotated span was **6.91 ms OFF** and **11.11 ms ON**. Copies, normalization and elementwise operations accounted for the largest named increase, about **1.83 ms per step**. Unrecorded activity has unknown cause. Attribution covers the matched decode phase. In separate profiler-off controls, each arm delivered 31,939 valid tokens over 96 exact-valid tasks, at about 1,706 tok/s OFF and 1,090 tok/s ON.

## Reproduce the published arithmetic offline

From the repository root, with Python 3.12 or later:

```sh
python3 episodes/06-serving-tune-up-scheduling-and-precision/verify.py
```

The verifier uses the [reviewed aggregate](../../public-data/site-v2/episode-6.json) and [recorded Grafana cell data](../../public-data/site-v2/episode-6-grafana.json). The latter retains the order of cell completion and the observed values. In a burst cell the first-content point is the median of four arrivals. The aggregate headline uses the median of 32 individual arrivals per setting. The offline verifier reconciles the headline effect, cell populations and trace means. It reads local files and uses the Python standard library.

AgentBench by MiraStack Labs produced the retained experiment evidence. The public replay operates on reviewed aggregates. A fresh live GPU execution requires the original private execution harness and a separate provider allocation.

Both pods were permanently deleted. Total modeled cost through cleanup was **$6.64**. Provider billing remained unsettled. The next controlled study measures sustained traffic under latency and output targets.

[Watch the episode and explore the dashboard](https://tokenbytoken.org/episodes/06-serving-tune-up-scheduling-and-precision/)
