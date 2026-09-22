# Token by Token — Inference Lab — Episode 0 results

Qwen2.5-32B-Instruct BF16 on one H100 80GB HBM3 per run, comparing vLLM 0.29.0 with SGLang 0.5.20. Baseline and stress are separate runs; both runtimes used the same allocation within each run. The study completed **936 requests with zero recorded failures** across 12 runtime/workload cells.

The figures below are direct screenshots of the project's native dashboard, populated from the retained sanitized study evidence. They are not screenshots of a currently running GPU or provider console. The source records, exact metric definitions and limitations remain in the [technical report](../data/public/report.md) and [reproduction contract](../data/public/reproduction.md).

## Delivered output rate and first-token latency

![Native dashboard output-throughput bars and logarithmic TTFT p50 plot, with baseline and stress workloads identified.](dashboard-captures/01-performance-720.png)

Each workload is an input-length/concurrency pair. Input length and concurrency change together, so the six cells are not a controlled scaling sweep. Baseline uses an output cap of 64 and three repetitions per cell; stress uses a cap of 128 and two repetitions. The plotted TTFT p50 values are descriptive percentiles, not uncertainty estimates.

At 128 input tokens and concurrency 16, observed output rate was 527.3 tok/s for vLLM and 483.6 for SGLang; TTFT p50 was 108 ms and 137 ms. At 8,192 input tokens and concurrency 32, rates were 57.5 and 43.7 tok/s; TTFT p50 was 47.9 s and 88.3 s.

## Delivered work must accompany throughput

![Native dashboard compares mean output length with the configured cap for both long-context workload pairs.](dashboard-captures/02-delivered-work-720.png)

At 8,192 input tokens/concurrency 8, vLLM averaged 47.8 output tokens and SGLang 64, under a cap of 64. At concurrency 32, vLLM averaged 99.89 and SGLang 128, under a cap of 128. The rates describe the runs' delivered output; they do not establish equal-output-work runtime superiority. The retained aggregates lack stop reasons and output-length distributions.

## Runtime phases, cache and queues

![Native runtime dashboard shows observed prefill/decode means, KV usage and waiting-request peaks; missing SGLang phase durations stay unavailable.](dashboard-captures/03-native-telemetry-720.png)

Phase durations are **medians of repetition-level histogram means**, calculated within each repetition as the change in a duration histogram's sum divided by the change in its count. They are not per-request p50 or p95. At the longest stress cell, vLLM's retained prefill/decode summaries were 0.963 s and 4.128 s. The SGLang scrape retained no corresponding duration samples.

KV and waiting-request values summarize per-repetition peaks. At the longest stress cell, native KV-usage peaks summarized to 96.5% for vLLM and 99% for SGLang, while waiting-request peaks summarized to 29 and 30. The peaks need not coincide. The engines' cache metric denominators have not been established as equivalent. These signals motivate controlled cache/queue experiments; they do not isolate a cause of the TTFT difference.

## GPU observations

![Native dashboard reports GPU utilization, framebuffer memory and power peaks by runtime and run from the one-second sampler.](dashboard-captures/04-gpu-peaks-720.png)

Every runtime/run arm recorded a 100% GPU-utilization peak. Observed peak memory was 74,139 MiB for vLLM in both runs, 70,632 MiB for baseline SGLang and 71,178 MiB for stress SGLang. Peak power ranged from 696.46 W to 706.04 W. These are sampled maxima, not sustained averages. Public aggregate evidence cannot reconstruct a GPU timeline or measure SM occupancy.

## Cost and provenance

The retained study records approximately **$2.19 combined conservative CLI debit**. It is not an invoice, an allocation of cost by runtime, or a cost-per-million-token result. Historical resource deletion was verified after each run. The local fixture dry run costs **$0 in provider charges**. A separate earlier RTX PRO 6000 trial cost **$4.1280**, including setup and troubleshooting; it is not part of the H100 experiment total. The [cost evidence ledger](cost-evidence.md) distinguishes observed debits, estimates and unavailable per-retry allocations. This editorial revision created no paid resources.

The exact historical container image digests and harness commit are not retained. An exact environment replay cannot be claimed. The companion project's recommended launch recipe is a new configuration that must be pinned and checked before a fresh paid run.

Sources: [benchmark summary](../data/public/benchmark-summary.csv), [runtime telemetry](../data/public/telemetry-summary.csv), [GPU summaries](../data/public/gpu-summary.json), [dashboard screenshot metadata](dashboard-captures/README.md).
