from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from runpod_benchmark.episode1_remote import (
    Episode1CellDriver,
    RemoteExecutionError,
    SshConfig,
    SshRemoteExecutor,
    SshTunnel,
)


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.identity = root / "id"
        self.known_hosts = root / "known_hosts"
        self.identity.write_text("private-test-placeholder")
        self.known_hosts.write_text("host test-placeholder")
        os.chmod(self.identity, 0o600)
        os.chmod(self.known_hosts, 0o600)
        self.config = SshConfig("192.0.2.10", 22022, "root", self.identity, self.known_hosts)

    def tearDown(self):
        self.temp.cleanup()

    def test_injected_runner_output_is_bounded_on_both_streams(self):
        def runner(command, **kwargs):
            del command, kwargs
            return subprocess.CompletedProcess([], 0, json.dumps({"ok": True}).encode(), b"x" * (1024 * 1024 + 1))

        executor = SshRemoteExecutor(self.config, runner=runner)
        with self.assertRaisesRegex(RemoteExecutionError, "non-success"):
            executor.run_json(["probe"], timeout_seconds=1)

    def test_payload_limit_fails_before_starting_runner(self):
        called = False

        def runner(*args, **kwargs):
            nonlocal called
            called = True
            raise AssertionError

        executor = SshRemoteExecutor(self.config, runner=runner)
        with self.assertRaisesRegex(RemoteExecutionError, "input exceeds"):
            executor.run_json(["probe"], input_value={"value": "x" * (1024 * 1024 + 1)})
        self.assertFalse(called)

    def test_runner_result_received_after_original_deadline_is_rejected(self):
        clock = [10.0]

        def runner(command, **kwargs):
            del command, kwargs
            clock[0] = 11.1
            return subprocess.CompletedProcess([], 0, b'{"ok":true}', b"")

        executor = SshRemoteExecutor(self.config, runner=runner, monotonic=lambda: clock[0])
        with self.assertRaisesRegex(RemoteExecutionError, "exceeded its deadline"):
            executor.run_json(
                ["probe"], timeout_seconds=30, deadline_monotonic=11.0
            )

    def test_native_runner_kills_and_reaps_on_deadline(self):
        executor = SshRemoteExecutor(self.config)
        started = time.monotonic()
        with self.assertRaisesRegex(RemoteExecutionError, "cancelled or exceeded"):
            executor._run_bounded(
                [sys.executable, "-c", "import time; time.sleep(30)"], None,
                deadline_monotonic=started + 2.05, cancel_event=None,
            )
        self.assertLess(time.monotonic() - started, 3)

    def test_leader_exit_cannot_hide_pipe_holding_descendant_past_deadline(self):
        executor = SshRemoteExecutor(self.config)
        started = time.monotonic()
        script = (
            "import subprocess,sys; "
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
            "print('{}', flush=True)"
        )
        with self.assertRaisesRegex(RemoteExecutionError, "cancelled or exceeded"):
            executor._run_bounded(
                [sys.executable, "-c", script], None,
                deadline_monotonic=started + 2.1, cancel_event=None,
            )
        self.assertLess(time.monotonic() - started, 3)

    def test_native_runner_cancellation_kills_output_flood(self):
        executor = SshRemoteExecutor(self.config)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaisesRegex(RemoteExecutionError, "cancelled or exceeded"):
            executor._run_bounded(
                [sys.executable, "-c", "import sys,time; sys.stdout.write('x'*2000000); sys.stdout.flush(); time.sleep(30)"],
                None, deadline_monotonic=time.monotonic() + 3, cancel_event=cancel,
            )

    def test_tunnel_early_exit_sets_cancel_and_releases_ownership(self):
        class ExitedProcess:
            pid = 123456789

            def wait(self, timeout=None):
                del timeout
                return 1

            def poll(self):
                return 1

        executor = SshRemoteExecutor(self.config)
        tunnel = SshTunnel(executor, local_port=39123)
        with patch("runpod_benchmark.episode1_remote.subprocess.Popen", return_value=ExitedProcess()):
            with self.assertRaisesRegex(RemoteExecutionError, "exited before"):
                tunnel.start(deadline_monotonic=time.monotonic() + 5)
        self.assertTrue(tunnel.cancel_event.is_set())
        self.assertIsNone(tunnel.process)

    def test_cell_driver_rejects_endpoint_not_bound_to_owned_tunnel_first(self):
        tunnel = type("Tunnel", (), {"local_port": 39123})()
        with self.assertRaisesRegex(ValueError, "owned SSH tunnel port"):
            Episode1CellDriver(
                endpoint_url="http://127.0.0.1:39124/v1/chat/completions",
                model="fixture", prompt_evidence={}, input_token_counter=lambda _messages: 1,
                output_token_counter=lambda _text: 1, tunnel=tunnel,
            )

    def test_cell_driver_rejects_unreviewed_prompt_material(self):
        tunnel = type("Tunnel", (), {"local_port": 39123})()
        with self.assertRaisesRegex(ValueError, "reviewed artifact"):
            Episode1CellDriver(
                endpoint_url="http://127.0.0.1:39123/v1/chat/completions",
                model="fixture", prompt_evidence={"fixed": [], "natural_quality": []},
                input_token_counter=lambda _messages: 1,
                output_token_counter=lambda _text: 1, tunnel=tunnel,
            )


if __name__ == "__main__":
    unittest.main()
