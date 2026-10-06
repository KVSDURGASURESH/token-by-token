from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from experiment_plan import TEMPLATES, canonical_digest, validate_plan  # noqa: E402


def valid_plan():
    return json.loads((ROOT / "tests/fixtures/experiment-plan.valid.json").read_text())


def test_catalog_is_exact_canonical_zero_through_sixteen():
    catalog = json.loads((ROOT / "dashboard/src/data/episodes.json").read_text())
    assert [episode["number"] for episode in catalog["episodes"]] == list(range(17))
    assert catalog["episodeNumbering"]["version"] == "episode-catalog.v2"
    assert catalog["episodeNumbering"]["oldToCurrent"] == {
        str(old): new for old, new in enumerate((0, 1, 2, 11, 12, 13, 14, 15, 3, 4, 5, 6, 7, 8, 9, 10, 16))
    }
    assert [episode["previousNumber"] for episode in catalog["episodes"]] == [0, 1, 2, 8, 9, 10, 11, 12, 13, 14, 15, 3, 4, 5, 6, 7, 16]
    assert catalog["episodes"][0]["evidence"] == "Exploratory recorded study"
    assert catalog["episodes"][1]["evidence"] == "Recorded exploratory H200 runtime comparison — capacity not established"
    assert all(episode["evidence"].startswith("Planned") for episode in catalog["episodes"][2:])
    assert set(TEMPLATES) == {episode["templateId"] for episode in catalog["episodes"][1:]}
    assert {TEMPLATES[f"episode-{n}-" + {11:"model-internals",12:"lora-qlora",13:"jev-decisions"}[n]]["track"] for n in (11,12,13)} == {"model","training","decision"}
    assert all(template["version"] == 2 for template in TEMPLATES.values())


def test_valid_plan_and_deterministic_digest():
    plan = valid_plan()
    assert validate_plan(plan) == []
    assert canonical_digest(plan) == canonical_digest(copy.deepcopy(plan))
    changed = copy.deepcopy(plan); changed["workload"]["requests"] += 1
    assert canonical_digest(plan) != canonical_digest(changed)


def test_unknown_keys_and_tampered_safety_are_rejected():
    plan = valid_plan(); plan["endpoint_url"] = "anything"
    assert validate_plan(plan)
    plan = valid_plan(); plan["execution_authorized"] = True
    assert "Safety constants were changed." in validate_plan(plan)


def test_wrongly_typed_import_fields_are_rejected_without_crashing():
    plan = valid_plan(); plan["optimizations"]["draft_model_id"] = 7
    assert validate_plan(plan)
    plan = valid_plan(); plan["quality"]["require_schema_validity"] = "yes"
    assert validate_plan(plan)
    plan = valid_plan(); plan["model"]["template_id"] = ""
    assert validate_plan(plan)


def test_nonfinite_ranges_and_incompatible_combinations_are_rejected():
    plan = valid_plan(); plan["slos"]["ttft_ms"] = math.nan
    assert validate_plan(plan)
    plan = valid_plan(); plan["hardware"]["gpu_count"] = 0
    assert validate_plan(plan)
    plan = valid_plan(); plan["optimizations"]["speculative_method"] = "draft_model"
    assert validate_plan(plan)
    plan = valid_plan(); plan["workload"]["arrival_rate_rps"] = 1
    assert validate_plan(plan)
    plan = valid_plan(); plan["optimizations"]["attention_backend"] = "magic"
    assert validate_plan(plan)


def test_money_is_decimal_string_and_unknown_compatibility_stays_unverified():
    plan = valid_plan(); plan["cost"]["desired_budget_usd"] = 5.0
    assert validate_plan(plan)
    registry = json.loads((ROOT / "dashboard/src/data/capabilities.v1.json").read_text())
    assert all(item["verifiedOn"] is None for item in registry["capabilities"])
    assert any(item["state"] == "requires_preflight" for item in registry["capabilities"])


def test_schema_is_closed_and_declares_planning_constants():
    schema = json.loads((ROOT / "schemas/experiment-plan.schema.json").read_text())
    assert schema["additionalProperties"] is False
    assert schema["properties"]["planning_only"]["const"] is True
    assert schema["properties"]["execution_ready"]["const"] is False
    assert schema["properties"]["execution_authorized"]["const"] is False
