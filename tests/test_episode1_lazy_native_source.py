from __future__ import annotations

import unittest
from types import SimpleNamespace

from runpod_benchmark.episode1_orchestrator import LifecycleError, RuntimeHandle
from runpod_benchmark.episode1_telemetry import LazyNativeSamplerSource


class FakeSampler:
    reap_reserve_ns = 10

    def __init__(self, *, fail_after_ownership: bool = False):
        self.fail_after_ownership = fail_after_ownership
        self.alive = False
        self.start_calls = []
        self.stop_calls = []
        self.store = SimpleNamespace(directory=None)
        self.records = []

    def start(self, *, start_ns: int, hard_deadline_ns: int) -> None:
        self.alive = True
        self.start_calls.append((start_ns, hard_deadline_ns))
        if self.fail_after_ownership:
            raise RuntimeError("injected failure after ownership")

    def stop(self, *, drain_ns: int, join_deadline_ns: int) -> None:
        self.stop_calls.append((drain_ns, join_deadline_ns))
        self.alive = False


class LazyNativeSamplerSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = [100]
        self.factory_calls = []
        self.sampler = FakeSampler()

    def factory(self, binding, handle):
        self.factory_calls.append((binding, handle))
        self.sampler.binding = binding
        return self.sampler

    def adapter(self, factory=None):
        return LazyNativeSamplerSource(
            self.factory if factory is None else factory,
            run_id="run-1", attempt_id="attempt-1", runtime="vllm",
            block="block-1", clock_domain="linux-boot-id:abc",
            hard_deadline_ns=10_000_000_000, max_sampling_gap_ns=1_000,
            monotonic_ns=lambda: self.clock[0], maximum_source_bytes=1_000,
        )

    @staticmethod
    def handle(runtime="vllm", block="block-1"):
        return RuntimeHandle("private-runtime-id", runtime, block, 42, 99)

    def test_factory_is_lazy_and_receives_exact_handle_and_pid_binding(self):
        source = self.adapter()
        handle = self.handle()
        self.assertEqual(self.factory_calls, [])
        source.start(handle, deadline_monotonic=9.0)
        self.assertEqual(len(self.factory_calls), 1)
        binding, received_handle = self.factory_calls[0]
        self.assertIs(received_handle, handle)
        self.assertEqual(
            (binding.run_id, binding.attempt_id, binding.runtime, binding.block,
             binding.process_identity, binding.process_start_identity,
             binding.clock_domain),
            ("run-1", "attempt-1", "vllm", "block-1", "pid:42", "ticks:99",
             "linux-boot-id:abc"),
        )
        self.assertEqual(self.sampler.start_calls, [(100, 10_000_000_000)])

    def test_runtime_and_block_mismatch_fail_before_factory(self):
        for handle in (self.handle(runtime="sglang"), self.handle(block="block-2")):
            with self.subTest(handle=handle):
                self.factory_calls.clear()
                with self.assertRaisesRegex(LifecycleError, "runtime or block mismatch"):
                    self.adapter().start(handle, deadline_monotonic=9.0)
                self.assertEqual(self.factory_calls, [])

    def test_reuse_is_rejected_without_second_factory_call(self):
        source = self.adapter()
        source.start(self.handle(), deadline_monotonic=9.0)
        with self.assertRaisesRegex(LifecycleError, "cannot be reused"):
            source.start(self.handle(), deadline_monotonic=9.0)
        self.assertEqual(len(self.factory_calls), 1)

    def test_factory_failure_is_closed_and_cannot_be_retried(self):
        calls = []

        def fail(binding, handle):
            calls.append((binding, handle))
            raise RuntimeError("private detail")

        source = self.adapter(fail)
        with self.assertRaisesRegex(LifecycleError, "factory failed"):
            source.start(self.handle(), deadline_monotonic=9.0)
        source.abort(deadline_monotonic=9.0)
        with self.assertRaisesRegex(LifecycleError, "cannot be reused"):
            source.start(self.handle(), deadline_monotonic=9.0)
        self.assertEqual(len(calls), 1)

    def test_factory_returning_different_binding_fails_closed(self):
        def mismatched(binding, handle):
            self.sampler.binding = None
            return self.sampler

        source = self.adapter(mismatched)
        with self.assertRaisesRegex(LifecycleError, "mismatched binding"):
            source.start(self.handle(), deadline_monotonic=9.0)
        self.assertEqual(self.sampler.start_calls, [])

    def test_abort_cleans_sampler_when_start_raises_after_ownership(self):
        self.sampler = FakeSampler(fail_after_ownership=True)
        source = self.adapter()
        with self.assertRaisesRegex(RuntimeError, "injected failure"):
            source.start(self.handle(), deadline_monotonic=9.0)
        self.assertTrue(self.sampler.alive)
        source.abort(deadline_monotonic=9.0)
        self.assertFalse(self.sampler.alive)
        self.assertEqual(len(self.sampler.stop_calls), 1)

    def test_expired_or_relaxed_operation_deadline_never_calls_factory(self):
        for deadline in (0.0000001, 11.0):
            with self.subTest(deadline=deadline):
                self.factory_calls.clear()
                with self.assertRaises((TimeoutError, LifecycleError)):
                    self.adapter().start(self.handle(), deadline_monotonic=deadline)
                self.assertEqual(self.factory_calls, [])

    def test_factory_deadline_crossing_fails_before_sampler_start(self):
        def slow_factory(binding, handle):
            self.clock[0] = 9_000_000_000
            self.sampler.binding = binding
            return self.sampler

        source = self.adapter(slow_factory)
        with self.assertRaises(TimeoutError):
            source.start(self.handle(), deadline_monotonic=9.0)
        self.assertEqual(self.sampler.start_calls, [])
        source.abort(deadline_monotonic=9.5)
        self.assertEqual(self.sampler.stop_calls, [])


if __name__ == "__main__":
    unittest.main()
