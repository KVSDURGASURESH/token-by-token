"""Reject storage the pod-only local guard cannot manage independently."""

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("guard_boundary_compiler", ROOT / "scripts/compile_plan.py")
compiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compiler)


def execution_inputs(*, local_guard):
    manifest = json.loads((ROOT / "examples/execution-manifest.template.json").read_text())
    live = json.loads((ROOT / "examples/execution-live-inputs.template.json").read_text())
    execution = manifest["execution"]
    execution["resource"]["container"]["image_digest"] = "sha256:" + "1" * 64
    execution["model"]["chat_template"]["sha256"] = "2" * 64
    execution["workload"]["dataset"].update(revision="3" * 40, sha256="4" * 64)
    for cell in execution["workload"]["prompt_cells"]:
        cell["prompt_sha256"] = "5" * 64
    now = datetime.now(timezone.utc)
    window = {
        "observed_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
    }
    live["gpu"].update(hourly_usd="1.00", **window)
    live["account"]["balance_usd"] = "13.00"
    live["ancillary_costs"].update(window)
    for component in live["ancillary_costs"]["components"].values():
        component.update(status="included", amount_usd="0.00")
    if local_guard:
        execution["guard_policy"] = {
            "mode": "local_only_acknowledged", "watchdogs": ["primary", "secondary"],
            "launcher": "caffeinate", "clock": "monotonic", "poll_interval_seconds": 1,
            "cli_timeout_seconds": 1, "arming_timeout_seconds": 1,
            "heartbeat_stale_after_seconds": 3, "delete_retry_delays_seconds": [0, 1],
            "start_no_new_arms_at_fraction": "0.75", "teardown_at_fraction": "0.85",
            "arm_order": ["vllm"], "watchdog_script_sha256": "6" * 64,
            "launcher_script_sha256": "7" * 64,
        }
        live["guard_acknowledgment"] = {
            "response": "ACCEPT LOCAL-WATCHDOG RISK", "source": "user",
            "observed_at": window["observed_at"],
        }
    return manifest, live


def test_local_only_guard_rejects_network_storage_even_with_pod_only_teardown():
    manifest, live = execution_inputs(local_guard=True)
    manifest["execution"]["resource"]["storage"]["network_volume_gb"] = 10
    with pytest.raises(ValueError, match="guard_policy.*storage"):
        compiler.compile_plan(manifest, live)


def test_local_only_guard_allows_container_disk_without_volume_attachments():
    manifest, live = execution_inputs(local_guard=True)
    plan = compiler.compile_plan(manifest, live)
    assert plan["execution_ready"] is True
    assert plan["guards"]["mode"] == "local_only_acknowledged"
    assert plan["manifest"]["execution"]["resource"]["storage"]["container_disk_gb"] == 100


def test_local_only_guard_preserves_costed_persistent_storage_deleted_with_pod():
    manifest, live = execution_inputs(local_guard=True)
    manifest["execution"]["resource"]["storage"]["volume_gb"] = 10
    live["ancillary_costs"]["components"]["storage"] = {"status": "billed", "hourly_usd": "0.10"}
    plan = compiler.compile_plan(manifest, live)
    assert plan["execution_ready"] is True
    assert plan["manifest"]["execution"]["teardown"]["resources"] == ["pod"]
    assert plan["cost"]["maximum_usd"] == "2.20"


@pytest.mark.parametrize("field,resource", [("volume_gb", "volume"), ("network_volume_gb", "network_volume")])
def test_provider_deadline_contract_preserves_explicitly_modeled_volume_teardown(field, resource):
    manifest, live = execution_inputs(local_guard=False)
    manifest["execution"]["resource"]["storage"][field] = 10
    manifest["execution"]["teardown"]["resources"].append(resource)
    live["ancillary_costs"]["components"]["network_volume" if resource == "network_volume" else "storage"] = {
        "status": "billed", "hourly_usd": "0.10",
    }
    plan = compiler.compile_plan(manifest, live)
    assert plan["execution_ready"] is True
    assert plan["manifest"]["execution"]["teardown"]["resources"] == ["pod", resource]
    assert plan["cost"]["maximum_usd"] == "2.20"
