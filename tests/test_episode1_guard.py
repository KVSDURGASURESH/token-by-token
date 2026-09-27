from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from runpod_benchmark.episode1 import canonical_json
from runpod_benchmark.episode1_execution import compile_execution_candidate
from runpod_benchmark.episode1_guard import (
    FileReceiptGuard,
    GuardError,
    make_guard_binding,
    restart_disposition,
)
from test_episode1_execution import inputs, protocol


def _binding(now=100.0):
    plan = compile_execution_candidate(protocol(), inputs())
    return make_guard_binding(
        plan=plan, unique_name="episode1-candidate-1-run", allocation_id="private",
        ownership_token="ownership", original_t0_monotonic=now,
        hard_deadline_monotonic=now + 7200, clock_domain="boot-1",
        primary_script_sha256="1" * 64, secondary_script_sha256="2" * 64,
        run_nonce="3" * 64,
    )


class GuardTests(unittest.TestCase):
    def test_binding_is_original_clock_and_identity_bound(self):
        binding = _binding()
        self.assertEqual(binding.teardown_deadline_monotonic, 6220.0)
        self.assertNotEqual(binding.sha256, _binding(101.0).sha256)

    def test_file_guard_requires_two_fresh_exact_receipts(self):
        binding = _binding()
        now = [101.0]
        alive = {11, 12}

        def launcher(value, directory, deadline):
            for role, pid, script in (("primary", 11, "1" * 64), ("secondary", 12, "2" * 64)):
                common = {
                    "role": role, "binding_sha256": value.sha256,
                    "run_nonce": value.run_nonce, "pid": pid,
                    "observed_monotonic": now[0], "initial_provider_poll_ok": True,
                    "script_sha256": script,
                }
                for kind in ("armed", "heartbeat"):
                    document = {"schema_version": f"episode1.guard-{kind}.v1", **common}
                    (directory / f"{kind}-{role}.json").write_text(
                        canonical_json(document) + "\n", encoding="utf-8"
                    )
            return (11, 12)

        with tempfile.TemporaryDirectory() as tmp:
            guard = FileReceiptGuard(
                Path(tmp) / "guard", launcher=launcher,
                process_alive=lambda pid: pid in alive, monotonic=lambda: now[0],
                heartbeat_max_age_seconds=5,
            )
            result = guard.arm(binding, deadline_monotonic=110)
            self.assertTrue(result["armed"])
            self.assertTrue(guard.healthy(binding, deadline_monotonic=110))
            now[0] = 107
            self.assertFalse(guard.healthy(binding, deadline_monotonic=110))

    def test_cross_run_receipt_is_rejected(self):
        binding = _binding()

        def launcher(value, directory, deadline):
            for role, pid in (("primary", 11), ("secondary", 12)):
                document = {
                    "schema_version": "episode1.guard-armed.v1", "role": role,
                    "binding_sha256": "0" * 64, "run_nonce": value.run_nonce,
                    "pid": pid, "observed_monotonic": 101.0,
                    "initial_provider_poll_ok": True,
                    "script_sha256": ("1" if role == "primary" else "2") * 64,
                }
                (directory / f"armed-{role}.json").write_text(json.dumps(document))
            return (11, 12)

        with tempfile.TemporaryDirectory() as tmp:
            guard = FileReceiptGuard(
                Path(tmp) / "guard", launcher=launcher,
                process_alive=lambda pid: True, monotonic=lambda: 101.0,
            )
            with self.assertRaisesRegex(GuardError, "not bound"):
                guard.arm(binding, deadline_monotonic=110)

    def test_restart_defaults_to_cleanup_only(self):
        binding = _binding()
        base = dict(
            current_plan_sha256=binding.plan_sha256,
            current_clock_domain="boot-1", now_monotonic=102.0,
            owned_resource_journal_present=True, both_watchdogs_healthy=True,
            lifecycle_complete=False,
        )
        self.assertEqual(restart_disposition(binding, **base), "cleanup_only")
        for key, value in (
            ("current_plan_sha256", "f" * 64),
            ("current_clock_domain", "boot-2"),
            ("owned_resource_journal_present", False),
            ("both_watchdogs_healthy", False),
            ("lifecycle_complete", True),
        ):
            case = dict(base)
            case[key] = value
            self.assertEqual(restart_disposition(binding, **case), "cleanup_only")
        late = dict(base)
        late["now_monotonic"] = binding.teardown_deadline_monotonic
        self.assertEqual(restart_disposition(binding, **late), "cleanup_only")

    def test_nonfinite_health_clock_fails_closed(self):
        binding = _binding()
        with tempfile.TemporaryDirectory() as tmp:
            guard = FileReceiptGuard(
                Path(tmp) / "guard", launcher=lambda *_: (11, 12),
                process_alive=lambda _pid: True, monotonic=lambda: math.nan,
            )
            guard.binding = binding
            self.assertFalse(guard.healthy(binding, deadline_monotonic=110))

    def test_restart_rejects_nonfinite_clock(self):
        binding = _binding()
        with self.assertRaises(GuardError):
            restart_disposition(
                binding, current_plan_sha256=binding.plan_sha256,
                current_clock_domain=binding.clock_domain,
                now_monotonic=math.nan, owned_resource_journal_present=True,
                both_watchdogs_healthy=True, lifecycle_complete=False,
            )


if __name__ == "__main__":
    unittest.main()
