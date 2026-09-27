import json
import os
import signal
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from runpod_benchmark import system_sampler as ss


def proc_stat(pid=123, start=777, utime=11, stime=7, rss=5):
    fields = ["S"] + ["0"] * 49  # fields 3 through 52
    fields[11] = str(utime); fields[12] = str(stime)
    fields[19] = str(start); fields[21] = str(rss)
    return f"{pid} (worker name) " + " ".join(fields) + "\n"


class SystemSamplerTests(unittest.TestCase):
    def make_proc(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / "123").mkdir(); (root / "net").mkdir()
        (root / "123" / "stat").write_text(proc_stat())
        (root / "123" / "io").write_text("read_bytes: 30\nwrite_bytes: 40\n")
        (root / "stat").write_text("cpu 1 2 3 4 5 6 7 8 9 10\n")
        (root / "meminfo").write_text("MemTotal: 100 kB\nMemAvailable: 40 kB\n")
        (root / "net" / "dev").write_text(
            "Inter-| Receive | Transmit\n face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed\n"
            " eth0: 100 0 0 0 0 0 0 0 200 0 0 0 0 0 0 0\n")
        return temporary, ss.ProcAdapter(root)

    def test_proc_identity_and_counters(self):
        tmp, proc = self.make_proc()
        self.addCleanup(tmp.cleanup)
        metrics, identity = proc.collect(ss.ProcessTarget(123, 777, "server"))
        self.assertEqual(identity, (123, 777))
        values = {x["name"]: x["value"] for x in metrics}
        self.assertEqual(values["process.cpu_ticks"], 18)
        self.assertEqual(values["process.read"], 30)
        self.assertEqual(values["host.memory.total"], 102400)
        self.assertEqual(values["host.network.tx"], 200)

    def test_prestart_is_explicitly_unavailable(self):
        tmp, proc = self.make_proc(); self.addCleanup(tmp.cleanup)
        metrics, identity = proc.collect(None)
        self.assertIsNone(identity)
        process = [x for x in metrics if x["scope"] == "process"]
        self.assertTrue(process)
        self.assertTrue(all(x["value"] is None and x["reason"] == "prestart" for x in process))

    def test_reused_pid_is_not_data(self):
        tmp, proc = self.make_proc(); self.addCleanup(tmp.cleanup)
        metrics, identity = proc.collect(ss.ProcessTarget(123, 778, "server"))
        self.assertIsNone(identity)
        process = [x for x in metrics if x["scope"] == "process"]
        self.assertTrue(all(x["value"] is None and x["reason"] == "identity_changed" for x in process))

    def test_gpu_values_and_unsupported_are_distinct(self):
        row = b"GPU-abc, 91, 2048, 81920, 410.5, 71, 1410, N/A, 1410, 0x0\n"
        calls = []
        def runner(argv, deadline):
            calls.append((argv, deadline)); return ss.CommandResult("ok", None, row, 0)
        metrics = ss.NvidiaSmiAdapter(Path("/usr/bin/nvidia-smi"), "0", runner).collect(99)
        values = {x["name"]: x for x in metrics}
        self.assertEqual(values["utilization.gpu"]["value"], 91.0)
        self.assertIsNone(values["clocks.current.memory"]["value"])
        self.assertEqual(values["clocks.current.memory"]["reason"], "not_supported")
        self.assertEqual(calls[0][0][0], "/usr/bin/nvidia-smi")
        self.assertIn("--id=0", calls[0][0])

    def test_gpu_command_failure_never_becomes_zero(self):
        def runner(_argv, _deadline):
            return ss.CommandResult("unavailable", "command_timeout", b"", None)
        metrics = ss.NvidiaSmiAdapter(Path("/x/nvidia-smi"), "GPU-x", runner).collect(10)
        self.assertTrue(all(x["value"] is None and x["reason"] == "command_timeout" for x in metrics))

    def test_command_timeout_is_bounded(self):
        start = time.monotonic_ns()
        result = ss.run_command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start + 500_000_000, cleanup_reserve_ns=200_000_000)
        self.assertEqual((result.status, result.reason), ("unavailable", "command_timeout"))
        self.assertLess(time.monotonic_ns() - start, 1_500_000_000)

    def test_command_output_cap(self):
        result = ss.run_command(
            [sys.executable, "-c", "import os; os.write(1,b'x'*100000)"],
            time.monotonic_ns() + 1_000_000_000, max_bytes=4096)
        self.assertEqual((result.status, result.reason), ("unavailable", "output_limit"))

    def test_missing_command_is_unavailable(self):
        result = ss.run_command(["/definitely/missing/nvidia-smi"], time.monotonic_ns() + 500_000_000)
        self.assertEqual((result.status, result.reason), ("unavailable", "spawn_failed"))

    def test_timeout_reaps_background_group(self):
        with tempfile.TemporaryDirectory() as td:
            pidfile = Path(td) / "pid"
            code = ("import os,signal,time\n"
                    "p=os.fork()\n"
                    "if p == 0:\n"
                    " signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                    " time.sleep(30)\n"
                    " os._exit(0)\n"
                    f"open({str(pidfile)!r},'w').write(str(p))\n"
                    "time.sleep(30)\n")
            child = None
            try:
                result = ss.run_command([sys.executable, "-c", code],
                                        time.monotonic_ns() + 1_200_000_000,
                                        cleanup_reserve_ns=600_000_000)
                self.assertEqual(result.reason, "command_timeout")
                self.assertTrue(pidfile.exists())
                child = int(pidfile.read_text())
                self.assertGreater(child, 1)
                with self.assertRaises(ProcessLookupError):
                    os.kill(child, 0)
            finally:
                if child is not None:
                    try: os.kill(child, signal.SIGKILL)
                    except ProcessLookupError: pass

    def test_post_spawn_setup_failure_reaps_process(self):
        observed = []
        real_popen = ss.subprocess.Popen
        def capture(*args, **kwargs):
            process = real_popen(*args, **kwargs); observed.append(process); return process
        with mock.patch.object(ss.subprocess, "Popen", side_effect=capture), \
             mock.patch.object(ss.selectors, "DefaultSelector", side_effect=RuntimeError("fixture")):
            with self.assertRaisesRegex(RuntimeError, "fixture"):
                ss.run_command([sys.executable, "-c", "import time; time.sleep(30)"],
                               time.monotonic_ns() + 700_000_000,
                               cleanup_reserve_ns=500_000_000)
        self.assertEqual(len(observed), 1)
        self.assertIsNotNone(observed[0].poll())

    def test_slot_has_clock_gap_schedule_and_identity_evidence(self):
        tmp, proc = self.make_proc(); self.addCleanup(tmp.cleanup)
        row = b"GPU-x, 1, 2, 3, 4, 5, 6, 7, 8, 0x0\n"
        gpu = ss.NvidiaSmiAdapter(Path("/x/nvidia-smi"), "0",
            lambda _a, _d: ss.CommandResult("ok", None, row, 0))
        sampler = ss.SystemSampler(ss.Binding("run", "attempt", "block", "boot-1"), gpu, proc)
        scheduled = time.monotonic_ns() - 2_100_000_000
        record = sampler.sample_slot(scheduled, ss.ProcessTarget(123, 777, "server"), "measure")
        self.assertGreaterEqual(record["missed_slots"], 2)
        self.assertEqual(record["process_identity_status"], "ok")
        self.assertEqual(record["process_identity_before"], (123, 777))
        self.assertIsNone(record["observed_gap_ns"])
        self.assertGreaterEqual(record["clock_uncertainty_ns"], 0)
        record2 = sampler.sample_slot(scheduled + 3_000_000_000, ss.ProcessTarget(123, 777, "server"), "drain")
        self.assertIsInstance(record2["observed_gap_ns"], int)

    def test_gpu_command_never_exceeds_original_hard_deadline(self):
        tmp, proc = self.make_proc(); self.addCleanup(tmp.cleanup)
        deadlines = []
        row = b"GPU-x, 1, 2, 3, 4, 5, 6, 7, 8, 0x0\n"
        gpu = ss.NvidiaSmiAdapter(Path("/x/nvidia-smi"), "0",
            lambda _a, deadline: (deadlines.append(deadline) or ss.CommandResult("ok", None, row, 0)))
        sampler = ss.SystemSampler(ss.Binding("run", "attempt", "block", "boot-1"), gpu, proc)
        now = time.monotonic_ns(); hard = now + 100_000_000
        sampler.sample_slot(now, None, "drain", hard_deadline_ns=hard)
        self.assertLessEqual(deadlines[0], hard)

    def test_process_identity_rejects_float_values(self):
        with self.assertRaises(ValueError): ss.ProcessTarget(1.0, 2, "server")
        with self.assertRaises(ValueError): ss.ProcessTarget(1, 2.0, "server")

    def test_slot_survives_process_disappearance(self):
        tmp, proc = self.make_proc(); self.addCleanup(tmp.cleanup)
        original = proc.collect
        def disappearing(target):
            result = original(target)
            (Path(tmp.name) / "123" / "stat").unlink()
            return result
        proc.collect = disappearing
        row = b"GPU-x, 1, 2, 3, 4, 5, 6, 7, 8, 0x0\n"
        gpu = ss.NvidiaSmiAdapter(Path("/x/nvidia-smi"), "0",
            lambda _a, _d: ss.CommandResult("ok", None, row, 0))
        sampler = ss.SystemSampler(ss.Binding("run", "attempt", "block", "boot-1"), gpu, proc)
        record = sampler.sample_slot(time.monotonic_ns(), ss.ProcessTarget(123, 777, "server"), "drain")
        self.assertEqual(record["process_identity_status"], "process_unavailable")
        process = [x for x in record["metrics"] if x["scope"] == "process"]
        self.assertTrue(all(x["value"] is None and x["reason"] == "identity_changed" for x in process))

    def test_parse_stat_handles_spaces_and_parentheses_in_comm(self):
        text = proc_stat().replace("(worker name)", "(worker ) name)")
        self.assertEqual(ss.parse_proc_stat(text)["start_ticks"], 777)


if __name__ == "__main__":
    unittest.main()
