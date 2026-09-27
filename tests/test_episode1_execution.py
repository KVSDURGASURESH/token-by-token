from __future__ import annotations

import copy
import json
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from runpod_benchmark.episode1 import canonical_json
from runpod_benchmark.episode1_execution import (
    Episode1ExecutionError,
    compile_execution_candidate,
    spend_approval_phrase,
    validate_execution_approvals,
    verify_execution_candidate,
    verify_fresh_for_create,
    watchdog_risk_phrase,
)
from runpod_benchmark.episode1_remote import SshConfig, SshRemoteExecutor, quote_remote_argv
from runpod_benchmark.pod_supervisor import PodProcessSupervisor, SupervisorError


ROOT = Path(__file__).resolve().parents[1]


def protocol() -> dict:
    return json.loads((ROOT / "fixtures/episode1/episode1-planning.json").read_text())


def inputs(*, ready: bool = True) -> dict:
    digest = "a" * 64
    image = f"sha256:{'b' * 64}" if ready else None
    return {
        "schema_version": "episode1.execution-input.v1",
        "candidate_id": "candidate-1",
        "protocol_sha256": protocol()["protocol_sha256"],
        "material_sha256": digest,
        "source_commit": "c" * 40,
        "provider": {
            "api_contract_sha256": digest if ready else None,
            "observed_at": "2026-09-22T12:00:00Z" if ready else None,
            "expires_at": "2026-09-22T12:15:00Z" if ready else None,
            "offer_reference_hash": digest if ready else None,
            "stock_verified": ready,
            "permanent_delete_supported": True,
            "delete_deadline_readback_supported": False,
            "inventory_read_supported": True,
            "direct_lookup_supported": True,
            "ambiguous_create_retry_forbidden": True,
            "recover_by_exact_name_supported": True,
            "account_balance_usd": "100.00" if ready else None,
            "account_evidence_sha256": digest if ready else None,
            "auto_pay_disabled": ready,
            "auto_pay_evidence_sha256": digest if ready else None,
            "unrelated_resources_evidence_sha256": digest if ready else None,
        },
        "allocation": {
            "gpu": "NVIDIA H100 80GB HBM3", "gpu_count": 1,
            "data_center_id": "US-TEST-1", "cloud_type": "SECURE",
            "container_disk_gb": 120, "volume_gb": 0, "volume_mount_path": "",
            "single_allocation": True, "isolation_mode": "host-env-sequential",
            "isolation_verified": True,
        },
        "access": {
            "mode": "full_ssh_public_ip", "public_ip_supported": True, "ssh_port": 22,
            "public_inference_ports": [], "image_starts_sshd": True,
            "strict_host_key_checking": True, "post_create_host_key_verification_required": True,
        },
        "runtime_builds": [{
            "runtime": runtime, "build_spec_sha256": digest,
            "dependency_lock_sha256": digest, "launcher_sha256": digest,
            "build_attestation_sha256": digest,
            "derived_image_digest": image, "post_create_gpu_check_required": True,
            "post_create_effective_flags_check_required": True,
        } for runtime in ("vllm-0.29.0", "sglang-0.5.20")],
        "capture": {
            "collector_sha256": digest, "private_schema_sha256": digest,
            "telemetry_cadence_seconds": 1,
        },
        "benchmark_standard": {
            "serving": {
                "harness": "sglang.bench_serving", "harness_version": "0.5.20",
                "harness_source_commit": "1" * 40, "adapter_sha256": digest,
                "dataset": "ShareGPT_V3_unfiltered_cleaned_split.json",
                "dataset_revision": "2" * 40, "dataset_sha256": digest,
                "selection_manifest_sha256": digest, "seed": 20260923,
                "request_count": 128, "output_tokens": 128, "arrival_policy": "infinite",
            },
            "quality": {
                "harness": "lm-evaluation-harness", "harness_source_commit": "3" * 40,
                "adapter_sha256": digest, "task": "gsm8k", "task_version": "3.0",
                "dataset_revision": "4" * 40, "dataset_sha256": digest,
                "task_config_sha256": digest, "num_fewshot": 5,
                "filter": "strict-match", "sample_count": 1319,
                "do_sample": False, "temperature": 0,
            },
            "application_gate": {
                "name": "episode1-json-extraction-24", "corpus_sha256": digest,
                "evaluator_sha256": digest, "standard_benchmark": False,
            },
        },
        "phase_budgets": {
            "provision_and_staging": 1200,
            "six_runtime_startups": 1440,
            "six_warmup_sets": 1080,
            "six_measured_blocks": 2520,
            "export_and_verified_deletion": 480,
            "one_startup_retry_contingency": 480,
        },
        "cost_components": [
            {
                "category": category,
                "status": (
                    "priced" if ready and category == "gpu"
                    else "verified_not_applicable" if ready else "unknown"
                ),
                "amount_usd": (
                    "4.000000" if ready and category == "gpu"
                    else "0.000000" if ready else None
                ),
                "billing_unit": (
                    "per_hour" if ready and category == "gpu"
                    else "not_applicable" if ready else "unknown"
                ),
                "rounding_seconds": 60,
                "included_in": None,
                "source_sha256": digest if ready else None,
                "observed_at": "2026-09-22T12:00:00Z" if ready else None,
                "expires_at": "2026-09-22T12:15:00Z" if ready else None,
            }
            for category in (
                "gpu", "container_storage", "volume_storage", "network_volume",
                "public_ip", "startup", "egress", "tax", "other",
            )
        ],
        "budget": {
            "maximum_spend_usd": "15.00", "minimum_final_balance_usd": "10.00",
            "maximum_lifetime_seconds": 7200, "startup_retry_limit": 1,
            "soft_stop_fraction": "0.75", "teardown_fraction": "0.85",
            "delete_verification_seconds": 120, "create_recovery_seconds": 60,
            "export_seconds": 60,
        },
        "guard": {
            "mode": "local_watchdog_fallback", "provider_deadline_seconds": None,
            "local_watchdog_plan_sha256": digest,
        },
    }


def _case_blocked_candidate_cannot_self_authorize() -> None:
    plan = compile_execution_candidate(protocol(), inputs(ready=False))
    assert plan["execution_ready"] is False
    with unittest.TestCase().assertRaises(Episode1ExecutionError):
        spend_approval_phrase(plan)


def _case_ready_plan_has_literal_separate_risk_acceptance() -> None:
    plan = compile_execution_candidate(protocol(), inputs())
    spend = spend_approval_phrase(plan)
    assert watchdog_risk_phrase(plan) == "ACCEPT LOCAL-WATCHDOG RISK"
    validate_execution_approvals(
        plan, spend_approval=spend, watchdog_risk_approval="ACCEPT LOCAL-WATCHDOG RISK"
    )


def _case_rehashed_semantic_tampering_is_rejected() -> None:
    plan = compile_execution_candidate(protocol(), inputs())
    plan["unresolved_blockers"] = ["invented"]
    plan["execution_ready"] = False
    body = dict(plan)
    body.pop("plan_sha256")
    import hashlib
    plan["plan_sha256"] = hashlib.sha256(canonical_json(body).encode()).hexdigest()
    with unittest.TestCase().assertRaisesRegex(Episode1ExecutionError, "blockers"):
        verify_execution_candidate(plan)


def _case_quote_freshness_is_a_separate_create_gate() -> None:
    plan = compile_execution_candidate(protocol(), inputs())
    verify_execution_candidate(plan)
    verify_fresh_for_create(plan, now=datetime(2026, 9, 22, 12, 10, tzinfo=timezone.utc))
    with unittest.TestCase().assertRaisesRegex(Episode1ExecutionError, "not fresh"):
        verify_fresh_for_create(plan, now=datetime(2026, 9, 22, 12, 15, tzinfo=timezone.utc))


def _case_one_image_architecture_is_enforced() -> None:
    value = inputs()
    value["runtime_builds"][1]["derived_image_digest"] = f"sha256:{'d' * 64}"
    with unittest.TestCase().assertRaisesRegex(Episode1ExecutionError, "same one-image"):
        compile_execution_candidate(protocol(), value)


def _case_cleanup_and_recovery_subbudgets_must_fit_frozen_phases() -> None:
    value = inputs()
    value["budget"]["create_recovery_seconds"] = 1201
    with unittest.TestCase().assertRaisesRegex(Episode1ExecutionError, "create recovery"):
        compile_execution_candidate(protocol(), value)
    value = inputs()
    value["budget"]["delete_verification_seconds"] = 421
    value["budget"]["export_seconds"] = 60
    with unittest.TestCase().assertRaisesRegex(Episode1ExecutionError, "sub-budgets"):
        compile_execution_candidate(protocol(), value)


def _case_provider_guard_still_requires_independent_local_watchdog() -> None:
    value = inputs()
    value["guard"] = {
        "mode": "provider_enforced", "provider_deadline_seconds": 7200,
        "local_watchdog_plan_sha256": None,
    }
    value["provider"]["delete_deadline_readback_supported"] = True
    plan = compile_execution_candidate(protocol(), value)
    assert "independent_local_watchdog_plan_unbound" in plan["unresolved_blockers"]
    value["guard"]["local_watchdog_plan_sha256"] = "a" * 64
    plan = compile_execution_candidate(protocol(), value)
    assert plan["execution_ready"] is True
    assert watchdog_risk_phrase(plan) is None


def _case_ssh_argv_uses_strict_host_key_and_quotes_remote_args(tmp_path: Path) -> None:
    key, known = tmp_path / "key", tmp_path / "known"
    key.write_text("fixture")
    known.write_text("fixture")
    key.chmod(stat.S_IRUSR | stat.S_IWUSR)
    known.chmod(stat.S_IRUSR | stat.S_IWUSR)
    seen: list[list[str]] = []

    def fake(argv, **_kwargs):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, b'{"ok":true}', b"")

    remote = SshRemoteExecutor(SshConfig("example.invalid", 31022, "root", key, known), runner=fake)
    assert remote.run_json(["printf", "%s", "a b;$(bad)"]) == {"ok": True}
    assert "StrictHostKeyChecking=yes" in seen[0]
    assert seen[0][-2] == "root@example.invalid"
    assert seen[0][-1] == "printf %s 'a b;$(bad)'"
    assert quote_remote_argv(["x", "a b"]) == "x 'a b'"


def _case_supervisor_terminates_and_reaps_process_group(tmp_path: Path) -> None:
    supervisor = PodProcessSupervisor(tmp_path / "state")
    supervisor.start(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        runtime="fixture", block_id="block-01", specification_sha256="a" * 64,
        deadline_monotonic=time.monotonic() + 5,
    )
    stopped = supervisor.stop(term_seconds=1, kill_seconds=1)
    assert stopped["reaped"] is True
    assert supervisor.descendants_absent() is True
    assert (tmp_path / "state" / "runtime.json").stat().st_mode & 0o077 == 0


def _case_supervisor_stops_group_after_leader_exits(tmp_path: Path) -> None:
    supervisor = PodProcessSupervisor(tmp_path / "state")
    supervisor.start(
        [
            sys.executable,
            "-c",
            "import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])",
        ],
        runtime="fixture", block_id="block-01", specification_sha256="a" * 64,
        deadline_monotonic=time.monotonic() + 5,
    )
    assert supervisor.process is not None
    supervisor.process.wait(timeout=2)
    stopped = supervisor.stop(term_seconds=1, kill_seconds=1)
    assert stopped["reaped"] is True
    assert supervisor.descendants_absent() is True


def _case_supervisor_output_flood_cannot_deadlock(tmp_path: Path) -> None:
    supervisor = PodProcessSupervisor(tmp_path / "state")
    supervisor.start(
        [sys.executable, "-c", "import sys,time;sys.stdout.write('x'*2000000);time.sleep(60)"],
        runtime="fixture", block_id="block-01", specification_sha256="a" * 64,
        deadline_monotonic=time.monotonic() + 5,
    )
    stopped = supervisor.stop(term_seconds=1, kill_seconds=1)
    assert stopped["reaped"] is True


def _case_supervisor_reserves_for_sigkill_with_short_deadline(tmp_path: Path) -> None:
    supervisor = PodProcessSupervisor(tmp_path / "state")
    supervisor.start(
        [
            sys.executable, "-c",
            "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)",
        ],
        runtime="fixture", block_id="block-01", specification_sha256="a" * 64,
        deadline_monotonic=time.monotonic() + 5,
    )
    time.sleep(.05)
    started = time.monotonic()
    stopped = supervisor.stop(deadline_monotonic=started + .3)
    elapsed = time.monotonic() - started
    assert stopped["sigkill_used"] is True
    assert stopped["reaped"] is True
    assert elapsed < .27, elapsed


def _case_supervisor_state_failure_kills_spawned_group(tmp_path: Path) -> None:
    supervisor = PodProcessSupervisor(tmp_path / "state")

    def fail_state(_value):
        raise OSError("fixture persistence failure")

    supervisor._write_state = fail_state  # type: ignore[method-assign]
    with unittest.TestCase().assertRaisesRegex(OSError, "persistence failure"):
        supervisor.start(
            [sys.executable, "-c", "import time;time.sleep(60)"],
            runtime="fixture", block_id="block-01", specification_sha256="a" * 64,
            deadline_monotonic=time.monotonic() + 5,
        )
    assert supervisor.process is None
    assert supervisor.identity is None


def _case_supervisor_identity_failure_kills_spawned_group(tmp_path: Path) -> None:
    supervisor = PodProcessSupervisor(tmp_path / "state")

    def fail_identity(_pid):
        raise SupervisorError("fixture identity failure")

    supervisor._process_start_ticks = fail_identity  # type: ignore[method-assign]
    with unittest.TestCase().assertRaisesRegex(SupervisorError, "identity failure"):
        supervisor.start(
            [sys.executable, "-c", "import time;time.sleep(60)"],
            runtime="fixture", block_id="block-01", specification_sha256="a" * 64,
            deadline_monotonic=time.monotonic() + 5,
        )
    assert supervisor.process is None
    assert supervisor.identity is None
    assert supervisor.cleanup_required is False


@unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux procfs")
def _case_supervisor_reaps_descendant_that_escapes_process_group(tmp_path: Path) -> None:
    supervisor = PodProcessSupervisor(tmp_path / "state")
    supervisor.start(
        [
            sys.executable,
            "-c",
            "import subprocess,sys,time;"
            "subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
            "start_new_session=True);time.sleep(60)",
        ],
        runtime="fixture", block_id="block-01", specification_sha256="a" * 64,
        deadline_monotonic=time.monotonic() + 5,
    )
    time.sleep(.1)
    stopped = supervisor.stop(term_seconds=.5, kill_seconds=.5)
    assert stopped["reaped"] is True
    assert supervisor.descendants_absent() is True


@unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux procfs")
def _case_state_failure_reaps_escaped_descendant(tmp_path: Path) -> None:
    supervisor = PodProcessSupervisor(tmp_path / "state")

    def fail_after_descendant_started(_value):
        time.sleep(.1)
        raise OSError("fixture persistence failure")

    supervisor._write_state = fail_after_descendant_started  # type: ignore[method-assign]
    with unittest.TestCase().assertRaisesRegex(OSError, "persistence failure"):
        supervisor.start(
            [
                sys.executable,
                "-c",
                "import subprocess,sys,time;"
                "subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
                "start_new_session=True);time.sleep(60)",
            ],
            runtime="fixture", block_id="block-01", specification_sha256="a" * 64,
            deadline_monotonic=time.monotonic() + 5,
        )
    assert supervisor.process is None
    assert supervisor.identity is None
    assert supervisor.cleanup_required is False


def _case_integer_contract_rejects_bools_and_floats() -> None:
    mutations = (
        (("allocation", "gpu_count"), True),
        (("access", "ssh_port"), 22.0),
        (("phase_budgets", "six_measured_blocks"), 2520.0),
        (("budget", "startup_retry_limit"), True),
    )
    for path, replacement in mutations:
        candidate = inputs()
        candidate[path[0]][path[1]] = replacement
        with unittest.TestCase().assertRaises(Episode1ExecutionError):
            compile_execution_candidate(protocol(), candidate)


def _case_standard_benchmarks_are_closed_and_digest_bound() -> None:
    plan = compile_execution_candidate(protocol(), inputs())
    self_contained = plan["benchmark_standard"]
    assert self_contained["serving"]["dataset"] == "ShareGPT_V3_unfiltered_cleaned_split.json"
    assert self_contained["quality"]["task"] == "gsm8k"
    assert self_contained["quality"]["sample_count"] == 1319
    assert self_contained["application_gate"]["standard_benchmark"] is False

    missing = inputs()
    del missing["benchmark_standard"]
    with unittest.TestCase().assertRaisesRegex(Episode1ExecutionError, "benchmark_standard"):
        compile_execution_candidate(protocol(), missing)

    changed = inputs()
    changed["benchmark_standard"]["quality"]["sample_count"] = 24
    with unittest.TestCase().assertRaisesRegex(Episode1ExecutionError, "1319"):
        compile_execution_candidate(protocol(), changed)


class ExecutionUnittestBridge(unittest.TestCase):
    """Make the same cases visible to the repository's unittest CI runner."""

    def test_blocked(self):
        _case_blocked_candidate_cannot_self_authorize()

    def test_integer_contract(self):
        _case_integer_contract_rejects_bools_and_floats()

    def test_standard_benchmarks(self):
        _case_standard_benchmarks_are_closed_and_digest_bound()

    def test_approvals(self):
        _case_ready_plan_has_literal_separate_risk_acceptance()

    def test_tampering(self):
        _case_rehashed_semantic_tampering_is_rejected()

    def test_freshness(self):
        _case_quote_freshness_is_a_separate_create_gate()

    def test_one_image(self):
        _case_one_image_architecture_is_enforced()

    def test_phase_subbudgets(self):
        _case_cleanup_and_recovery_subbudgets_must_fit_frozen_phases()

    def test_provider_guard_requires_local_watchdog(self):
        _case_provider_guard_still_requires_independent_local_watchdog()

    def test_ssh(self):
        with tempfile.TemporaryDirectory() as directory:
            _case_ssh_argv_uses_strict_host_key_and_quotes_remote_args(Path(directory))

    def test_supervisor(self):
        with tempfile.TemporaryDirectory() as directory:
            _case_supervisor_terminates_and_reaps_process_group(Path(directory))

    def test_supervisor_leader_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            _case_supervisor_stops_group_after_leader_exits(Path(directory))

    def test_supervisor_output_flood(self):
        with tempfile.TemporaryDirectory() as directory:
            _case_supervisor_output_flood_cannot_deadlock(Path(directory))

    def test_supervisor_short_deadline_reserves_for_sigkill(self):
        with tempfile.TemporaryDirectory() as directory:
            _case_supervisor_reserves_for_sigkill_with_short_deadline(Path(directory))

    def test_supervisor_state_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            _case_supervisor_state_failure_kills_spawned_group(Path(directory))

    def test_supervisor_identity_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            _case_supervisor_identity_failure_kills_spawned_group(Path(directory))

    def test_supervisor_escaped_descendant(self):
        with tempfile.TemporaryDirectory() as directory:
            _case_supervisor_reaps_descendant_that_escapes_process_group(Path(directory))

    def test_supervisor_state_failure_escaped_descendant(self):
        with tempfile.TemporaryDirectory() as directory:
            _case_state_failure_reaps_escaped_descendant(Path(directory))
