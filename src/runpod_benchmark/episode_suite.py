"""Bounded endpoint rehearsals for Inference Lab Episodes 1–16.

These packs reuse the local quick-test runner. They never provision provider
resources and are explicitly not canonical episode evidence.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import threading
from collections.abc import Callable, Mapping
from typing import Any

from .playground import MAX_CONCURRENCY, MAX_REPETITIONS, PlaygroundValidationError, canonical_sha256, run_config, without_raw_text
from .metrics import summarize_distribution, unavailable_metric

ROOT = pathlib.Path(__file__).resolve().parents[2]
REGISTRY = json.loads((ROOT / "dashboard/src/data/episode-tests.v1.json").read_text(encoding="utf-8"))
PACKS = {item["episode"]: item for item in REGISTRY["episodes"]}
SCHEMA_VERSION = "inference-lab.episode-rehearsal.v1"
RESULT_SCHEMA_VERSION = "inference-lab.episode-rehearsal-result.v1"
_KEYS = {
    "schema_version", "episode", "profile_ids", "suite_repetitions", "repetitions", "batch_size",
    "context_tokens", "sequence_tokens", "request_timeout_seconds",
}


class _GpuSampler:
    """Opt-in bridge-host sampler for profiles explicitly bound to local GPUs."""

    def __init__(self) -> None:
        self.stop = threading.Event()
        self.utilization: list[float] = []
        self.memory_used: list[float] = []
        self.failure: str | None = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self.stop.is_set():
            try:
                completed = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5, check=True,
                )
                for line in completed.stdout.splitlines():
                    fields = [item.strip() for item in line.split(",")]
                    if len(fields) == 2:
                        self.utilization.append(float(fields[0]))
                        self.memory_used.append(float(fields[1]))
            except (FileNotFoundError, subprocess.SubprocessError, ValueError) as exc:
                self.failure = f"local nvidia-smi sampling failed: {type(exc).__name__}"
                return
            self.stop.wait(1.0)

    def start(self) -> None:
        self.thread.start()

    def finish(self) -> dict[str, Any]:
        self.stop.set()
        self.thread.join(timeout=6)
        reason = self.failure or "no nvidia-smi samples were observed"
        return {
            "scope": "bridge_host_all_visible_gpus_not_lane_attributable",
            "gpu_utilization_percent": summarize_distribution("gpu_utilization_percent", "percent", "local_nvidia_smi", self.utilization) if self.utilization else unavailable_metric("gpu_utilization_percent", "percent", "local_nvidia_smi", reason),
            "gpu_memory_used_mib": summarize_distribution("gpu_memory_used_mib", "MiB", "local_nvidia_smi", self.memory_used) if self.memory_used else unavailable_metric("gpu_memory_used_mib", "MiB", "local_nvidia_smi", reason),
        }


def public_registry() -> dict[str, Any]:
    return json.loads(json.dumps(REGISTRY))


def validate_episode_run(raw: Mapping[str, Any], profiles: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != _KEYS:
        raise PlaygroundValidationError("episode run has missing or unknown fields")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise PlaygroundValidationError(f"schema_version must be {SCHEMA_VERSION}")
    episode = raw.get("episode")
    if isinstance(episode, bool) or not isinstance(episode, int) or episode not in PACKS:
        raise PlaygroundValidationError("episode must be an integer from 1 through 16")
    profile_ids = raw.get("profile_ids")
    if not isinstance(profile_ids, list) or not 1 <= len(profile_ids) <= 2 or len(profile_ids) != len(set(profile_ids)):
        raise PlaygroundValidationError("profile_ids must contain one or two unique profiles")
    if any(not isinstance(item, str) or not item for item in profile_ids):
        raise PlaygroundValidationError("profile_ids are invalid")
    if profiles is not None and any(item not in profiles for item in profile_ids):
        raise PlaygroundValidationError("episode run references an unknown endpoint profile")
    repetitions = raw.get("repetitions")
    suite_repetitions = raw.get("suite_repetitions")
    batch_size = raw.get("batch_size")
    context_tokens = raw.get("context_tokens")
    sequence_tokens = raw.get("sequence_tokens")
    timeout = raw.get("request_timeout_seconds")
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or not 1 <= repetitions <= min(5, MAX_REPETITIONS):
        raise PlaygroundValidationError("repetitions must be between 1 and 5")
    if isinstance(suite_repetitions, bool) or not isinstance(suite_repetitions, int) or not 1 <= suite_repetitions <= 10:
        raise PlaygroundValidationError("suite_repetitions must be between 1 and 10")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= MAX_CONCURRENCY:
        raise PlaygroundValidationError(f"batch_size must be between 1 and {MAX_CONCURRENCY}")
    if isinstance(context_tokens, bool) or not isinstance(context_tokens, int) or not 1 <= context_tokens <= 1_000_000:
        raise PlaygroundValidationError("context_tokens must be between 1 and 1000000")
    if isinstance(sequence_tokens, bool) or not isinstance(sequence_tokens, int) or not 1 <= sequence_tokens <= 4096:
        raise PlaygroundValidationError("sequence_tokens must be between 1 and 4096")
    if profiles is not None:
        for profile_id in profile_ids:
            capacity = profiles[profile_id].get("context_length")
            if isinstance(capacity, int) and context_tokens + sequence_tokens > capacity:
                raise PlaygroundValidationError(f"requested context plus sequence exceeds profile {profile_id} context_length")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 600:
        raise PlaygroundValidationError("request_timeout_seconds must be between 1 and 600")
    return {
        "schema_version": SCHEMA_VERSION, "episode": episode, "profile_ids": list(profile_ids),
        "suite_repetitions": suite_repetitions, "repetitions": repetitions, "batch_size": batch_size, "context_tokens": context_tokens,
        "sequence_tokens": sequence_tokens, "request_timeout_seconds": float(timeout),
    }


def compile_cells(config: Mapping[str, Any], profiles: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    checked = validate_episode_run(config, profiles)
    pack = PACKS[checked["episode"]]
    lanes = [{"id": f"lane-{index + 1}", "profile_id": profile_id, "label": profiles[profile_id]["label"]} for index, profile_id in enumerate(checked["profile_ids"])]
    return [{
        "cell_id": cell["id"], "cell_label": cell["label"],
        "quick_test_config": {
            "schema_version": "episode1.quick-test.v1", "mode": "single" if len(lanes) == 1 else "compare",
            "prompt": {"system": "Follow the requested output contract exactly. Do not invent measurements.", "user": cell["prompt"]},
            "lanes": lanes, "sampling": {"maximum_output_tokens": checked["sequence_tokens"], "temperature": 0.0, "top_p": 1.0},
            "request_timeout_seconds": checked["request_timeout_seconds"], "repetitions": checked["repetitions"], "concurrency": checked["batch_size"],
        },
    } for cell in pack["cells"]]


def run_episode(
    raw_config: Mapping[str, Any], profiles: Mapping[str, Mapping[str, Any]], *,
    emit: Callable[[Mapping[str, Any]], None] = lambda _event: None,
    cancel_event: threading.Event | None = None,
    stream: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    config = validate_episode_run(raw_config, profiles)
    pack = PACKS[config["episode"]]
    cancellation = cancel_event or threading.Event()
    digest = canonical_sha256(config)
    cells = []
    selected = [profiles[profile_id] for profile_id in config["profile_ids"]]
    telemetry_enabled = any(profile.get("gpu_telemetry") == "local_nvidia_smi" for profile in selected)
    gpu_sampler = _GpuSampler() if telemetry_enabled else None
    telemetry: dict[str, Any] | None = None
    try:
        if gpu_sampler:
            gpu_sampler.start()
        emit({"type": "episode", "state": "preparing", "episode": config["episode"], "config_sha256": digest, "suite_total": config["suite_repetitions"]})
        compiled_cells = compile_cells(config, profiles)
        for suite_round in range(1, config["suite_repetitions"] + 1):
            if cancellation.is_set():
                break
            emit({"type": "suite", "state": "running", "suite_round": suite_round, "suite_total": config["suite_repetitions"]})
            for index, compiled in enumerate(compiled_cells, start=1):
                if cancellation.is_set():
                    break
                emit({"type": "cell", "state": "running", "suite_round": suite_round, "suite_total": config["suite_repetitions"], "cell_id": compiled["cell_id"], "cell_label": compiled["cell_label"], "index": index, "total": len(pack["cells"])})
                def child_event(event: Mapping[str, Any]) -> None:
                    if event.get("type") != "complete":
                        emit({**event, "suite_round": suite_round, "suite_total": config["suite_repetitions"], "cell_id": compiled["cell_id"], "cell_label": compiled["cell_label"]})
                kwargs = {"emit": child_event, "cancel_event": cancellation}
                if stream is not None:
                    kwargs["stream"] = stream
                result = run_config(compiled["quick_test_config"], profiles, **kwargs)
                safe = without_raw_text(result)
                cells.append({"suite_round": suite_round, "cell_id": compiled["cell_id"], "cell_label": compiled["cell_label"], "result": safe})
                emit({"type": "cell", "state": "complete", "suite_round": suite_round, "suite_total": config["suite_repetitions"], "cell_id": compiled["cell_id"], "cell_label": compiled["cell_label"], "index": index, "total": len(pack["cells"]), "result": safe})
            emit({"type": "suite", "state": "complete", "suite_round": suite_round, "suite_total": config["suite_repetitions"]})
    finally:
        if gpu_sampler:
            telemetry = gpu_sampler.finish()
    telemetry = telemetry or {
        "scope": "unavailable",
        "gpu_utilization_percent": unavailable_metric("gpu_utilization_percent", "percent", "endpoint_external", "selected endpoint profiles do not declare gpu_telemetry=local_nvidia_smi; OpenAI-compatible responses do not expose GPU utilization"),
        "gpu_memory_used_mib": unavailable_metric("gpu_memory_used_mib", "MiB", "endpoint_external", "selected endpoint profiles do not declare gpu_telemetry=local_nvidia_smi"),
    }
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "classification": REGISTRY["classification"],
        "episode_numbering_version": REGISTRY["episodeNumberingVersion"],
        "episode": config["episode"], "title": pack["title"], "track": pack["track"],
        "previous_episode": pack.get("previousEpisode"),
        "objective": pack["objective"], "limitation": pack["limitation"],
        "config_sha256": digest, "cancelled": cancellation.is_set(), "cells": cells,
        "effective_config": config,
        "endpoint_declarations": [{key: profile.get(key) for key in ("id", "runtime_id", "model", "context_length", "gpu_type", "gpu_count", "node_count", "parallelism", "runtime_controls", "gpu_telemetry")} for profile in selected],
        "gpu_telemetry": telemetry,
        "measurement_notes": {
            "context_tokens": "declared workload target; exact prompt tokens remain unavailable unless the endpoint reports matching usage",
            "sequence_tokens": "maximum output tokens sent to the endpoint",
            "itl": "client inter-chunk latency is captured; it is not labeled token-level ITL because SSE chunks need not map one-to-one to tokens",
            "runtime_controls_and_parallelism": "profile declarations describe the already-running endpoint; the rehearsal does not mutate server configuration",
            "suite_repetitions": "the complete ordered cell pack is repeated; each stored cell result is tagged with suite_round",
        },
    }
    emit({"type": "complete", "result": result})
    return result
