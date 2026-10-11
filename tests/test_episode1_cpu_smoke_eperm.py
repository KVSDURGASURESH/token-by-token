import importlib.util
import signal
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


PATH = Path(__file__).resolve().parents[1] / "scripts" / "episode1_cpu_smoke.py"
SPEC = importlib.util.spec_from_file_location("episode1_cpu_smoke_eperm", PATH)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class GroupPermissionTests(unittest.TestCase):
    def test_eperm_means_present_but_not_owned_for_signaling(self):
        calls = []

        def denied(pgid, sig):
            calls.append((pgid, sig))
            raise PermissionError(1, "operation not permitted")

        with mock.patch.object(smoke.os, "killpg", side_effect=denied):
            self.assertTrue(smoke._group_exists(12345))
            with self.assertRaisesRegex(ValueError,
                                        "control_startup_cleanup_not_permitted"):
                smoke._cleanup_group(12345, time.monotonic() + 0.2)

        self.assertEqual(calls, [(12345, 0), (12345, 0),
                                 (12345, signal.SIGTERM)])
        self.assertNotIn((12345, signal.SIGKILL), calls)

    def test_disappeared_group_is_successful_absence(self):
        with mock.patch.object(smoke.os, "killpg",
                               side_effect=ProcessLookupError()):
            self.assertFalse(smoke._group_exists(12345))
            smoke._cleanup_group(12345, time.monotonic() + 0.2)

    def test_created_background_group_is_reaped(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / "child.pid"
            code = ("import pathlib,subprocess,sys;"
                    "p=subprocess.Popen([sys.executable,'-c',"
                    "'import time;time.sleep(30)']);"
                    f"pathlib.Path({str(pidfile)!r}).write_text(str(p.pid))")
            try:
                with self.assertRaisesRegex(ValueError,
                                            "control_startup_descendants"):
                    smoke.control_command([sys.executable, "-c", code],
                                          cwd=directory, timeout=1)
                child = int(pidfile.read_text())
                with self.assertRaises(ProcessLookupError):
                    os.kill(child, 0)
            finally:
                if pidfile.exists():
                    child = int(pidfile.read_text())
                    try:
                        os.kill(child, signal.SIGKILL)
                    except ProcessLookupError:
                        pass


if __name__ == "__main__": unittest.main()
