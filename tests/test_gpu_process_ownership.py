from __future__ import annotations

import copy
import hashlib
import json
import time
import unittest
from unittest import mock

from runpod_benchmark import gpu_process_ownership as g


def stat(pid, parent, start):
    return (f"{pid} (worker name) " + " ".join(['S', str(parent)] + ['0'] * 17 + [str(start)])).encode()


def status(nspid):
    return ("Name:\tworker\n" + ("NSpid:\t" + "\t".join(map(str, nspid)) + "\n" if nspid is not None else "")).encode()


class FakeProc:
    def __init__(self, snapshots):
        self.snapshots = snapshots; self.call = 0; self.current = None
    def pids(self, deadline, monotonic):
        self.current = self.snapshots[min(self.call, len(self.snapshots) - 1)]
        self.call += 1
        return sorted(self.current)
    def read(self, path, max_bytes, deadline, monotonic):
        _proc, pid, kind = path.split('/')[1:]
        value = self.current[int(pid)][kind]
        if len(value) > max_bytes: raise g.OwnershipError('fixture_oversize')
        return value


class MutableClock:
    def __init__(self, value=1): self.value = value; self.remaining = None
    def arm(self, remaining): self.remaining = remaining
    def __call__(self):
        if self.remaining is not None:
            if self.remaining == 0: self.value = 100
            else: self.remaining -= 1
        return self.value


def snap(child_start=110, child_parent=10, child_nspid=(10011, 11), extra=None):
    value = {
        10: {'stat': stat(10, 1, 100), 'status': status((10010, 10))},
        11: {'stat': stat(11, child_parent, child_start), 'status': status(child_nspid)},
    }
    if extra: value.update(extra)
    return value


class Runner:
    def __init__(self, result): self.result = result; self.calls = []
    def __call__(self, argv, deadline):
        self.calls.append((tuple(argv), deadline)); return self.result


def collect(proc, raw=b'11, GPU-abc, 123\n', domain='proc_pid', result=None):
    runner = Runner(result or g.CommandResult('ok', raw, None))
    receipt = g.collect(root_pid=10, root_start_ticks=100, expected_gpu_uuid='GPU-abc',
                        pid_domain=domain, runner=runner, proc=proc,
                        deadline_monotonic_ns=1000, monotonic_ns=lambda: 100)
    return receipt, runner


class OwnershipTests(unittest.TestCase):
    def test_direct_pid_receipt_is_closed_and_bound(self):
        receipt, runner = collect(FakeProc([snap(), snap()]))
        self.assertEqual(runner.calls, [(g.QUERY, 1000)])
        self.assertEqual(receipt['processes'][0]['proc_start_ticks'], 110)
        self.assertEqual(receipt['total_used_memory_mib'], 123)
        g.verify(receipt, root_pid=10, root_start_ticks=100,
                 expected_gpu_uuid='GPU-abc', pid_domain='proc_pid')

    def test_outermost_namespace_pid_maps_explicitly(self):
        receipt, _ = collect(FakeProc([snap(), snap()]), raw=b'10011, GPU-abc, 9\n',
                             domain='outermost_nspid')
        self.assertEqual(receipt['processes'][0]['proc_pid'], 11)
        self.assertEqual(receipt['processes'][0]['nspid'], [10011, 11])

    def test_unrelated_process_is_rejected(self):
        with self.assertRaisesRegex(g.OwnershipError, 'not_owned'):
            collect(FakeProc([snap(child_parent=1), snap(child_parent=1)]))

    def test_ambiguous_namespace_mapping_is_rejected(self):
        extra = {12: {'stat': stat(12, 10, 120), 'status': status((10011, 12))}}
        with self.assertRaisesRegex(g.OwnershipError, 'ambiguous'):
            collect(FakeProc([snap(extra=extra), snap(extra=extra)]),
                    raw=b'10011, GPU-abc, 9\n', domain='outermost_nspid')

    def test_pid_reuse_between_query_and_second_snapshot_is_rejected(self):
        with self.assertRaisesRegex(g.OwnershipError, 'identity_changed'):
            collect(FakeProc([snap(), snap(child_start=111)]))

    def test_ancestor_reuse_between_snapshots_is_rejected(self):
        before = {
            10: {'stat': stat(10, 1, 100), 'status': status((10010, 10))},
            11: {'stat': stat(11, 10, 110), 'status': status((10011, 11))},
            12: {'stat': stat(12, 11, 120), 'status': status((10012, 12))},
        }
        after = copy.deepcopy(before)
        after[11]['stat'] = stat(11, 10, 111)
        with self.assertRaisesRegex(g.OwnershipError, 'identity_changed'):
            collect(FakeProc([before, after]), raw=b'12, GPU-abc, 9\n')

    def test_missing_namespace_mapping_is_rejected(self):
        with self.assertRaisesRegex(g.OwnershipError, 'missing_or_ambiguous'):
            collect(FakeProc([snap(child_nspid=None), snap(child_nspid=None)]),
                    raw=b'10011, GPU-abc, 9\n', domain='outermost_nspid')

    def test_wrong_device_duplicate_empty_and_malformed_are_rejected(self):
        cases = [
            (b'11, GPU-other, 1\n', 'unexpected_device'),
            (b'11, GPU-abc, 1\n11, GPU-abc, 2\n', 'duplicate'),
            (b'', 'missing_or_oversize'),
            (b'11, GPU-abc, [N/A]\n', 'malformed'),
        ]
        for raw, message in cases:
            with self.subTest(raw=raw), self.assertRaisesRegex(g.OwnershipError, message):
                collect(FakeProc([snap(), snap()]), raw=raw)

    def test_unavailable_is_failure_not_zero(self):
        with self.assertRaisesRegex(g.OwnershipError, 'query_unavailable'):
            collect(FakeProc([snap(), snap()]), result=g.CommandResult('unavailable', None, 'timeout'))

    def test_root_reuse_is_rejected(self):
        bad = snap(); bad[10] = {'stat': stat(10, 1, 101), 'status': status((10010, 10))}
        with self.assertRaisesRegex(g.OwnershipError, 'root_identity_changed'):
            collect(FakeProc([bad, bad]))

    def test_receipt_tampering_and_open_fields_are_rejected(self):
        receipt, _ = collect(FakeProc([snap(), snap()]))
        tampered = copy.deepcopy(receipt); tampered['processes'][0]['used_memory_mib'] = 999
        with self.assertRaisesRegex(g.OwnershipError, 'aggregate_invalid|hash_invalid'):
            g.verify(tampered, root_pid=10, root_start_ticks=100,
                     expected_gpu_uuid='GPU-abc', pid_domain='proc_pid')
        opened = copy.deepcopy(receipt); opened['extra'] = True
        with self.assertRaisesRegex(g.OwnershipError, 'open_or_wrong_schema'):
            g.verify(opened, root_pid=10, root_start_ticks=100,
                     expected_gpu_uuid='GPU-abc', pid_domain='proc_pid')

    def test_deadline_is_forwarded_unchanged_and_exhaustion_fails(self):
        receipt, runner = collect(FakeProc([snap(), snap()]))
        self.assertEqual(runner.calls[0][1], 1000)
        with self.assertRaisesRegex(g.OwnershipError, 'deadline_exhausted'):
            g.collect(root_pid=10, root_start_ticks=100, expected_gpu_uuid='GPU-abc',
                      pid_domain='proc_pid', runner=runner, proc=FakeProc([snap()]),
                      deadline_monotonic_ns=100, monotonic_ns=lambda: 100)

    def test_deadline_during_inventory_scan_and_tree_prevents_runner(self):
        clock = MutableClock()

        class InventoryExpiry(FakeProc):
            def pids(self, deadline, monotonic):
                self.current = self.snapshots[0]
                clock.value = deadline
                return sorted(self.current)

        class ScanExpiry(FakeProc):
            def read(self, path, max_bytes, deadline, monotonic):
                value = super().read(path, max_bytes, deadline, monotonic)
                clock.value = deadline
                return value

        class ClosureExpiry(FakeProc):
            def __init__(self, snapshots): super().__init__(snapshots); self.reads = 0
            def read(self, path, max_bytes, deadline, monotonic):
                value = super().read(path, max_bytes, deadline, monotonic)
                self.reads += 1
                if self.reads == 4: clock.arm(2)
                return value

        for source, reason in ((InventoryExpiry([snap()]), 'inventory'),
                               (ScanExpiry([snap()]), 'proc_scan'),
                               (ClosureExpiry([snap()]), 'tree_build')):
            with self.subTest(reason=reason):
                clock.value, clock.remaining = 1, None
                runner = Runner(g.CommandResult('ok', b'11, GPU-abc, 1\n', None))
                with self.assertRaisesRegex(g.OwnershipError, reason):
                    g.collect(root_pid=10, root_start_ticks=100, expected_gpu_uuid='GPU-abc',
                              pid_domain='proc_pid', runner=runner, proc=source,
                              deadline_monotonic_ns=100, monotonic_ns=clock)
                self.assertEqual(runner.calls, [])

    def test_inventory_and_snapshot_byte_limits_prevent_runner(self):
        for patch_name, patch_value, reason in (
            ('MAX_PROCESSES', 1, 'proc_process_limit'),
            ('MAX_TOTAL_PROC_BYTES', 1, 'proc_snapshot_byte_limit'),
        ):
            with self.subTest(bound=patch_name), mock.patch.object(g, patch_name, patch_value):
                runner = Runner(g.CommandResult('ok', b'11, GPU-abc, 1\n', None))
                with self.assertRaisesRegex(g.OwnershipError, reason):
                    g.collect(root_pid=10, root_start_ticks=100, expected_gpu_uuid='GPU-abc',
                              pid_domain='proc_pid', runner=runner, proc=FakeProc([snap()]),
                              deadline_monotonic_ns=100, monotonic_ns=lambda: 1)
                self.assertEqual(runner.calls, [])

    def test_no_success_if_deadline_expires_during_final_verification(self):
        clock = MutableClock()
        original = g.verify
        def verify_then_expire(*args, **kwargs):
            original(*args, **kwargs); clock.value = 100
        with mock.patch.object(g, 'verify', side_effect=verify_then_expire):
            with self.assertRaisesRegex(g.OwnershipError, 'after_verification'):
                g.collect(root_pid=10, root_start_ticks=100, expected_gpu_uuid='GPU-abc',
                          pid_domain='proc_pid', runner=Runner(g.CommandResult('ok', b'11, GPU-abc, 1\n', None)),
                          proc=FakeProc([snap(), snap()]), deadline_monotonic_ns=100,
                          monotonic_ns=clock)

    def test_verifier_rejects_semantically_invalid_mapping_even_when_rehashed(self):
        receipt, _ = collect(FakeProc([snap(), snap()]))
        receipt['processes'][0]['nvidia_pid'] = 12
        unsigned = dict(receipt); unsigned.pop('receipt_sha256')
        receipt['receipt_sha256'] = hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        ).hexdigest()
        with self.assertRaisesRegex(g.OwnershipError, 'mapping_invalid'):
            g.verify(receipt, root_pid=10, root_start_ticks=100,
                     expected_gpu_uuid='GPU-abc', pid_domain='proc_pid')

    def test_bool_root_and_nonstring_gpu_uuid_are_rejected_cleanly(self):
        receipt, _ = collect(FakeProc([snap(), snap()]))
        receipt['root'] = {'pid': True, 'start_ticks': 100}
        with self.assertRaisesRegex(g.OwnershipError, 'invalid_integer'):
            g.verify(receipt, root_pid=1, root_start_ticks=100,
                     expected_gpu_uuid='GPU-abc', pid_domain='proc_pid')
        with self.assertRaisesRegex(g.OwnershipError, 'invalid_expected_gpu_uuid'):
            g.collect(root_pid=10, root_start_ticks=100, expected_gpu_uuid=None,
                      pid_domain='proc_pid', runner=Runner(g.CommandResult('ok', b'', None)),
                      proc=FakeProc([snap()]), deadline_monotonic_ns=100,
                      monotonic_ns=lambda: 1)
        with self.assertRaisesRegex(g.OwnershipError, 'invalid_verification_binding'):
            g.verify(receipt, root_pid=10, root_start_ticks=100,
                     expected_gpu_uuid=None, pid_domain='proc_pid')

    def test_bounded_local_command_success_and_timeout(self):
        result = g.run_command(('/bin/echo', 'ok'), time.monotonic_ns() + 1_000_000_000,
                               cleanup_reserve_ns=100_000_000)
        self.assertEqual((result.status, result.stdout, result.reason), ('ok', b'ok\n', None))
        started = time.monotonic()
        result = g.run_command(('/bin/sh', '-c', 'sleep 5'),
                               time.monotonic_ns() + 400_000_000,
                               cleanup_reserve_ns=200_000_000)
        self.assertEqual((result.status, result.reason), ('unavailable', 'command_timeout'))
        self.assertLess(time.monotonic() - started, 1.0)


if __name__ == '__main__': unittest.main()
