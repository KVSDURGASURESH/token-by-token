#!/usr/bin/env python3
"""Reconcile Episode 06's published aggregates and recorded chart samples offline."""

from collections import Counter, defaultdict
import json
from math import isclose
from pathlib import Path
from statistics import mean

DATA = Path(__file__).resolve().parents[2] / "public-data" / "site-v2"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def same(observed, expected, label):
    require(isclose(observed, expected, abs_tol=1e-8), label)


def main():
    result = json.loads((DATA / "episode-6.json").read_text())
    grafana = json.loads((DATA / "episode-6-grafana.json").read_text())
    cells = grafana["cells"]
    require(grafana["evidence"] == "recorded", "Chart data must be recorded")
    require([row["cell"] for row in cells] == list(range(1, 33)), "Expected 32 ordered cells")
    groups = defaultdict(list)
    arrivals = Counter()
    for row in cells:
        groups[row["chunk"], row["condition"]].append(row["pause_ms"])
        require(row["foreground_completed"] == 8, "Eight valid foreground streams per cell")
        require(("first_content_ms" in row) == (row["condition"] == "burst"), "First content applies to burst only")
        if "first_content_ms" in row:
            require(row["first_content_ms"] > 0, "Invalid first-content latency")
            arrivals[row["chunk"]] += 4

    scheduling = result["scheduling"]
    require(len(groups) == 4 and all(len(rows) == 8 for rows in groups.values()), "Eight cells per condition")
    require(arrivals == {512: 32, 4096: 32}, "32 arrivals per setting")
    require(len(scheduling["blocks"]) == 8, "Eight matched blocks")
    for setting in scheduling["settings"]:
        chunk = setting["chunk"]
        burst = mean(groups[chunk, "burst"])
        sham = mean(groups[chunk, "no-burst"])
        same(burst, setting["burst"], "Burst cell mean")
        same(sham, setting["sham"], "No-burst cell mean")
        same(burst - sham, setting["addedPause"], "Burst penalty")
    reduction = mean(row["large"] - row["small"] for row in scheduling["blocks"])
    same(reduction, scheduling["reduction"], "Paired reduction")
    require(scheduling["streamValid"] == sum(row["foreground_completed"] for row in cells) + sum(arrivals.values()), "320 valid primary streams")

    decode = result["decode"]
    require(len(decode["spans"]) == 10 and decode["tokensPerArm"] == 154, "Matched trace population")
    for arm in ("off", "on"):
        same(mean(step[arm] for step in decode["spans"]), decode["mean"][arm], "Matched decode mean")
    print(json.dumps({"status": "passed", "recorded_cells": 32, "first_content_cells": 16,
                      "paired_pause_reduction_ms": round(reduction, 2),
                      "matched_steps": len(decode["spans"])}, indent=2))


if __name__ == "__main__":
    main()
