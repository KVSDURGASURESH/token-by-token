import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class FakeRunpodClient:
    def __init__(self, *, delete_failures=0, balance_failures=0, proof_failures=0, balance="14.000000"):
        self.delete_failures = delete_failures
        self.balance_failures = balance_failures
        self.proof_failures = proof_failures
        self.delete_calls = 0
        self.deleted = False
        self.balance_polls = 0
        self.balance = balance

    def balance_usd(self):
        self.balance_polls += 1
        if self.balance_polls <= self.balance_failures:
            raise RuntimeError("transient balance failure")
        return self.balance

    def delete_pod(self, resource_id):
        self.delete_calls += 1
        if self.delete_calls <= self.delete_failures:
            raise RuntimeError("transient delete failure")
        self.deleted = True
        return True

    def inventory_absent(self, resource_id):
        if self.proof_failures:
            self.proof_failures -= 1
            raise RuntimeError("transient inventory failure")
        return self.deleted

    def direct_not_found(self, resource_id):
        return self.deleted


class LocalWatchdogTests(unittest.TestCase):
    def test_watchdog_soft_stops_then_deletes_with_complete_proof(self):
        from local_watchdog import GuardConfig, run_watchdog

        clock = FakeClock()
        client = FakeRunpodClient(delete_failures=1)
        config = GuardConfig(
            max_usd=Decimal("8.00"),
            initial_balance_usd=Decimal("14.00"),
            hourly_usd=Decimal("3600.00"),
            deadline_seconds=100,
            poll_interval_seconds=1,
            soft_stop_fraction=Decimal("0.75"),
            teardown_fraction=Decimal("0.85"),
            delete_retry_delays_seconds=(0, 1, 2),
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_watchdog(
                config=config,
                client=client,
                resource_id="private-pod-id",
                role="primary",
                marker_dir=root / "markers",
                checkpoint_path=root / "primary.json",
                monotonic=clock.monotonic,
                sleep=clock.sleep,
            )

            self.assertTrue((root / "markers" / "stop-new-arms").exists())
            self.assertTrue((root / "markers" / "teardown-now").exists())
            self.assertEqual(result["trigger"], "teardown_threshold")
            self.assertEqual(client.delete_calls, 2)
            self.assertGreaterEqual(client.balance_polls, 2)
            self.assertTrue(result["deletion_acknowledged"])
            self.assertTrue(result["inventory_absent"])
            self.assertTrue(result["direct_not_found"])
            self.assertTrue(result["final_balance_observed"])
            rendered = (root / "primary.json").read_text(encoding="utf-8")
            self.assertNotIn("private-pod-id", rendered)

    def test_watchdog_survives_transient_balance_poll_failures(self):
        from local_watchdog import GuardConfig, run_watchdog

        clock = FakeClock()
        client = FakeRunpodClient(balance_failures=2)
        config = GuardConfig(
            max_usd=Decimal("8.00"), initial_balance_usd=Decimal("14.00"),
            hourly_usd=Decimal("1.00"), deadline_seconds=2,
            poll_interval_seconds=1, soft_stop_fraction=Decimal("0.75"),
            teardown_fraction=Decimal("0.85"), delete_retry_delays_seconds=(0, 1),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_watchdog(
                config=config, client=client, resource_id="private-pod-id",
                role="primary", marker_dir=root / "markers",
                checkpoint_path=root / "primary.json", monotonic=clock.monotonic,
                sleep=clock.sleep,
            )
        self.assertEqual(result["trigger"], "deadline")
        self.assertEqual(result["balance_poll_failures"], 2)

    def test_delete_retries_cover_proof_failures(self):
        from local_watchdog import GuardConfig, run_watchdog

        clock = FakeClock()
        client = FakeRunpodClient(proof_failures=1)
        config = GuardConfig(
            max_usd=Decimal("8.00"), initial_balance_usd=Decimal("14.00"),
            hourly_usd=Decimal("1.00"), deadline_seconds=1,
            poll_interval_seconds=1, soft_stop_fraction=Decimal("0.75"),
            teardown_fraction=Decimal("0.85"), delete_retry_delays_seconds=(0, 1),
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = run_watchdog(
                config=config, client=client, resource_id="private-pod-id",
                role="secondary", marker_dir=Path(tmp) / "markers",
                checkpoint_path=Path(tmp) / "secondary.json",
                monotonic=clock.monotonic, sleep=clock.sleep,
            )
        self.assertEqual(result["delete_attempts"], 2)
        self.assertTrue(result["inventory_absent"])

    def test_watchdog_deadline_deletes_before_budget_threshold(self):
        from local_watchdog import GuardConfig, run_watchdog

        clock = FakeClock()
        client = FakeRunpodClient()
        config = GuardConfig(
            max_usd=Decimal("8.00"),
            initial_balance_usd=Decimal("14.00"),
            hourly_usd=Decimal("1.731667"),
            deadline_seconds=3,
            poll_interval_seconds=1,
            soft_stop_fraction=Decimal("0.75"),
            teardown_fraction=Decimal("0.85"),
            delete_retry_delays_seconds=(0, 1),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_watchdog(
                config=config,
                client=client,
                resource_id="private-pod-id",
                role="secondary",
                marker_dir=root / "markers",
                checkpoint_path=root / "secondary.json",
                monotonic=clock.monotonic,
                sleep=clock.sleep,
            )
            self.assertEqual(result["trigger"], "deadline")
            self.assertTrue((root / "markers" / "teardown-now").exists())
            self.assertFalse((root / "markers" / "stop-new-arms").exists())

    def test_observed_balance_debit_can_trigger_teardown_before_modeled_cost(self):
        from local_watchdog import GuardConfig, run_watchdog

        clock = FakeClock()
        client = FakeRunpodClient(balance="5.00")
        config = GuardConfig(
            max_usd=Decimal("8.00"),
            initial_balance_usd=Decimal("14.00"),
            hourly_usd=Decimal("1.00"),
            deadline_seconds=3600,
            poll_interval_seconds=1,
            soft_stop_fraction=Decimal("0.75"),
            teardown_fraction=Decimal("0.85"),
            delete_retry_delays_seconds=(0, 1),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_watchdog(
                config=config,
                client=client,
                resource_id="private-pod-id",
                role="primary",
                marker_dir=root / "markers",
                checkpoint_path=root / "primary.json",
                monotonic=clock.monotonic,
                sleep=clock.sleep,
            )
            self.assertEqual(result["trigger"], "teardown_threshold")
            self.assertEqual(result["observed_balance_debit_usd"], "9.000000")
            self.assertEqual(result["guarded_exposure_usd"], "9.000000")

    def test_launcher_builds_two_caffeinated_independent_processes(self):
        from arm_local_watchdogs import build_watchdog_commands

        commands = build_watchdog_commands(
            python_bin="/usr/bin/python3",
            caffeinate_bin="/usr/bin/caffeinate",
            watchdog_script=Path("/repo/scripts/local_watchdog.py"),
            plan_path=Path("/private/plan.json"),
            resource_id_file=Path("/private/resource-id"),
            evidence_dir=Path("/private/evidence"),
            launch_nonce="fresh",
        )

        self.assertEqual(len(commands), 2)
        self.assertEqual({command[1] for command in commands}, {"-i"})
        self.assertEqual({command[4] for command in commands}, {"--role"})
        self.assertEqual({command[5] for command in commands}, {"primary", "secondary"})
        checkpoints = [command[command.index("--checkpoint") + 1] for command in commands]
        self.assertNotEqual(checkpoints[0], checkpoints[1])

    def test_inventory_parser_rejects_unknown_shapes(self):
        from local_watchdog import SubprocessRunpodClient

        client = SubprocessRunpodClient()
        client._run = lambda *_args: (0, {"unexpected": []})
        with self.assertRaisesRegex(RuntimeError, "inventory"):
            client.inventory_absent("private-pod-id")
        client._run = lambda *_args: (0, [{"id": "valid"}, "malformed"])
        with self.assertRaisesRegex(RuntimeError, "inventory"):
            client.inventory_absent("private-pod-id")

    def test_subprocess_calls_have_a_bound_timeout(self):
        from unittest.mock import patch
        from local_watchdog import SubprocessRunpodClient

        client = SubprocessRunpodClient(cli_timeout_seconds=7)
        with patch("local_watchdog.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = '{"clientBalance":"14.00"}'
            run.return_value.stderr = ""
            client.balance_usd()
        self.assertEqual(run.call_args.kwargs["timeout"], 7)

    def test_launcher_rejects_unbound_script_hashes(self):
        from arm_local_watchdogs import validate_script_hashes

        plan = {
            "guards": {
                "mode": "local_only_acknowledged",
                "watchdog_script_sha256": "0" * 64,
                "launcher_script_sha256": "1" * 64,
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watchdog = root / "watchdog.py"
            launcher = root / "launcher.py"
            watchdog.write_text("watchdog", encoding="utf-8")
            launcher.write_text("launcher", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "digest"):
                validate_script_hashes(plan, watchdog, launcher)

    def test_launcher_fails_closed_when_either_watchdog_exits_early(self):
        from arm_local_watchdogs import launch_watchdog_processes

        class FakeProcess:
            def __init__(self, pid, returncode):
                self.pid = pid
                self.returncode = returncode
                self.terminated = False

            def poll(self):
                return self.returncode

            def terminate(self):
                self.terminated = True

            def wait(self, timeout=None):
                return self.returncode

        created = [FakeProcess(101, None), FakeProcess(102, 1)]
        processes = created.copy()

        def fake_popen(*_args, **_kwargs):
            return processes.pop(0)

        emergency_calls = []
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "failed to stay alive"):
                launch_watchdog_processes(
                    commands=[["watchdog-primary"], ["watchdog-secondary"]],
                    evidence_dir=Path(tmp),
                    popen_factory=fake_popen,
                    settle_sleep=lambda _seconds: None,
                    arming_timeout_seconds=1,
                    launch_nonce="fresh",
                    on_failure=lambda: emergency_calls.append("delete"),
                )
            self.assertTrue(created[0].terminated)
            self.assertEqual(emergency_calls, ["delete"])

    def test_launcher_waits_for_both_armed_handshakes(self):
        from arm_local_watchdogs import launch_watchdog_processes

        class FakeProcess:
            pid = 101
            def poll(self): return None
            def terminate(self): pass

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = 0
            def settle(_seconds):
                nonlocal calls
                calls += 1
                if calls == 1:
                    for role in ("primary", "secondary"):
                        (root / f"watchdog-{role}-armed.json").write_text(
                            json.dumps({"armed": True, "role": role, "launch_nonce": "fresh"})
                        )
            pids = launch_watchdog_processes(
                commands=[["primary"], ["secondary"]], evidence_dir=root,
                popen_factory=lambda *_args, **_kwargs: FakeProcess(),
                settle_sleep=settle, arming_timeout_seconds=2,
                launch_nonce="fresh",
            )
            self.assertEqual(set(pids), {"primary", "secondary"})

    def test_launcher_rejects_stale_armed_handshakes(self):
        from arm_local_watchdogs import launch_watchdog_processes

        class FakeProcess:
            pid = 101
            terminated = False
            def poll(self): return None
            def terminate(self): self.terminated = True

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for role in ("primary", "secondary"):
                (root / f"watchdog-{role}-armed.json").write_text(
                    json.dumps({"armed": True, "role": role, "launch_nonce": "stale"})
                )
            with self.assertRaisesRegex(RuntimeError, "arm"):
                launch_watchdog_processes(
                    commands=[["primary"], ["secondary"]], evidence_dir=root,
                    popen_factory=lambda *_args, **_kwargs: FakeProcess(),
                    settle_sleep=lambda _seconds: None, arming_timeout_seconds=1,
                    launch_nonce="fresh",
                )


if __name__ == "__main__":
    unittest.main()
