# Reproduction contract

## Recorded configuration

Use Qwen/Qwen2.5-32B-Instruct revision `5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd` on one NVIDIA H100 80GB HBM3 with bfloat16 weights and a 16,384-token context. Pin vLLM 0.29.0 and SGLang 0.5.20. Both arms used prefix caching and chunked prefill. Use temperature 0, top-p 1, top-k 0, seed 20260920, exact-token deterministic prompts, and streamed OpenAI-compatible chat completions.

Baseline profiles used input/concurrency pairs 128/1, 2048/4, and 8192/8, a maximum of 64 output tokens, 20 requests, and three repetitions. Stress profiles used 128/16 with 32 requests, 2048/24 with 48 requests, and 8192/32 with 64 requests, a maximum of 128 output tokens, and two repetitions. The load model was closed-loop. The run used warmup and validation gates and collected one-second GPU and runtime-native telemetry.

The retained client metrics are TTFT, TPOT, client inter-chunk latency, E2E latency, aggregate delivered output-token rate, request counts, delivered output-token totals, and errors. The percentile method and contributing sample count are recorded in `live-study.json` and `benchmark-summary.csv`. Aggregate output rate is delivered output tokens divided by wall-clock time; it is not the median of repetition-level throughput values.

## Publicly unrecoverable provenance

The sanitized public bundle does not retain immutable runtime image digests, the exact harness commit used during execution, the full prompt payload or chat template, measured-arm order, per-repetition raw samples, stop reasons, or output-length distributions. A decision-grade reproduction must record those fields during execution. They must not be inferred from later repository state.

## Requirements for the next controlled study

Record immutable image digests, the harness commit and prompt/template hashes, and randomized or counterbalanced arm order. Apply an identical prompt and output contract to every paired arm, make warmup and cache-reset policy explicit, retain raw repetition samples and stop reasons, and predeclare aggregation rules plus latency and goodput SLOs. Keep measured facts, derived conclusions, and proposed experiments separate in every public artifact.
