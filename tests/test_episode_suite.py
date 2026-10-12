from __future__ import annotations

import pytest

from runpod_benchmark.episode_suite import PACKS, compile_cells, run_episode, validate_episode_run
from runpod_benchmark.playground import PlaygroundValidationError, validate_profiles


def profiles():
    return validate_profiles([{
        "id": "local", "label": "Local vLLM", "url": "http://127.0.0.1:8000/v1/chat/completions",
        "runtime_id": "vllm", "model": "fixture", "context_length": 8192,
        "supported_optional_fields": [], "gpu_type": "H100", "gpu_count": 1, "node_count": 1,
        "parallelism": {"dp": 1, "tp": 1, "pp": 1, "ep": 1},
        "runtime_controls": {"prompt_caching": "enabled", "chunked_prefill": "enabled", "continuous_batching": "enabled"},
        "gpu_telemetry": "unavailable",
    }])


def config(**overrides):
    value = {
        "schema_version": "inference-lab.episode-rehearsal.v1", "episode": 1,
        "profile_ids": ["local"], "suite_repetitions": 2, "repetitions": 1,
        "batch_size": 1, "context_tokens": 1024, "sequence_tokens": 64,
        "request_timeout_seconds": 30,
    }
    value.update(overrides)
    return value


def test_registry_contains_runnable_packs_for_every_planned_episode():
    assert sorted(PACKS) == list(range(1, 17))
    assert PACKS[3]["title"] == "Prefix reuse"
    assert PACKS[10]["title"] == "Slurm and Kubernetes"
    assert PACKS[11]["title"] == "Model internals"
    assert PACKS[15]["title"] == "Saturation, SLO and cost"
    for episode in PACKS:
        cells = compile_cells(config(episode=episode, suite_repetitions=1), profiles())
        assert cells
        assert all(cell["quick_test_config"]["sampling"]["maximum_output_tokens"] == 64 for cell in cells)


def test_suite_repetition_and_capacity_are_bounded():
    assert validate_episode_run(config(suite_repetitions=10), profiles())["suite_repetitions"] == 10
    with pytest.raises(PlaygroundValidationError, match="suite_repetitions"):
        validate_episode_run(config(suite_repetitions=11), profiles())
    with pytest.raises(PlaygroundValidationError, match="exceeds profile"):
        validate_episode_run(config(context_tokens=8180, sequence_tokens=64), profiles())


def test_complete_pack_repeats_are_round_tagged_and_sanitized():
    def fake_stream(request):
        request["content_callback"]("one ", 100)
        request["content_callback"]("two", 200)
        return {"text": "private response", "ttft_ms": 5.0, "e2e_ms": 15.0,
                "content_span_ms": 10.0, "inter_chunk_ms": [10.0], "input_tokens": 4,
                "output_tokens": 2, "content_event_count": 2, "stop_reason": "stop"}

    result = run_episode(config(), profiles(), stream=fake_stream)
    expected = len(PACKS[1]["cells"]) * 2
    assert len(result["cells"]) == expected
    assert {cell["suite_round"] for cell in result["cells"]} == {1, 2}
    assert all("private response" not in str(cell) for cell in result["cells"])
    assert result["effective_config"]["suite_repetitions"] == 2
    assert result["episode_numbering_version"] == "episode-catalog.v2"
    assert result["previous_episode"] == 1
    assert not result["gpu_telemetry"]["gpu_utilization_percent"]["available"]
