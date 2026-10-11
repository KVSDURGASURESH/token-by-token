# Qwen2.5-32B serving benchmark: vLLM versus SGLang

Classification: exploratory_noncanonical

successful requests: 936

failed requests: 0

Two single-H100 runs compared vLLM 0.29.0 and SGLang 0.5.20 with the same pinned Qwen2.5-32B-Instruct revision, bfloat16 weights, deterministic exact-token prompts, temperature 0, and client-side streaming instrumentation.

## Measured stress results

The rate column is aggregate delivered output tokens divided by measured wall time. It is not a median. The stress setting allowed a maximum of 128 output tokens per request.

| Profile | vLLM aggregate output tok/s | SGLang aggregate output tok/s | vLLM TTFT p50 | SGLang TTFT p50 |
|---|---:|---:|---:|---:|
| 128 tokens, concurrency 16 | 527.3 | 483.6 | 107.7 ms | 136.9 ms |
| 2,048 tokens, concurrency 24 | 263.0 | 176.7 | 6,404.8 ms | 10,688.2 ms |
| 8,192 tokens, concurrency 32 | 57.5 | 43.7 | 47,936.1 ms | 88,319.8 ms |

vLLM delivered approximately 9%, 49%, and 32% more aggregate output rate in these three stress cells. At 8,192 tokens and concurrency 32, median TTFT was approximately 48 seconds for vLLM and 88 seconds for SGLang.

The long-context arms did not deliver equal output work. At 8,192 tokens and concurrency 8, vLLM averaged 47.80 delivered output tokens per successful request while SGLang averaged 64.00, against a 64-token maximum. At 8,192 tokens and concurrency 32, vLLM averaged 99.89 while SGLang averaged 128.00, against a 128-token maximum. Stop reasons and output-length distributions are not available in the public evidence, so no EOS, truncation, or quality explanation is claimed. The observed rates remain valid delivered-throughput measurements, but those two pairs are not equal-output-work comparisons.

## Runtime-native telemetry

At concurrency 32, median peak KV-cache usage was 96.5% for vLLM and 99% for SGLang. Median peak waiting requests were 29 and 30 respectively. High native KV occupancy and waiting-request peaks accompanied long TTFT in the long-context cells. This is consistent with memory and queue pressure, but the experiment does not isolate their causal contributions.

vLLM exposed request prefill/decode histograms; SGLang exposed KV usage, queue depth, token rates, and prefix-cache-hit metrics but not separate request prefill/decode durations. Client ITL is inter-chunk latency from streamed client events, not server-side inter-token latency.

The eBPF capability probe was retained as unavailable: the container had kernel BTF but lacked BPF capabilities, tracefs, bpftrace, and bpftool. No tracing was attached, and this did not block native telemetry.

## Interpretation limits

This is exploratory closed-loop evidence, not a universal runtime ranking. Prefix caching and chunked prefill were enabled. The baseline and stress workloads used different maximum output-token settings. Every p99 is descriptive because the study has limited independent repetitions and no run-level uncertainty estimate; no fixed request-count threshold establishes p99 precision. Goodput is unavailable because no latency SLO was predeclared.

Observed conservative CLI debit across both runs was approximately $2.19. Both pods were permanently deleted; fresh provider inventory was empty after each run. The final provider account balance was checked privately and is not part of the public bundle.
