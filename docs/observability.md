# Local observability stack

The local stack provisions a read-only, dark Grafana dashboard at
`http://127.0.0.1:3000` and uses the existing VictoriaMetrics instance at
`http://127.0.0.1:8428` as its Prometheus-compatible data source. Both ports
are loopback-only. Grafana is anonymous-viewer only; it has no checked-in
password and cannot edit the provisioned dashboard.

Start or refresh only the observability services without rebuilding the
episode console:

```bash
docker compose up -d --no-build victoria-metrics grafana
docker compose ps
curl --fail http://127.0.0.1:3000/api/health
curl --fail http://127.0.0.1:8428/targets
```

Open **Inference Lab / Execution telemetry**. Select a time window that
contains the run, then select `catalog_version`, `episode`, `run_id`,
`config_digest`, `repeat`, `engine`, and `gpu` where those labels exist.
Canonical Episode IDs use `episode-catalog.v2`: old Episodes 8–14 are new
3–9, old 15 is new 10, and old 3–7 are new 11–15. Immutable historical and
synthetic packs retain their original ID plus their catalog version; never
merge across catalog versions.

## Metric contract

Every execution series must carry the bounded identifiers that apply:
`catalog_version`, `episode`, `run_id`, `config_digest`, `repeat`, `engine`,
and `gpu`. `profile` and `cell` may be added. `run_id` is an opaque bounded
identifier. `config_digest` is the configuration SHA-256, not the configuration
itself. Never use prompt text, output text, user labels, endpoint URLs, request
IDs, or credentials as metric labels.

| Metric | Type | Meaning |
|---|---|---|
| `inference_lab_request_attempts_total` | counter | Requests admitted to a measured run. Use `rate()` for request rate. |
| `inference_lab_request_successes_total` / `inference_lab_request_failures_total` | counter | Terminal valid streams / all other attempts. |
| `inference_lab_output_tokens_total` | counter | Exact completion tokens from successful terminal streams. Use `rate()` for output throughput. |
| `inference_lab_ttft_seconds` | histogram | Send to first non-empty streamed content delta. |
| `inference_lab_tpot_seconds` | histogram | Per-request first-to-last content span divided by exact output tokens minus one. |
| `inference_lab_client_inter_chunk_seconds` | histogram | Gaps between non-empty SSE content events. Chunks are **not tokens**. |
| `inference_lab_e2e_seconds` | histogram | Send through validated terminal `[DONE]` and exact usage. |
| `inference_lab_runtime_queue_depth` | gauge | Runtime-native queue depth, only when a versioned collector documents it. |
| `inference_lab_kv_cache_occupancy_ratio` | gauge | Runtime-native used/capacity ratio, not a client inference. |
| `inference_lab_prefix_cache_hits_total` / `...misses_total` | counter | Runtime-native cache decisions. |
| `inference_lab_parallelism_info` | gauge fixed at 1 | Declared effective topology in bounded `dp`, `tp`, `pp`, `ep`, and `nodes` labels. |
| `inference_lab_run_cost_usd` | gauge | Settled or explicitly provisional run cost; `cost_status` is required. Never substitute zero for unknown. |
| `inference_lab_run_info` | gauge fixed at 1 | Provenance and availability anchor, with the bounded labels above and image digest/model revision where available. |

The existing local rehearsal bridge exposes `inference_lab_requests_total` and
`inference_lab_<summary>` as **latest-completed-run gauges**. They remain useful
for the “Local rehearsal snapshot” panels. They are not counters or histogram
buckets: do not apply `rate()` or `histogram_quantile()` to them. The dashboard
keeps missing contract metrics visibly empty rather than manufacturing values.
Synthetic mock validation uses the separate `inference_lab_mock_*` namespace
and `validation_source="synthetic-mock"`; it must not be presented as measured
engine telemetry.

TTFT, TPOT, E2E, and client inter-chunk definitions follow
[`metric-definitions.md`](metric-definitions.md). Percentiles over the histogram
contract use `histogram_quantile`; current rehearsal p95/p99 values are already
computed summary gauges and are queried directly.

## Optional remote GPU telemetry

NVIDIA DCGM Exporter is not started by this Compose project because it must run
on the actual GPU host with a compatible driver, DCGM, and container runtime.
Copy `deploy/victoria-metrics/dcgm-targets.example.yml` to a private file,
replace the placeholders with the reachable exporter `host:9400` and the
current bounded run provenance, and start the stack with
`DCGM_TARGETS_FILE=/absolute/private/path.yml`. Update the private target file
for each run so DCGM samples are never silently attributed to another run.
Verify the effective runtime output at the exporter's `/metrics`; selecting a
DCGM field does not guarantee that a GPU emits it. The dashboard targets the
official utilization, frame-buffer memory, and board-power metric names and
shows no data when absent. Local bridge GPU utilization and used-memory panels
use host-wide `nvidia-smi` summary gauges when those samples exist; they are not
lane-attributable, and local board power is not currently exported by this
bridge.

Configuration follows the official
[Grafana file provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/),
[VictoriaMetrics Grafana integration](https://docs.victoriametrics.com/victoriametrics/integrations/grafana/),
[VictoriaMetrics file service discovery](https://docs.victoriametrics.com/victoriametrics/sd_configs/),
and [NVIDIA DCGM Exporter metric contract](https://docs.nvidia.com/datacenter/dcgm/latest/reference/dcgm-exporter-metrics.html).

## Stop and rollback

`docker compose stop grafana` removes Grafana from service without touching
VictoriaMetrics data. `docker compose down` stops the stack but preserves the
named metrics volume. Do not add `--volumes` unless retained local metrics are
intentionally being deleted.


## Episode 02 aligned evidence

`episode2_telemetry.align_signals` qualifies native/runtime, GPU, host and client signals by exact execution/engine/arm/cell/block identity, runtime version, normalized units, cadence, measured-window coverage, clock offsets and retained uncertainty. Source mappings must be independently proved for the pinned runtime; a normalized metric name does not establish availability. GPU samples require process attribution; counter resets and missing coverage remain explicit unavailable records. Converted timestamps are labeled client-monotonic while preserving their source domain. No guessed queue, cache, CPU or GPU values fill a missing signal.

`episode2_rca.evaluate_hypothesis` recomputes the disposition from predeclared signatures, recorded evidence lineage, required aligned signals, confounder controls and a recorded controlled equal-work intervention. A high correlation or missing instrumentation leaves causal disposition inconclusive. Diagnostic attempts stay outside baseline/treatment aggregates. All hypotheses retain limits; an unsupported mechanism supplies no optimization winner or paid-rerun authority.

Source schemas are `episode2-telemetry.schema.json` and `episode2-hypothesis.schema.json`. Offline checks: `PYTHONPATH=src:scripts .venv/bin/python -m pytest tests/test_episode2_telemetry.py tests/test_episode2_rca.py -q`. Runtime collection and provider readiness require separate measured evidence.

Episode 02 causal dispositions require typed predicates over qualified recorded signals in every measured block. Each predicate names a normalized signal, mean/minimum/maximum, comparison operator and finite threshold; every declared confounder has a sample predicate. The evaluator validates raw run observations and aligns signal coverage before computing predicates. Legacy prose, caller verdict booleans and opaque hashes produce an inconclusive proposal. Controlled tests bind distinct execution/evidence, equal delivered work and the actual before/after configuration hashes. Independent review must still establish source authority and scientific suitability of the predeclared test.
