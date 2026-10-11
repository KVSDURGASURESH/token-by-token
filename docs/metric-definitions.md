# Benchmark metric definitions

These definitions are the client contract for every runtime. Use monotonic time
for durations. Preserve raw per-request observations privately; publish only
sanitized aggregates with metric-specific counts, source, percentile method,
warnings, and availability reason.

## Client latency

- **TTFT (`ttft_ms`)**: elapsed milliseconds from the benchmark transport's
  actual request-send timestamp to receipt of the first non-empty streamed
  content delta. Connection setup before the actual send is excluded. A stream
  with no content has no TTFT and is a failed request.
- **E2E (`e2e_ms`)**: elapsed milliseconds from actual request send through
  successful receipt and validation of the terminal `[DONE]` event and exact
  streamed completion-token usage.
- **Client ITL (`client_inter_chunk_ms`)**: each monotonic gap between consecutive
  non-empty streamed content deltas. Its observation count is content gaps, not
  requests or tokens. It is not server token latency and must not be renamed as
  such.
- **TPOT (`tpot_ms`)**: for a successful request with at least two exact output
  tokens, `(last non-empty content event - first non-empty content event) /
  (output_tokens - 1)`. Terminal `[DONE]` and usage-envelope overhead is excluded.
  With fewer than two exact output tokens, TPOT is unavailable because no
  post-first-token interval exists. TPOT is a client-derived average decode span
  per output token for one request, not the ITL distribution.
- **Send lag (`send_lag_ms`)**: actual send time minus scheduled send time for an
  open-loop request. Report it separately so an overloaded client cannot be
  mistaken for server queueing.

For each distribution, sort applicable finite nonnegative observations and use
linear interpolation at rank `(n - 1) * q` for p50, p95, and p99. Never average
precomputed percentiles across repetitions. Pool compatible raw observations or
report repetitions separately. A p99 with fewer than 1,000 applicable
observations is `descriptive p99`; always show its `n`.

## Rates, failures, and quality

- **Attempted requests**: every scheduled request entering a measured cell.
- **Successful requests**: attempted requests with a valid terminal stream,
  non-empty content, TTFT, and exact nonnegative completion-token count.
- **Failed requests**: attempted minus successful. Publish the count, error rate,
  and sanitized failure classes; never silently discard retries or timeouts.
- **Output throughput**: exact output tokens from successful requests divided by
  measured cell wall seconds. It is aggregate token rate, not the inverse of
  TPOT.
- **Goodput**: output tokens from successful requests that satisfy every declared
  applicable latency SLO, divided by the same measured wall seconds. Publish the
  complete SLO contract, qualifying request count, and qualifying token count.
  Without a nonempty SLO contract or exact tokens, goodput is unavailable.
- **Quality gate**: a predeclared test appropriate to the workload, plus
  output-length and stop-reason distributions and success/error thresholds.
  Output-changing optimizations require this evidence. Speculative decoding also
  reports accepted draft tokens divided by proposed draft tokens and accepted
  tokens per draft step.

Closed-loop concurrency measures work admitted as earlier requests complete.
Open-loop capacity uses a declared arrival process and rate independent of
completion. For open loop, report target and achieved arrival rate, send lag,
queue behavior, errors, latency/goodput SLOs, and the highest sustainable rate;
do not call a closed-loop concurrency sweep a capacity curve.

## Runtime-native telemetry

When available, collect runtime-native queue wait, prefill duration, decode
duration, KV-cache occupancy/capacity, prefix-cache hits and misses, scheduler
batch/admission state, and preemption count. Retain the runtime metric name,
version, unit, sampling or counter interval, and aggregation. Missing native
metrics are explicitly unavailable; they never erase the client metrics above.

GPU utilization, memory, power, and process samples are supporting telemetry.
They do not substitute for runtime queue/prefill/decode evidence and must be
aligned to the exact measured window.

## Common E2E decomposition

Use this conceptual decomposition only when each component has compatible clock
and boundary definitions:

```text
client E2E
  = transport/request overhead
  + runtime queue wait
  + prefill
  + first-token scheduling/serialization
  + decode and inter-token delivery
  + terminal-stream/usage completion
```

Client TTFT approximately spans transport, queue, prefill, and first-token
delivery. The first-to-last content span covers observable decode/delivery;
`E2E - last content time` retains terminal stream and usage completion overhead.
Do not subtract runtime-native durations from client E2E as if the remainder were
precise unless clocks, windows, and units are demonstrated to align. Prefix-cache
hits change prefill work; chunked prefill can change queue/preemption behavior;
speculation changes decode work; quantization can change both performance and
quality. Those are hypotheses to measure, not labels from which to infer cause.

## Comparison rules

For causal optimization claims, pair baseline and treatment on the same physical
GPU with identical pinned image except for the one declared changed variable,
or explain why an image change is inseparable from the treatment. Keep model and
tokenizer revisions, prompts and hashes, requested output lengths, sampling,
load process, client/harness version, timeouts, warmups, cache state, and quality
gate fixed. Randomize repeated arm order and disclose drift.

Cross-GPU or historical comparisons may be descriptive context only. A same-GPU
paired arm is required to attribute a change to an optimization.
