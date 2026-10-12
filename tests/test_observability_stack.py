from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "deploy/grafana/dashboards/inference-lab-execution.json"


def _expressions(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        if isinstance(value.get("expr"), str):
            found.append(value["expr"])
        for child in value.values():
            found.extend(_expressions(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_expressions(child))
    return found


def test_dashboard_is_provisionable_and_uses_stable_identity() -> None:
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    assert dashboard["uid"] == "inference-lab-execution"
    assert dashboard["title"] == "Inference Lab · Execution telemetry"
    assert dashboard["editable"] is False
    assert dashboard["time"]["from"] == "now-1h"
    variables = {item["name"] for item in dashboard["templating"]["list"]}
    assert {"catalog_version", "episode", "run_id", "config_digest", "repeat", "engine", "gpu"} <= variables


def test_queries_do_not_treat_snapshot_gauges_as_counters_or_histograms() -> None:
    expressions = _expressions(json.loads(DASHBOARD.read_text(encoding="utf-8")))
    joined = "\n".join(expressions)
    assert "rate(inference_lab_requests_total" not in joined
    assert "histogram_quantile" in joined
    for metric in ("inference_lab_ttft_ms", "inference_lab_tpot_ms", "inference_lab_e2e_ms", "inference_lab_client_inter_chunk_ms"):
        assert f"histogram_quantile" + "(" not in "\n".join(expr for expr in expressions if metric in expr)


def test_dashboard_targets_required_metric_families() -> None:
    expressions = _expressions(json.loads(DASHBOARD.read_text(encoding="utf-8")))
    joined = "\n".join(expressions)
    for metric in (
        "inference_lab_request_attempts_total", "inference_lab_output_tokens_total",
        "inference_lab_ttft_seconds_bucket", "inference_lab_tpot_seconds_bucket",
        "inference_lab_client_inter_chunk_seconds_bucket", "inference_lab_e2e_seconds_bucket",
        "inference_lab_runtime_queue_depth", "inference_lab_kv_cache_occupancy_ratio",
        "inference_lab_gpu_utilization_percent", "inference_lab_gpu_memory_used_mib",
        "DCGM_FI_DEV_GPU_UTIL", "DCGM_FI_DEV_FB_USED", "DCGM_FI_DEV_POWER_USAGE",
        "inference_lab_parallelism_info", "inference_lab_run_cost_usd",
    ):
        assert metric in joined


def test_tail_contract_has_p95_and_p99_for_each_latency_family() -> None:
    expressions = _expressions(json.loads(DASHBOARD.read_text(encoding="utf-8")))
    for metric in ("ttft", "tpot", "e2e", "client_inter_chunk"):
        matching = "\n".join(expr for expr in expressions if f"inference_lab_{metric}_seconds_bucket" in expr)
        assert "histogram_quantile(0.95" in matching
        assert "histogram_quantile(0.99" in matching


def test_future_aggregations_preserve_run_provenance_and_mib_units() -> None:
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    expressions = _expressions(dashboard)
    provenance = "catalog_version, episode, run_id, config_digest, repeat, engine, gpu"
    for expression in expressions:
        if "histogram_quantile" in expression:
            assert f"sum by (le, {provenance})" in expression
        if "rate(inference_lab_request_attempts_total" in expression:
            assert f"sum by ({provenance})" in expression
        if "rate(inference_lab_output_tokens_total" in expression:
            assert f"sum by ({provenance})" in expression
        if "rate(inference_lab_prefix_cache_" in expression:
            assert expression.count(f"sum by ({provenance})") == 3

    memory_panel = next(panel for panel in dashboard["panels"] if panel["id"] == 19)
    assert memory_panel["fieldConfig"]["defaults"]["unit"] == "mbytes"
