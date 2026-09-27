"""Concrete, digest-bound Episode 1 production adapter.

Importing this module performs no provider request.  Credentials and private
paths are accepted only through the process environment and are never emitted.
"""

from __future__ import annotations

import hashlib
import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from episode1_watchdog import (
    ProcessLauncher,
    build_guard_commands,
    persist_authority,
    prepare_launch,
)
from runpod_benchmark.bounded_runpod_transport import BoundedRunpodTransport
from runpod_benchmark.episode1_guard import FileReceiptGuard
from runpod_benchmark.episode1_remote import (
    Episode1CellDriver,
    SshConfig,
    SshRemoteExecutor,
    SshTunnel,
)
from runpod_benchmark.episode1_runtime_control import SshRuntimeControl
from runpod_benchmark.episode1_telemetry import (
    Episode1BlockTelemetry,
    LazyNativeSamplerSource,
    TelemetrySeriesSpec,
)
from runpod_benchmark.native_sampler import (
    MetricSpec,
    NativeSampler,
    PrivateEvidenceStore,
    localhost_http_scraper,
)
from runpod_benchmark.runpod_v2 import OwnedResource, Response, RunpodV2Provider


_MODEL = "Qwen/Qwen2.5-32B-Instruct"
_ADAPTER_SPEC = "runpod_benchmark.episode1_runpod_adapter:build_cleanup_provider"
_SYSTEM_SPECS = (
    TelemetrySeriesSpec("system-gpu-utilization", "system_source_window", "utilization.gpu", "gauge", {"source": "nvidia-smi", "unit": "percent", "scope": "device"}),
    TelemetrySeriesSpec("system-gpu-memory-used", "system_source_window", "memory.used", "gauge", {"source": "nvidia-smi", "unit": "MiB", "scope": "device"}),
    TelemetrySeriesSpec("system-gpu-memory-total", "system_source_window", "memory.total", "gauge", {"source": "nvidia-smi", "unit": "MiB", "scope": "device"}),
    TelemetrySeriesSpec("system-gpu-power", "system_source_window", "power.draw", "gauge", {"source": "nvidia-smi", "unit": "W", "scope": "device"}),
    TelemetrySeriesSpec("system-gpu-temperature", "system_source_window", "temperature.gpu", "gauge", {"source": "nvidia-smi", "unit": "C", "scope": "device"}),
    TelemetrySeriesSpec("system-process-cpu-ticks", "system_source_window", "process.cpu_ticks", "counter", {"source": "procfs", "unit": "ticks", "scope": "process"}),
    TelemetrySeriesSpec("system-process-cpu-clock-hz", "system_source_window", "process.cpu.clock_ticks_per_second", "gauge", {"source": "sysconf", "unit": "ticks/s", "scope": "process"}),
    TelemetrySeriesSpec("system-process-rss", "system_source_window", "process.rss", "gauge", {"source": "procfs", "unit": "bytes", "scope": "process"}),
    TelemetrySeriesSpec("system-process-read", "system_source_window", "process.read", "counter", {"source": "procfs", "unit": "bytes", "scope": "process"}),
    TelemetrySeriesSpec("system-process-write", "system_source_window", "process.write", "counter", {"source": "procfs", "unit": "bytes", "scope": "process"}),
    TelemetrySeriesSpec("system-host-cpu-total", "system_source_window", "host.cpu.total_excluding_guest_duplicates_ticks", "counter", {"source": "procfs", "unit": "ticks", "scope": "host"}),
    TelemetrySeriesSpec("system-host-cpu-busy", "system_source_window", "host.cpu.busy_excluding_idle_iowait_ticks", "counter", {"source": "procfs", "unit": "ticks", "scope": "host"}),
    TelemetrySeriesSpec("system-host-cpu-logical-count", "system_source_window", "host.cpu.logical_count", "gauge", {"source": "procfs", "unit": "count", "scope": "host"}),
    TelemetrySeriesSpec("system-host-memory-total", "system_source_window", "host.memory.total", "gauge", {"source": "procfs", "unit": "bytes", "scope": "host"}),
    TelemetrySeriesSpec("system-host-memory-available", "system_source_window", "host.memory.available", "gauge", {"source": "procfs", "unit": "bytes", "scope": "host"}),
    TelemetrySeriesSpec("system-host-network-rx", "system_source_window", "host.network.rx", "counter", {"source": "procfs", "unit": "bytes", "scope": "host"}),
    TelemetrySeriesSpec("system-host-network-tx", "system_source_window", "host.network.tx", "counter", {"source": "procfs", "unit": "bytes", "scope": "host"}),
)
_NATIVE_METRICS = {
    "vllm": (
        MetricSpec("gauge", "vllm:num_requests_running", {"model_name": _MODEL, "engine": "0"}, "1"),
        MetricSpec("gauge", "vllm:num_requests_waiting", {"model_name": _MODEL, "engine": "0"}, "1"),
        MetricSpec("gauge", "vllm:kv_cache_usage_perc", {"model_name": _MODEL, "engine": "0"}, "1"),
        MetricSpec("counter", "vllm:request_queue_time_seconds_sum", {"model_name": _MODEL, "engine": "0"}, "seconds"),
        MetricSpec("counter", "vllm:request_prefill_time_seconds_sum", {"model_name": _MODEL, "engine": "0"}, "seconds"),
        MetricSpec("counter", "vllm:request_decode_time_seconds_sum", {"model_name": _MODEL, "engine": "0"}, "seconds"),
    ),
    "sglang": (
        MetricSpec("gauge", "sglang:num_running_reqs", {"model_name": _MODEL, "engine_type": "unified", "tp_rank": "0", "pp_rank": "0", "moe_ep_rank": "0"}, "1"),
        MetricSpec("gauge", "sglang:num_queue_reqs", {"model_name": _MODEL, "engine_type": "unified", "tp_rank": "0", "pp_rank": "0", "moe_ep_rank": "0"}, "1"),
        MetricSpec("gauge", "sglang:full_token_usage", {"model_name": _MODEL, "engine_type": "unified", "tp_rank": "0", "pp_rank": "0", "moe_ep_rank": "0"}, "1"),
        MetricSpec("counter", "sglang:queue_time_seconds_sum", {"model_name": _MODEL, "engine_type": "unified", "tp_rank": "0", "pp_rank": "0", "moe_ep_rank": "0"}, "seconds"),
        MetricSpec("counter", "sglang:realtime_tokens_total", {"model_name": _MODEL, "engine_type": "unified", "tp_rank": "0", "pp_rank": "0", "moe_ep_rank": "0", "mode": "prefill_compute"}, "tokens"),
        MetricSpec("counter", "sglang:realtime_tokens_total", {"model_name": _MODEL, "engine_type": "unified", "tp_rank": "0", "pp_rank": "0", "moe_ep_rank": "0", "mode": "decode"}, "tokens"),
    ),
}
_NATIVE_SERIES_IDS = (
    "native-active-requests", "native-waiting-requests", "native-kv-occupancy",
    "native-queue-seconds-sum", "native-prefill-work", "native-decode-work",
)


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"required private setting {name} is absent or invalid")
    return value


def _positive_port(name: str) -> int:
    raw = _required_environment(name)
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"private setting {name} is not a port") from exc
    if not 1 <= value <= 65535:
        raise ValueError(f"private setting {name} is not a port")
    return value


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _transport(api_key: str | None = None) -> BoundedRunpodTransport:
    return BoundedRunpodTransport(
        _required_environment("RUNPOD_API_KEY") if api_key is None else api_key,
        response_factory=Response,
    )


def _core_provider(*, persist_owned) -> RunpodV2Provider:
    # Read every required setting before the transport starts its broker.
    credential_value = _required_environment("RUNPOD_API_KEY")
    image = _required_environment("EPISODE1_APPROVED_IMAGE_REFERENCE")
    key_fingerprint = _required_environment(
        "EPISODE1_AUTHORIZED_KEY_FINGERPRINT"
    )
    transport = _transport(credential_value)
    try:
        return RunpodV2Provider(
            transport,
            approved_image_reference=image,
            approved_authorized_key_fingerprint=key_fingerprint,
            persist_owned=persist_owned,
        )
    except BaseException:
        try:
            transport.close()
        except BaseException:
            pass
        raise


class _CleanupOnlyProvider:
    """Watchdog surface for one authority; deliberately has no create method."""

    def __init__(self) -> None:
        self._core: RunpodV2Provider | None = None
        self._owned: OwnedResource | None = None

    def _bound(self, authority: Any) -> tuple[RunpodV2Provider, OwnedResource]:
        owned = OwnedResource(
            authority.private_id, authority.unique_name, authority.ownership_token,
            authority.billing_started_monotonic,
        )
        if self._core is None:
            self._core = _core_provider(persist_owned=lambda _owned: None)
            self._core._owned[owned.private_id] = owned
            self._owned = owned
        elif self._owned != owned:
            raise ValueError("cleanup provider cannot be rebound to another authority")
        return self._core, owned

    def poll_owned(self, authority: Any, *, deadline_monotonic: float) -> bool:
        core, owned = self._bound(authority)
        response = core.transport.request(
            "GET", f"/pods/{core._path_id(owned.private_id)}",
            deadline_monotonic=deadline_monotonic,
        )
        if response.status == 404:
            return False
        body = response.body
        env = body.get("env") if isinstance(body, Mapping) else None
        return bool(
            response.status == 200
            and isinstance(body, Mapping)
            and body.get("id") == owned.private_id
            and body.get("name") == owned.unique_name
            and isinstance(env, Mapping)
            and env.get(core.OWNERSHIP_ENV)
            == hashlib.sha256(owned.ownership_token.encode()).hexdigest()
        )

    def delete_owned(self, authority: Any, *, deadline_monotonic: float) -> bool:
        core, owned = self._bound(authority)
        # A 404 is an idempotently accepted cleanup result.  This matters when
        # the two independent watchdogs race to delete the same owned pod.
        core.delete_allocation(owned, deadline_monotonic=deadline_monotonic)
        return True

    def inventory_absent(self, authority: Any, *, deadline_monotonic: float) -> bool:
        core, owned = self._bound(authority)
        return core.inventory_absent(owned, deadline_monotonic=deadline_monotonic)

    def direct_not_found(self, authority: Any, *, deadline_monotonic: float) -> bool:
        core, owned = self._bound(authority)
        return core.direct_not_found(owned, deadline_monotonic=deadline_monotonic)

    def close(self, *, deadline_monotonic: float | None = None) -> bool:
        if self._core is None:
            return True
        return self._core.transport.close(deadline_monotonic=deadline_monotonic)


def build_cleanup_provider() -> _CleanupOnlyProvider:
    """Return the watchdog's cleanup-only capability."""
    return _CleanupOnlyProvider()


class _PreCreateGuardedProvider:
    def __init__(self, core: RunpodV2Provider, *, context: Any, state_directory: Path,
                 permit_path: Path, authority_path: Path, entrypoint: Path,
                 library_path: Path, restart_entrypoint: Path,
                 adapter_source: Path) -> None:
        self._core = core
        self._context = context
        self._state_directory = state_directory
        self._permit_path = permit_path
        self._authority_path = authority_path
        self._entrypoint = entrypoint
        self._library_path = library_path
        self._restart_entrypoint = restart_entrypoint
        self._adapter_source = adapter_source
        self._permit = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._core, name)

    def create_allocation(self, *, unique_name: str, ownership_token: str,
                          plan: Mapping[str, Any], deadline_monotonic: float):
        if self._permit is not None:
            raise RuntimeError("provider adapter create capability is single use")
        self._permit = prepare_launch(
            directory=self._state_directory,
            plan_sha256=self._context.plan_sha256,
            watchdog_plan_sha256=plan["guard"]["local_watchdog_plan_sha256"],
            unique_name=unique_name,
            ownership_token=ownership_token,
            original_t0_monotonic=self._context.original_t0_monotonic,
            arm_deadline_monotonic=deadline_monotonic,
            teardown_deadline_monotonic=self._context.teardown_deadline_monotonic,
            hard_deadline_monotonic=self._context.hard_deadline_monotonic,
            clock_domain=self._context.clock_domain,
            entrypoint=self._entrypoint,
            library_path=self._library_path,
            restart_entrypoint=self._restart_entrypoint,
            adapter_source=self._adapter_source,
        )
        return self._core.create_allocation(
            unique_name=unique_name, ownership_token=ownership_token, plan=plan,
            deadline_monotonic=deadline_monotonic,
        )

    def persist(self, owned: OwnedResource) -> None:
        if self._permit is None:
            raise RuntimeError("deletion authority preceded the pre-create permit")
        persist_authority(
            self._authority_path, self._permit, private_id=owned.private_id,
            unique_name=owned.unique_name, ownership_token=owned.ownership_token,
            billing_started_monotonic=owned.billing_started_monotonic,
        )

    def close(self, *, deadline_monotonic: float | None = None) -> bool:
        return self._core.transport.close(deadline_monotonic=deadline_monotonic)


def _ssh(allocation: Any) -> SshRemoteExecutor:
    return SshRemoteExecutor(SshConfig(
        host=allocation.ssh_host,
        public_port=allocation.ssh_public_port,
        user=os.environ.get("EPISODE1_SSH_USER", "root"),
        identity_file=Path(_required_environment("EPISODE1_SSH_IDENTITY_FILE")),
        known_hosts_file=Path(_required_environment("EPISODE1_SSH_KNOWN_HOSTS_FILE")),
    ))


def _tokenizer():
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(
        _required_environment("EPISODE1_TOKENIZER_DIRECTORY"),
        local_files_only=True,
    )


def _normalize_token_ids(value: Any) -> list[int]:
    if hasattr(value, "input_ids"):
        value = value.input_ids
    if isinstance(value, tuple):
        value = list(value)
    if isinstance(value, list) and len(value) == 1 and isinstance(
        value[0], (list, tuple)
    ):
        value = list(value[0])
    if not isinstance(value, list) or any(
        isinstance(item, bool) or not isinstance(item, int) or item < 0
        for item in value
    ):
        raise ValueError("tokenizer returned invalid input IDs")
    return list(value)


def build_episode1_components(*, context: Any, prompt_evidence: Mapping[str, Any],
                              private_evidence_directory: Path) -> Mapping[str, Any]:
    root = Path(__file__).resolve().parents[2]
    scripts = root / "scripts"
    entrypoint = (scripts / "watchdog_entry.py").resolve(strict=True)
    library_path = (scripts / "episode1_watchdog.py").resolve(strict=True)
    restart_entrypoint = (scripts / "restart_cleanup_entry.py").resolve(strict=True)
    adapter_source = Path(__file__).resolve(strict=True)
    evidence = private_evidence_directory.absolute()
    state_directory = evidence.parent / f".{evidence.name}.watchdog-state"
    guard_directory = evidence.parent / f".{evidence.name}.guard"
    permit_path = state_directory / "launch-permit.json"
    authority_path = state_directory / "authority.json"

    # Validate every fallible local dependency before starting the provider
    # transport broker.  No provider request is made here.
    tokenizer = _tokenizer()
    local_port = _positive_port("EPISODE1_LOCAL_PORT")

    holder: dict[str, Any] = {}

    def cleanup_partial(deadline: float) -> None:
        for owned in tuple(core._owned.values()):
            core.delete_allocation(owned, deadline_monotonic=deadline)
            if not core.inventory_absent(owned, deadline_monotonic=deadline):
                raise RuntimeError("partial guard cleanup inventory still contains pod")
            if not core.direct_not_found(owned, deadline_monotonic=deadline):
                raise RuntimeError("partial guard cleanup direct read still finds pod")

    commands, sleep_preventer = build_guard_commands(
        python=Path(sys.executable).resolve(strict=True), entrypoint=entrypoint,
        state_directory=state_directory, guard_directory=guard_directory,
        adapter_spec=_ADAPTER_SPEC, adapter_source=adapter_source,
        heartbeat_seconds=2.0, poll_timeout_seconds=5.0,
        retry_delays=(0.0, 1.0, 2.0, 4.0),
        sleep_preventer=("/usr/bin/caffeinate", "-w", "{worker_pid}"),
    )
    launcher = ProcessLauncher(
        permit_path=permit_path, authority_path=authority_path, commands=commands,
        cleanup_partial=cleanup_partial, sleep_preventer=sleep_preventer,
    )
    guard = FileReceiptGuard(
        guard_directory, launcher=launcher, process_alive=_process_alive,
        monotonic=time.monotonic, heartbeat_max_age_seconds=10.0,
    )

    tunnels: dict[str, SshTunnel] = {}
    runtimes: dict[str, SshRuntimeControl] = {}

    def input_ids(messages):
        return _normalize_token_ids(
            tokenizer.apply_chat_template(
                list(messages), tokenize=True, add_generation_prompt=True
            )
        )

    def input_count(messages):
        return len(input_ids(messages))

    def output_count(text: str):
        return len(tokenizer.encode(text, add_special_tokens=False))

    def runtime_factory(allocation):
        runtime = SshRuntimeControl(_ssh(allocation))
        runtimes[allocation.private_id] = runtime
        return runtime

    def cell_factory(allocation):
        tunnel = SshTunnel(_ssh(allocation), local_port=local_port, remote_port=8000)
        tunnels[allocation.private_id] = tunnel
        return Episode1CellDriver(
            endpoint_url=f"http://127.0.0.1:{local_port}/v1/chat/completions",
            model=_MODEL, prompt_evidence=prompt_evidence,
            input_token_counter=input_count, output_token_counter=output_count,
            input_token_ids=input_ids, tunnel=tunnel,
        )

    def telemetry_factory(plan, block, run_attempt_id, startup_attempt_id,
                          block_attempt, allocation, capture):
        family = str(block["runtime"]).split("-", 1)[0]
        native_metrics = _NATIVE_METRICS[family]
        specs = tuple(
            TelemetrySeriesSpec(series_id, "native", metric.metric_name,
                                metric.kind, metric.labels)
            for series_id, metric in zip(_NATIVE_SERIES_IDS, native_metrics)
        ) + _SYSTEM_SPECS
        if tuple(spec.series_id for spec in specs) != tuple(context.telemetry_series):
            raise ValueError("production telemetry contract differs from fixed adapter specs")
        tunnel = tunnels.get(allocation.private_id)
        if tunnel is None:
            raise RuntimeError("telemetry lacks the allocation-bound SSH tunnel")
        runtime = runtimes.get(allocation.private_id)
        if runtime is None:
            raise RuntimeError("telemetry lacks the allocation-bound runtime control")

        def sampler_factory(binding, handle):
            store = PrivateEvidenceStore(
                evidence / f"native-{startup_attempt_id}"
            )
            return NativeSampler(
                binding=binding,
                metrics=native_metrics,
                scrape=localhost_http_scraper(
                    f"http://127.0.0.1:{tunnel.local_port}/metrics"
                ),
                identity_probe=lambda deadline: runtime.observe_process_identity(
                    handle, deadline_monotonic=deadline / 1_000_000_000
                ),
                store=store, interval_ns=1_000_000_000,
                scrape_timeout_ns=750_000_000,
            )

        native = LazyNativeSamplerSource(
            sampler_factory, run_id=context.run_id,
            attempt_id=startup_attempt_id, runtime=str(block["runtime"]),
            block=str(block["block_id"]), clock_domain=context.clock_domain,
            hard_deadline_ns=int(context.hard_deadline_monotonic * 1_000_000_000),
            max_sampling_gap_ns=2_500_000_000, monotonic_ns=time.monotonic_ns,
        )
        return Episode1BlockTelemetry(
            plan=plan, block=block, run_attempt_id=run_attempt_id,
            startup_attempt_id=startup_attempt_id, block_attempt=block_attempt,
            allocation=allocation, capture=capture, specs=specs, native=native,
            max_system_sampling_gap_ns=2_500_000_000,
            native_clock_domain=context.clock_domain,
        )

    watchdog_sha256 = hashlib.sha256(entrypoint.read_bytes()).hexdigest()
    core = _core_provider(
        persist_owned=lambda owned: holder["provider"].persist(owned)
    )
    try:
        provider = _PreCreateGuardedProvider(
            core, context=context, state_directory=state_directory,
            permit_path=permit_path, authority_path=authority_path,
            entrypoint=entrypoint, library_path=library_path,
            restart_entrypoint=restart_entrypoint, adapter_source=adapter_source,
        )
        holder["provider"] = provider
        return {
            "provider": provider,
            "guard": guard,
            "runtime_factory": runtime_factory,
            "cell_factory": cell_factory,
            "telemetry_factory": telemetry_factory,
            "primary_watchdog_sha256": watchdog_sha256,
            "secondary_watchdog_sha256": watchdog_sha256,
            "monitor_poll_seconds": 1.0,
        }
    except BaseException:
        try:
            core.transport.close()
        except BaseException:
            pass
        raise
