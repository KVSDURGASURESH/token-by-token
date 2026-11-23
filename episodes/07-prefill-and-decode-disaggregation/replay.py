"""Recompute the published Episode 07 comparisons from the included aggregates."""

import json
from decimal import Decimal
from pathlib import Path
from statistics import mean


HEADLINE = "We Split Prefill and Decode. Why Did First Text Still Get Slower?"


def replay(data):
    if data.get("schema") != "token-by-token.episode07.1" or data.get("evidence") != "recorded NVLink":
        raise ValueError("expected the recorded Episode 07 NVLink aggregate")
    if data.get("headline") != HEADLINE:
        raise ValueError("unexpected Episode 07 headline")
    steady = data["steady"]["windows"]
    burst = data["burst"]["pairs"]
    sweep = data["sweep"]["windows"]
    if (len(steady), len(burst), len(sweep)) != (24, 4, 32):
        raise ValueError("incomplete cohort")
    result = {}
    for layout, setting in (("colocated", "CO4096"), ("split", "PD4096")):
        rows = [row for row in steady if row["setting"] == setting and row["load"] == "busy"]
        rates = {}
        for rate in (0.5, 1, 2, 4):
            paired = [row for row in sweep if row["layout"] == layout and row["rate_rps"] == rate]
            if {row["block"] for row in paired} != {1, 2, 3, 4} or len(paired) != 4:
                raise ValueError("expected every layout and rate to have four unique blocks")
            eligible = [row for row in paired if row["state"] in ("passes", "server_limit")]
            rates[str(rate)] = {
                "passing_windows": sum(row["state"] == "passes" for row in paired),
                "eligible_windows": len(eligible),
                "mean_window_p95_first_text_ms": mean(row["p95_first_text_ms"] for row in eligible)
                if len(eligible) == 4 else None,
                "offered_requests": sum(row["offers"] for row in paired),
                "requests_within_targets": sum(row["within_targets"] for row in paired),
            }
        result[layout] = {
            "steady_mean_window_p95_ms": mean(row["p95_first_text_ms"] for row in rows),
            "steady_valid_output_tokens_per_s": mean(row["valid_output_tokens_per_s"] for row in rows),
            "mean_added_foreground_pause_ms": mean(row[f"{layout}_added_pause_ms"] for row in burst),
            "mean_window_median_incoming_first_text_ms": mean(
                row[f"{layout}_incoming_first_text_ms"] for row in burst
            ),
            "sweep": rates,
        }
    for rate in result["colocated"]["sweep"]:
        co, pd = (result[layout]["sweep"][rate] for layout in ("colocated", "split"))
        if co["offered_requests"] != pd["offered_requests"]:
            raise ValueError("a matched rate has different offer counts")
    if any(result[layout]["sweep"]["2"]["passing_windows"] != 4 for layout in result):
        raise ValueError("expected all repeats to pass at 2 requests/sec")
    if any(result[layout]["sweep"]["4"]["eligible_windows"] != 0 for layout in result):
        raise ValueError("4 requests/sec must remain excluded as client-limited")

    pcie = data["pcie"]
    if (
        pcie.get("status") != "qualification_failed"
        or pcie.get("qualified_host") is not False
        or pcie.get("qualification_attempts") != 2
        or pcie.get("measured_burst_cells") != 0
    ):
        raise ValueError("unexpected PCIe qualification disposition")
    runpod_debits = Decimal(data["cost"]["observed_debits_usd"])
    if runpod_debits != sum((Decimal(item["usd"]) for item in data["cost"]["items"]), Decimal(0)):
        raise ValueError("Runpod debit total does not reconcile")
    result["cost_boundary"] = {
        "runpod_observed_debits_usd": str(runpod_debits),
        "hyperstack_qualification_spend_usd": pcie["qualification_spend_usd"],
        "combined_total_not_claimed": True,
    }
    result["pcie_boundary"] = {
        "status": pcie["status"],
        "qualification_attempts": pcie["qualification_attempts"],
        "measured_performance_cells": pcie["measured_burst_cells"],
    }
    return result


if __name__ == "__main__":
    source = Path(__file__).with_name("episode-07.json")
    print(json.dumps(replay(json.loads(source.read_text())), indent=2, allow_nan=False))
