import hashlib
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from runpod_benchmark.episode1_runpod_adapter import (
    _NATIVE_METRICS,
    _CleanupOnlyProvider,
    _PreCreateGuardedProvider,
    _core_provider,
    _normalize_token_ids,
    build_cleanup_provider,
)
from runpod_benchmark.native_sampler import parse_prometheus
from runpod_benchmark.runpod_v2 import OwnedResource, Response


class RunpodAdapterTests(unittest.TestCase):
    def _authority(self, *, private_id="pod-1"):
        return SimpleNamespace(
            private_id=private_id,
            unique_name="episode1-owned",
            ownership_token="private-token",
            billing_started_monotonic=12.5,
        )

    def test_cleanup_factory_exposes_no_create_capability(self) -> None:
        provider = build_cleanup_provider()
        for name in ("create", "create_pod", "create_allocation"):
            self.assertFalse(callable(getattr(provider, name, None)))

    @patch("runpod_benchmark.episode1_runpod_adapter._transport")
    def test_core_provider_validates_all_settings_before_transport(self, transport) -> None:
        with patch.dict(os.environ, {"RUNPOD_API_KEY": "private"}, clear=True):
            with self.assertRaisesRegex(ValueError, "APPROVED_IMAGE_REFERENCE"):
                _core_provider(persist_owned=lambda _owned: None)
        transport.assert_not_called()

    @patch(
        "runpod_benchmark.episode1_runpod_adapter.RunpodV2Provider",
        side_effect=RuntimeError("synthetic constructor failure"),
    )
    @patch("runpod_benchmark.episode1_runpod_adapter._transport")
    def test_core_provider_closes_transport_if_constructor_fails(
        self, transport_factory, _provider
    ) -> None:
        transport = MagicMock()
        transport_factory.return_value = transport
        settings = {
            "RUNPOD_API_KEY": "private",
            "EPISODE1_APPROVED_IMAGE_REFERENCE": "image@sha256:" + "a" * 64,
            "EPISODE1_AUTHORIZED_KEY_FINGERPRINT": "SHA256:fixture",
        }
        with patch.dict(os.environ, settings, clear=True):
            with self.assertRaisesRegex(RuntimeError, "constructor failure"):
                _core_provider(persist_owned=lambda _owned: None)
        transport.close.assert_called_once_with()

    def test_token_ids_accept_realistic_shapes_and_reject_ambiguous_values(self) -> None:
        self.assertEqual([1, 2], _normalize_token_ids([1, 2]))
        self.assertEqual([1, 2], _normalize_token_ids((1, 2)))
        self.assertEqual([1, 2], _normalize_token_ids([[1, 2]]))
        self.assertEqual(
            [1, 2], _normalize_token_ids(SimpleNamespace(input_ids=[[1, 2]]))
        )
        for invalid in ([True], [-1], [1.0], [[1], [2]], "1,2"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                _normalize_token_ids(invalid)

    def test_native_specs_match_representative_exporter_labels(self) -> None:
        model = "Qwen/Qwen2.5-32B-Instruct"
        common_vllm = f'model_name="{model}",engine="0"'
        common_sglang = (
            f'model_name="{model}",engine_type="unified",tp_rank="0",'
            'pp_rank="0",moe_ep_rank="0"'
        )
        bodies = {
            "vllm": (
                f'vllm:num_requests_running{{{common_vllm}}} 1\n'
                f'vllm:num_requests_waiting{{{common_vllm}}} 2\n'
                f'vllm:kv_cache_usage_perc{{{common_vllm}}} 0.5\n'
                '# TYPE vllm:request_queue_time_seconds histogram\n'
                f'vllm:request_queue_time_seconds_sum{{{common_vllm}}} 3\n'
                '# TYPE vllm:request_prefill_time_seconds histogram\n'
                f'vllm:request_prefill_time_seconds_sum{{{common_vllm}}} 4\n'
                '# TYPE vllm:request_decode_time_seconds histogram\n'
                f'vllm:request_decode_time_seconds_sum{{{common_vllm}}} 5\n'
            ).encode(),
            "sglang": (
                f'sglang:num_running_reqs{{{common_sglang}}} 1\n'
                f'sglang:num_queue_reqs{{{common_sglang}}} 2\n'
                f'sglang:full_token_usage{{{common_sglang}}} 0.5\n'
                '# TYPE sglang:queue_time_seconds histogram\n'
                f'sglang:queue_time_seconds_sum{{{common_sglang}}} 3\n'
                f'sglang:realtime_tokens_total{{{common_sglang},mode="prefill_compute"}} 4\n'
                f'sglang:realtime_tokens_total{{{common_sglang},mode="decode"}} 5\n'
            ).encode(),
        }
        for runtime, raw in bodies.items():
            parsed = parse_prometheus(raw)
            for spec in _NATIVE_METRICS[runtime]:
                matches = [
                    point for point in parsed.points
                    if point.metric_name == spec.metric_name
                    and dict(point.labels) == dict(spec.labels)
                ]
                with self.subTest(runtime=runtime, metric=spec.metric_name,
                                  labels=spec.labels):
                    self.assertEqual(1, len(matches))

    @patch("runpod_benchmark.episode1_runpod_adapter._core_provider")
    def test_cleanup_provider_binds_one_authority_and_reuses_transport(
        self, core_factory
    ) -> None:
        authority = self._authority()
        ownership_hash = hashlib.sha256(
            authority.ownership_token.encode()
        ).hexdigest()
        core = MagicMock()
        core._owned = {}
        core._path_id.return_value = "pod-1"
        core.OWNERSHIP_ENV = "EPISODE1_OWNERSHIP_SHA256"
        core.transport.request.return_value = Response(
            200,
            {
                "id": authority.private_id,
                "name": authority.unique_name,
                "env": {core.OWNERSHIP_ENV: ownership_hash},
            },
        )
        core.inventory_absent.return_value = True
        core.direct_not_found.return_value = True
        core_factory.return_value = core
        provider = _CleanupOnlyProvider()

        self.assertTrue(provider.poll_owned(authority, deadline_monotonic=20.0))
        self.assertTrue(provider.delete_owned(authority, deadline_monotonic=21.0))
        self.assertTrue(provider.inventory_absent(authority, deadline_monotonic=22.0))
        self.assertTrue(provider.direct_not_found(authority, deadline_monotonic=23.0))

        core_factory.assert_called_once()
        owned = OwnedResource("pod-1", "episode1-owned", "private-token", 12.5)
        self.assertEqual(core._owned, {"pod-1": owned})
        core.delete_allocation.assert_called_once_with(
            owned, deadline_monotonic=21.0
        )

        with self.assertRaisesRegex(ValueError, "another authority"):
            provider.poll_owned(
                self._authority(private_id="pod-2"), deadline_monotonic=24.0
            )

    @patch("runpod_benchmark.episode1_runpod_adapter.persist_authority")
    @patch("runpod_benchmark.episode1_runpod_adapter.prepare_launch")
    def test_precreate_permit_precedes_provider_create_and_binds_authority(
        self, prepare, persist
    ) -> None:
        events = []
        permit = object()
        prepare.side_effect = lambda **_kwargs: events.append("permit") or permit
        core = MagicMock()
        allocation = OwnedResource(
            "pod-1", "episode1-owned", "private-token", 12.5
        )
        core.create_allocation.side_effect = (
            lambda **_kwargs: events.append("create") or allocation
        )
        context = SimpleNamespace(
            plan_sha256="a" * 64,
            original_t0_monotonic=1.0,
            teardown_deadline_monotonic=30.0,
            hard_deadline_monotonic=40.0,
            clock_domain="test-clock",
        )
        provider = _PreCreateGuardedProvider(
            core,
            context=context,
            state_directory=Path("state"),
            permit_path=Path("state/permit.json"),
            authority_path=Path("state/authority.json"),
            entrypoint=Path("watchdog.py"),
            library_path=Path("library.py"),
            restart_entrypoint=Path("restart.py"),
            adapter_source=Path("adapter.py"),
        )
        plan = {"guard": {"local_watchdog_plan_sha256": "b" * 64}}

        result = provider.create_allocation(
            unique_name="episode1-owned",
            ownership_token="private-token",
            plan=plan,
            deadline_monotonic=20.0,
        )
        self.assertIs(result, allocation)
        self.assertEqual(events, ["permit", "create"])
        provider.persist(allocation)
        persist.assert_called_once_with(
            Path("state/authority.json"),
            permit,
            private_id="pod-1",
            unique_name="episode1-owned",
            ownership_token="private-token",
            billing_started_monotonic=12.5,
        )
        with self.assertRaisesRegex(RuntimeError, "single use"):
            provider.create_allocation(
                unique_name="episode1-owned",
                ownership_token="private-token",
                plan=plan,
                deadline_monotonic=20.0,
            )

    def test_precreate_rejects_authority_before_permit(self) -> None:
        provider = _PreCreateGuardedProvider(
            MagicMock(),
            context=MagicMock(),
            state_directory=Path("state"),
            permit_path=Path("state/permit.json"),
            authority_path=Path("state/authority.json"),
            entrypoint=Path("watchdog.py"),
            library_path=Path("library.py"),
            restart_entrypoint=Path("restart.py"),
            adapter_source=Path("adapter.py"),
        )
        with self.assertRaisesRegex(RuntimeError, "preceded"):
            provider.persist(
                OwnedResource("pod-1", "episode1-owned", "private-token", 12.5)
            )


if __name__ == "__main__":
    unittest.main()
