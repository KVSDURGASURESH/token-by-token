from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from runpod_benchmark import episode1_remote as REMOTE


def _assert_pid_absent_now(case: unittest.TestCase, pid: int) -> None:
    with case.assertRaises(ProcessLookupError):
        os.kill(pid, 0)


class BoundedSshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        key, known = root / "key", root / "known"
        key.write_text("test", encoding="utf-8")
        known.write_text("test", encoding="utf-8")
        key.chmod(0o600)
        known.chmod(0o600)
        config = REMOTE.SshConfig("192.0.2.1", 22, "root", key, known)
        self.executor = REMOTE.SshRemoteExecutor(config)
        self.processes: list[subprocess.Popen[bytes]] = []

    def tearDown(self) -> None:
        for process in self.processes:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=2)
        self.temp.cleanup()

    def _recording_popen(self):
        actual = subprocess.Popen

        def spawn(*args, **kwargs):
            process = actual(*args, **kwargs)
            self.processes.append(process)
            return process

        return patch.object(REMOTE.subprocess, "Popen", side_effect=spawn)

    def _assert_reaped(self, process: subprocess.Popen[bytes]) -> None:
        self.assertIsNotNone(process.returncode)
        with self.assertRaises(ChildProcessError):
            os.waitpid(process.pid, os.WNOHANG)

    def test_success_reaps_leader_and_finishes_pipes(self) -> None:
        with self._recording_popen():
            result = self.executor._run_bounded(
                [
                    sys.executable, "-c",
                    "import sys;sys.stdout.buffer.write(sys.stdin.buffer.read()+b'-ok')",
                ],
                b"sent",
                deadline_monotonic=time.monotonic() + 3,
                cancel_event=None,
            )
        self.assertEqual(result.stdout, b"sent-ok")
        self.assertEqual(result.returncode, 0)
        self._assert_reaped(self.processes[0])

    def test_exhausted_cleanup_reserve_fails_before_popen(self) -> None:
        with patch.object(REMOTE.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(REMOTE.RemoteExecutionError, "cleanup reserve"):
                self.executor._run_bounded(
                    [sys.executable, "-c", "pass"], None,
                    deadline_monotonic=time.monotonic() + 1.9,
                    cancel_event=None,
                )
        popen.assert_not_called()

    def test_thread_start_failure_still_kills_and_reaps_child(self) -> None:
        actual_start = REMOTE.threading.Thread.start
        starts = 0

        def fail_second_start(thread):
            nonlocal starts
            starts += 1
            if starts == 2:
                raise RuntimeError("synthetic local thread exhaustion")
            return actual_start(thread)

        with self._recording_popen(), patch.object(
            REMOTE.threading.Thread, "start", fail_second_start
        ):
            with self.assertRaisesRegex(REMOTE.RemoteExecutionError, "I/O setup failed"):
                self.executor._run_bounded(
                    [sys.executable, "-c", "import time;time.sleep(60)"], None,
                    deadline_monotonic=time.monotonic() + 2.5,
                    cancel_event=None,
                )
        self._assert_reaped(self.processes[0])

    def test_thread_constructor_failure_still_kills_and_reaps_child(self) -> None:
        with self._recording_popen(), patch.object(
            REMOTE.threading, "Thread", side_effect=RuntimeError("synthetic constructor failure")
        ):
            with self.assertRaisesRegex(REMOTE.RemoteExecutionError, "I/O setup failed"):
                self.executor._run_bounded(
                    [sys.executable, "-c", "import time;time.sleep(60)"], None,
                    deadline_monotonic=time.monotonic() + 2.5,
                    cancel_event=None,
                )
        self._assert_reaped(self.processes[0])

    def test_success_kills_closed_stdio_same_group_descendant(self) -> None:
        child_pid_file = Path(self.temp.name) / "closed-stdio-child.pid"
        child_code = "import time;time.sleep(60)"
        script = (
            "import pathlib,subprocess,sys;"
            f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}],"
            "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
            f"pathlib.Path({str(child_pid_file)!r}).write_text(str(p.pid))"
        )
        with self._recording_popen():
            result = self.executor._run_bounded(
                [sys.executable, "-c", script], None,
                deadline_monotonic=time.monotonic() + 3,
                cancel_event=None,
            )
        self.assertEqual(result.returncode, 0)
        self._assert_reaped(self.processes[0])
        self.assertTrue(child_pid_file.exists())
        _assert_pid_absent_now(self, int(child_pid_file.read_text()))

    def test_deadline_kills_pipe_holding_descendant_and_reaps_leader(self) -> None:
        child_pid_file = Path(self.temp.name) / "child.pid"
        child_code = "import time;time.sleep(60)"
        script = (
            "import pathlib,subprocess,sys;"
            f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}]);"
            f"pathlib.Path({str(child_pid_file)!r}).write_text(str(p.pid))"
        )
        started = time.monotonic()
        with self._recording_popen():
            with self.assertRaisesRegex(REMOTE.RemoteExecutionError, "cancelled or exceeded"):
                self.executor._run_bounded(
                    [sys.executable, "-c", script], None,
                    deadline_monotonic=started + 2.35,
                    cancel_event=None,
                )
        self.assertLessEqual(time.monotonic(), started + 2.35 + 0.05)
        self._assert_reaped(self.processes[0])
        self.assertTrue(child_pid_file.exists())
        _assert_pid_absent_now(self, int(child_pid_file.read_text()))

    def test_stopped_term_ignoring_process_is_killed_and_reaped(self) -> None:
        script = (
            "import os,signal;"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            "os.kill(os.getpid(),signal.SIGSTOP)"
        )
        started = time.monotonic()
        with self._recording_popen():
            with self.assertRaisesRegex(REMOTE.RemoteExecutionError, "cancelled or exceeded"):
                self.executor._run_bounded(
                    [sys.executable, "-c", script], None,
                    deadline_monotonic=started + 2.35,
                    cancel_event=None,
                )
        self.assertLessEqual(time.monotonic(), started + 2.35 + 0.05)
        self._assert_reaped(self.processes[0])
        self.assertEqual(self.processes[0].returncode, -signal.SIGKILL)

    def test_term_ignoring_descendant_is_killed_with_group(self) -> None:
        child_pid_file = Path(self.temp.name) / "ignoring-child.pid"
        child_code = (
            "import signal,time;"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            "time.sleep(60)"
        )
        script = (
            "import pathlib,subprocess,sys,time;"
            f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}]);"
            f"pathlib.Path({str(child_pid_file)!r}).write_text(str(p.pid));"
            "time.sleep(60)"
        )
        started = time.monotonic()
        with self._recording_popen():
            with self.assertRaisesRegex(REMOTE.RemoteExecutionError, "cancelled or exceeded"):
                self.executor._run_bounded(
                    [sys.executable, "-c", script], None,
                    deadline_monotonic=started + 2.35,
                    cancel_event=None,
                )
        self.assertLessEqual(time.monotonic(), started + 2.35 + 0.05)
        self._assert_reaped(self.processes[0])
        self.assertTrue(child_pid_file.exists())
        _assert_pid_absent_now(self, int(child_pid_file.read_text()))

    def test_cancellation_uses_reserved_cleanup_and_reaps(self) -> None:
        cancelled = threading.Event()
        cancelled.set()
        started = time.monotonic()
        with self._recording_popen():
            with self.assertRaisesRegex(REMOTE.RemoteExecutionError, "cancelled or exceeded"):
                self.executor._run_bounded(
                    [sys.executable, "-c", "import time;time.sleep(60)"], None,
                    deadline_monotonic=started + 2.5,
                    cancel_event=cancelled,
                )
        self.assertLess(time.monotonic() - started, 1.0)
        self._assert_reaped(self.processes[0])


if __name__ == "__main__":
    unittest.main()
