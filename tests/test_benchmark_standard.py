from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from runpod_benchmark.benchmark_standard import (
    BenchmarkStandardError,
    exercise_gsm8k,
    gsm8k_command,
    gsm8k_strict_match,
    select_sharegpt_requests,
    serving_command,
    verify_artifact,
)


ROOT = Path(__file__).resolve().parents[1]


class FakeTokenizer:
    bos_token = "<bos>"

    def apply_chat_template(self, messages, **kwargs):
        del kwargs
        return f"<bos>user:{messages[0]['content']}\nassistant:"

    def encode(self, value):
        return value.split()


def test_artifact_verification_fails_closed(tmp_path: Path) -> None:
    artifact = tmp_path / "a.bin"
    artifact.write_bytes(b"known")
    verify_artifact(
        artifact, sha256=hashlib.sha256(b"known").hexdigest(), size_bytes=5
    )
    with pytest.raises(BenchmarkStandardError, match="size mismatch"):
        verify_artifact(artifact, sha256="0" * 64, size_bytes=4)
    with pytest.raises(BenchmarkStandardError, match="SHA-256 mismatch"):
        verify_artifact(artifact, sha256="0" * 64, size_bytes=5)


def test_sharegpt_selection_is_deterministic_and_text_free(tmp_path: Path) -> None:
    dataset = tmp_path / "sharegpt.json"
    rows = [
        {"conversations": [{"value": f"prompt words {index}"}, {"value": f"answer {index}"}]}
        for index in range(8)
    ]
    rows.append({"conversations": [{"value": "one turn"}]})
    dataset.write_text(json.dumps(rows), encoding="utf-8")
    kwargs = dict(
        seed=20260923,
        request_count=4,
        output_tokens=8,
        context_length=64,
        apply_chat_template=True,
    )
    first = select_sharegpt_requests(dataset, FakeTokenizer(), **kwargs)
    second = select_sharegpt_requests(dataset, FakeTokenizer(), **kwargs)
    assert first == second
    assert len(first["requests"]) == 4
    assert "prompt words" not in json.dumps(first)
    assert all(len(row["prompt_sha256"]) == 64 for row in first["requests"])


def test_gsm8k_strict_match_and_full_fixture_exercise(tmp_path: Path) -> None:
    assert gsm8k_strict_match("work\n#### 1,234.", "work\n#### $1,234")
    assert not gsm8k_strict_match("the answer is 1234", "#### 1234")
    path = tmp_path / "test.jsonl"
    path.write_text(
        json.dumps({"question": "1+1?", "answer": "reason\n#### 2"}) + "\n"
        + json.dumps({"question": "2+2?", "answer": "reason\n#### 4"}) + "\n",
        encoding="utf-8",
    )
    result = exercise_gsm8k(path)
    assert result["sample_count"] == 2
    assert result["gold_self_matches"] == 2
    assert result["known_mismatch_rejected"] is True


def test_commands_bind_common_endpoints_and_frozen_settings(tmp_path: Path) -> None:
    vllm = serving_command(
        runtime="vllm-0.29.0", base_url="http://127.0.0.1:8000",
        model="Qwen/Qwen3-32B", tokenizer_path=tmp_path / "tokenizer",
        dataset_path=tmp_path / "sharegpt.json", output_path=tmp_path / "out.jsonl",
        concurrency=4,
    )
    sglang = serving_command(
        runtime="sglang-0.5.20", base_url="http://127.0.0.1:8000",
        model="Qwen/Qwen3-32B", tokenizer_path=tmp_path / "tokenizer",
        dataset_path=tmp_path / "sharegpt.json", output_path=tmp_path / "out.jsonl",
        concurrency=4,
    )
    assert vllm[vllm.index("--backend") + 1] == "vllm"
    assert sglang[sglang.index("--backend") + 1] == "sglang-oai"
    assert "--apply-chat-template" in vllm
    assert vllm[vllm.index("--sharegpt-output-len") + 1] == "128"

    quality = gsm8k_command(
        base_url="http://127.0.0.1:8000/", model="Qwen/Qwen3-32B",
        output_path=tmp_path / "quality",
    )
    assert "base_url=http://127.0.0.1:8000/v1/completions" in quality
    assert quality[quality.index("--tasks") + 1] == "gsm8k"
    assert "--limit" not in quality


def test_manifest_binds_the_checked_in_adapter() -> None:
    manifest = json.loads(
        (ROOT / "fixtures/episode1/benchmark-standard.json").read_text(encoding="utf-8")
    )
    adapter = manifest["adapter"]
    adapter_path = ROOT / adapter["path"]
    assert adapter_path.stat().st_size == adapter["size_bytes"]
    assert hashlib.sha256(adapter_path.read_bytes()).hexdigest() == adapter["sha256"]
