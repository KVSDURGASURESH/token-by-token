from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runpod_benchmark.episode1 import canonical_json
from runpod_benchmark.episode1_orchestrator import Allocation, RuntimeHandle
from runpod_benchmark.episode1_telemetry import (
    Episode1BlockTelemetry, NativeSamplerSource, TelemetrySeriesSpec,
)


class _Sampler:
    reap_reserve_ns = 1

    def __init__(self, clock):
        self.clock = clock
        self.store = SimpleNamespace(directory=None)
        self.records = []
        self.start_calls = 0
        self.stop_calls = 0

    def start(self, *, start_ns, hard_deadline_ns):
        self.start_calls += 1
        self.clock[0] = 1_000_000_000

    def stop(self, **kwargs):
        self.stop_calls += 1


class NativeSamplerSourceTests(unittest.TestCase):
    @staticmethod
    def _source(root: Path, payload: bytes, maximum: int, clock=None):
        target = root / "slot-00000001.json"
        target.write_bytes(payload)
        sampler = SimpleNamespace(
            reap_reserve_ns=1,
            store=SimpleNamespace(directory=root),
            records=[{
                "sequence": 1,
                "private_path": str(target),
                "file_sha256": hashlib.sha256(payload).hexdigest(),
            }],
        )
        values = [100] if clock is None else clock
        return NativeSamplerSource(
            sampler, hard_deadline_ns=10_000_000_000,
            max_sampling_gap_ns=1, maximum_source_bytes=maximum,
            monotonic_ns=lambda: values[0],
        )

    def test_worker_started_across_deadline_remains_abortable(self):
        clock = [100]
        sampler = _Sampler(clock)
        source = NativeSamplerSource(
            sampler, hard_deadline_ns=10_000_000_000,
            max_sampling_gap_ns=1, monotonic_ns=lambda: clock[0],
        )
        with self.assertRaises(TimeoutError):
            source.start(object(), deadline_monotonic=1.0)
        clock[0] = 1_000_000_001
        source.abort(deadline_monotonic=2.0)
        self.assertTrue(source._stopped)
        self.assertEqual((sampler.start_calls, sampler.stop_calls), (1, 1))

    def test_source_rejects_cap_plus_one(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            root = Path(temporary) / "evidence"
            root.mkdir(mode=0o700)
            with self.assertRaisesRegex(Exception, "retention bound"):
                self._source(root, b"12345", 4)._source(deadline_monotonic=1.0)

    def test_source_rejects_symlink_root(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            base = Path(temporary)
            actual = base / "actual"
            actual.mkdir(mode=0o700)
            target = actual / "slot-00000001.json"
            target.write_bytes(b"x")
            link = base / "evidence"
            link.symlink_to(actual, target_is_directory=True)
            sampler = SimpleNamespace(
                reap_reserve_ns=1, store=SimpleNamespace(directory=link),
                records=[{"sequence": 1, "private_path": str(link / target.name),
                          "file_sha256": hashlib.sha256(b"x").hexdigest()}],
            )
            source = NativeSamplerSource(
                sampler, hard_deadline_ns=10_000_000_000,
                max_sampling_gap_ns=1, maximum_source_bytes=4,
                monotonic_ns=lambda: 100,
            )
            with self.assertRaises(OSError):
                source._source(deadline_monotonic=1.0)

    def test_source_checks_deadline_after_hash(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            root = Path(temporary) / "evidence"
            root.mkdir(mode=0o700)
            clock = [100]
            source = self._source(root, b"x", 4, clock)
            real_sha256 = hashlib.sha256

            def expire(value=b""):
                clock[0] = 2_000_000_000
                return real_sha256(value)

            with patch("runpod_benchmark.episode1_telemetry.hashlib.sha256", side_effect=expire):
                with self.assertRaises(TimeoutError):
                    source._source(deadline_monotonic=1.0)

    def test_abort_persists_system_source_before_native_failure(self):
        class FailingNative:
            def start(self, handle, *, deadline_monotonic): pass
            def abort(self, *, deadline_monotonic): raise TimeoutError("join timed out")

        class Capture:
            def __init__(self): self.failed=[]
            def failed_telemetry_source(self, **value): self.failed.append(value)
            def system_source(self, value): pass
            contract=SimpleNamespace(run_id='run-1')

        capture=Capture()
        allocation=Allocation('pod','run-1','host',22022,22,'x'*64,'H100',1,'dc','SECURE',
            64,0,'/workspace','image','image',1.0)
        telemetry=Episode1BlockTelemetry(
            plan={'plan_sha256':'a'*64},block={'block_id':'block-1','runtime':'vllm'},
            run_attempt_id='attempt-1',startup_attempt_id='block-1-attempt-1',
            block_attempt=1,allocation=allocation,capture=capture,
            specs=(TelemetrySeriesSpec('system-rss','system_source_window','rss_bytes',
                'gauge',{'source':'procfs'}),),native=FailingNative(),
            max_system_sampling_gap_ns=1_000_000_000,native_clock_domain='clock',
        )
        telemetry.start(RuntimeHandle('process','vllm','block-1',42,99),deadline_monotonic=10.0)
        record={'schema_version':'episode1.system-sample.v1','sequence':1,
                'binding':{'run_id':'run-1','attempt_id':'attempt-1','block':'block-1'}}
        encoded=(canonical_json(record)+'\n').encode()
        telemetry.system_sample({'record':record,'source_sha256':hashlib.sha256(encoded).hexdigest()})
        with self.assertRaisesRegex(TimeoutError,'join timed out'):
            telemetry.abort(deadline_monotonic=10.0)
        self.assertEqual(len(capture.failed),1)
        self.assertEqual(capture.failed[0]['source_bytes'],encoded)
        self.assertEqual(capture.failed[0]['reason'],'block_abort')


if __name__ == "__main__":
    unittest.main()
