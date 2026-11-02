from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: str) -> dict[str, object]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_episode04_projection_matches_allowlisted_chart_rows() -> None:
    charts = read_json("episodes/04-speculative-decoding/charts.json")
    projection = read_json("public-data/site-v2/episode-4.json")
    chart_rows = charts["rows"]
    projection_rows = projection["chart_rows"]

    assert len(chart_rows) == len(projection_rows) == 12
    by_cell = {
        (row["runtime"], row["output_class"], row["policy"]): row
        for row in chart_rows
    }
    for row in projection_rows:
        source = by_cell[(row["runtime"], row["output_class"], row["policy"])]
        for metric in (
            "tpot_improvement_pct",
            "e2e_improvement_pct",
            "ttft_improvement_pct",
            "draft_miss_rate_p50",
            "exact_output_match_rate",
        ):
            assert row[metric] == source[metric]
        assert source["claim_status"] == "pending_output_adjudication"


def test_episode04_public_contract_is_recorded_but_real_execution_is_closed() -> None:
    public_catalog = read_json("public-data/contracts/episode-catalog.v2.json")
    site_catalog = read_json("public-data/site-v2/catalog.json")
    client_catalog = read_json("client/src/token_by_token_cli/resources/episodes/catalog.v1.json")
    rehearsal = read_json("examples/episode-04-offline-rehearsal.json")

    public = next(item for item in public_catalog["episodes"] if item["number"] == 4)
    site = next(item for item in site_catalog["episodes"] if item["number"] == 4)
    client = next(item for item in client_catalog["episodes"] if item["episode"] == 4)

    assert public["status"] == site["status"] == "available"
    assert client["status"] == "recorded"
    assert client["load_levels"] == [1]
    assert rehearsal["classification"] == "synthetic_mock"
    assert rehearsal["execution_boundary"] == {
        "network": "forbidden",
        "provider_submission": False,
        "gpu_execution": False,
        "inference_engine": False,
        "recorded_values_replayed": False,
        "performance_or_quality_claim": False,
    }


def test_episode04_invalid_sglang_store_is_excluded_and_output_gate_is_explicit() -> None:
    results = read_json("episodes/04-speculative-decoding/results.json")
    projection = read_json("public-data/site-v2/episode-4.json")

    assert results["claim_status"] == "pending_output_adjudication"
    assert results["output_hash_adjudication"]["task_oracle"] == "unavailable"
    assert "HTTP 400" in results["excluded_source"]["reason"]
    assert projection["evidence_boundary"]["correctness_or_losslessness_claim"] is False
    assert projection["evidence_boundary"]["excluded"] == "earlier main-store SGLang HTTP-400 observations"


def test_episode04_configuration_notation_and_miss_denominators_are_explicit() -> None:
    results = read_json("episodes/04-speculative-decoding/results.json")

    notation = results["configuration_notation"]
    assert notation["vllm"] == {
        "k1": {"num_speculative_tokens": 1},
        "k3": {"num_speculative_tokens": 3},
        "k5": {"num_speculative_tokens": 5},
    }
    assert notation["sglang"]["s3d4"] == {
        "speculative_num_steps": 3,
        "speculative_num_draft_tokens": 4,
        "speculative_eagle_topk": 1,
    }
    assert notation["observed_adjudication_balance_candidates"] == [
        "vllm-k3",
        "sglang-s3d4",
    ]

    telemetry = results["telemetry"]
    assert telemetry["highest_miss_settings"]["vllm-k5"] == {
        "primary_requests": 24,
        "rejected": 12549,
        "proposed": 16725,
        "ratio": 0.7503139013452915,
    }
    assert telemetry["highest_miss_settings"]["sglang-s5d6"] == {
        "primary_requests": 24,
        "rejected": 17809,
        "proposed": 21135,
        "ratio": 0.8426307073574639,
    }
    assert telemetry["applicable_primary_speculative_responses"] == 144
    assert telemetry["speculative_responses_missing_draft_telemetry"] == 0
