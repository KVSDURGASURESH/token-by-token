# Accessibility text for social images

## TTFT p50 / p95 / p99

Horizontal bar chart of time to first token percentiles for SGLang, vLLM across
6 highest-concurrency runtime/profile cells on NVIDIA H100 80GB HBM3.
Lower values are better; bar lengths use a disclosed logarithmic scale. Every
available row is labelled with exact p50, p95, and p99 milliseconds and its
metric-specific sample count. Cells contain
64-128 attempted requests; unavailable metrics are labelled unavailable.

## Tail latency matrix

Table-style graphic listing p95 and p99 milliseconds for TTFT, TPOT, client
inter-chunk latency, and end-to-end latency for the same stress cells. It is
intended to show where tail behavior differs from median or throughput behavior.

## Output throughput

Horizontal bar chart of successful streamed output tokens per measured wall
second for the same 6 cells. Higher bars are better. Exact rates
and mean delivered output tokens per successful request are shown. Runtime
compatibility disclosures appear in the post and report and are required when
interpreting the chart.
