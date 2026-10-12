# Episode 1 evidence capture contract

Status: planned capture, not measured results. Use with the [implementation brief](implementation-brief.md). Fixtures must carry `local_fixture` in every exported dataset and a persistent visible label in the dashboard. A screenshot of a fixture is a local rehearsal screenshot.

## Keys and clocks

Use opaque experiment, runtime, pair, block, cell, request and attempt keys. An attempt is never silently replaced. The private mapping contains provider IDs, endpoints and process identifiers; the public exporter admits only the declared opaque keys. Bind code, protocol, corpus, tokenizer/chat-template, image and schedule hashes. Record source schema and collector version.

Client latency uses one monotonic clock. Every collector records its clock domain, sample sequence, UTC timestamp and paired monotonic anchor. Capture anchors at start/end and after detected clock steps. Record time synchronization status and offset uncertainty for cross-host telemetry. Join samples by declared cell/block windows, with an uncertainty band if needed; never subtract client and server monotonic timestamps. A UTC axis aligns observations approximately and does not establish causation.

## Capture matrix

All raw artifacts stay in an ignored private directory with restricted permissions. The paths below are artifact roles, not permission to publish the contents.

| Signal | Source, units and cadence | Private evidence | Public view and unavailable behavior |
|---|---|---|---|
| Request timeline | Client transport; monotonic ns for a/b/s/f/l/d; every attempt | Request JSONL, dispatch/cancellation record, bounded response text and content-event timing | TTFT/E2E/send-lag/terminal-overhead points in ms per block; failed/censored counts retained. Missing terminal evidence is unavailable, never a completed latency. |
| Output work | Streamed final usage, stop reason, full-output pinned-tokenizer reconciliation; every request | Usage object, response/token IDs where available, tokenizer/template hashes, finish reason | Output-token distribution, stop-reason counts, fixed-length failures and reconciliation status. Content-event count is not token count. Unexplained disagreement blocks equal-work claims. |
| Quality | Strict parser and frozen semantic evaluator; every natural task | Gold labels, output, parser result, exact field comparison and evaluator hash | Schema-valid, correct, nontruncated and SLO-qualified counts with denominators; no response excerpts in automatic exports. Unknown quality yields unavailable goodput. |
| Cold/warm lifecycle | Launcher and readiness probe; event boundaries | Process creation/exit, effective startup configuration, model load, ready and first-valid request, warmup outcomes | Allocation/download/load/warmup/measured/drain phases separate; startup ms per fresh block. Labels alone cannot certify restarts. |
| Runtime queue/activity | Native Prometheus gauges; target 1 s, before/after each cell | Entire scrape privately, including labels, status, duration and dropped-sample count | Runtime-specific queued/running requests over elapsed seconds. Gauge samples cannot recover unseen spikes or per-request queue latency. Missing native fields remain gaps. |
| KV/cache | Native documented utilization/capacity and prefix-cache counters; target 1 s plus boundary snapshots | Versioned metric name, HELP/TYPE/unit, allocator capacity and effective cache-disable setting | KV occupancy fraction and cache-hit counters only with stated semantics. Prefix off is verified configuration, not inferred from GPU memory. GPU-used memory is not KV occupancy. |
| Prefill/decode/request service | Native cumulative counters/histograms; target 1 s plus boundaries | Raw bucket/count/sum, labels, scrape times, restart/reset markers | Within-block differences only; reset/invalid intervals excluded with reasons. Keep native names and definitions. Never label all runtime request-duration series as the same prefill/decode metric. |
| GPU | `nvidia-smi` or NVML; target 1 s | Utilization %, used/total MiB, power W, temperature C, supported clocks MHz, throttling reason codes, samples/gaps | Aligned utilization, memory, power and temperature charts, with units and valid-sample counts. Unsupported clocks/throttling are unavailable. Sampled utilization is not SM occupancy. |
| Host/client | Process/host collectors; target 1 s | CPU utilization with normalization, RSS bytes, disk/network byte counters, event-loop/dispatch lag, connection pool limits | Normalized CPU %, memory MiB and delta rates with scope. Omit hostnames, addresses, paths and process command lines. Resource saturation or high send lag qualifies server conclusions. |
| Cost/lifecycle | Provider quote, balances, transaction export, lifecycle reads; event boundaries and settlement | Fresh offer/config, pre/post balance, itemized bill, all owned-resource create/delete/status responses | Provider-reported total, balance-derived change, modelled phase estimates and unattributed residual in distinct columns. No mock ledger becomes a charge. |

Capture telemetry before startup and continue through the last request drain. Export sample coverage by expected and observed counts, maximum gap and scrape failures. Do not forward-fill gaps across restarts or different blocks. Counter deltas require the same process identity and a nondecreasing counter. Telemetry overhead remains part of the declared experiment environment; keep collectors and cadence equal across arms.

Runtime-native prefill/decode data is supplemental. The comparable latency source is the declared client trace. Native histogram buckets generally do not yield exact percentiles and can mix unrelated traffic; restrict to the single isolated server and bounded window, and disclose that boundary-scrape timing still introduces uncertainty.

## Figures and genuine screenshot shot list

Prepare these figures before live collection, using unmistakably labeled fixtures:

1. A request timeline explaining arrival, actual send, first/last content and terminal usage; show the TPOT/chunk limitation.
2. Per-block TTFT and E2E p50/p95 points: x = runtime/block, y = ms; show n and failures. Keep small-sample p99 out of headlines.
3. Throughput and goodput: separate req/s and output-token/s panels, common wall denominator, fixed and natural cells separated.
4. Output length/stop-reason and quality outcome counts, with all attempted requests accounted for.
5. Time-aligned GPU/queue/KV panels: x = elapsed seconds; phase bands, explicit gaps and source names.
6. Cost waterfall: provider total beside estimated exclusive phases and reconciliation residual; estimates visibly labeled.

For the future live run, retain authentic screenshots at: pre-create quote/configuration; initial billing balance; runtime version/effective configuration; hardware query; completed dashboard filters and charts; provider deletion confirmation plus subsequent empty owned-resource inventory; final settled billing. A cropped console screenshot is supporting evidence, not a substitute for machine-readable lifecycle verification. Preserve date range, units and amounts while redacting identity, keys, resource IDs, SSH/proxy URLs, payment details and unrelated resources. Never publish raw terminal output or reconstruct a missing console screenshot.

The hardware screenshot is NVIDIA telemetry, not a NVIDIA NIM dashboard. No NIM experiment is in this protocol. Paged attention and radix-prefix diagrams, if needed for later writing, should be small explanatory diagrams tied to verified concepts; this pilot does not measure either mechanism in isolation.

## Export gate

The exporter must construct a closed public object, not remove a few forbidden keys from arbitrary raw data. Reject unknown keys, nonfinite numbers, invalid units, inconsistent counts and fixture/live provenance mismatches. Include no raw text, arbitrary error messages, labels, URLs, absolute paths or provider/account identifiers. Use fixed reason enums and null plus a reason for unavailable metrics. Validate the resulting artifact, scan it for prohibited material and write a checksum inventory. Hashes establish file integrity, not the truth of measurements.
