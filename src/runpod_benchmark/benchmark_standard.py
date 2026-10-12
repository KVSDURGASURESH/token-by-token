"""Pinned, zero-cost preparation for the Episode 1 standard benchmarks.

The functions here do not contact a model server or create provider resources.
They verify immutable input bytes, reproduce SGLang's ShareGPT selection,
exercise the GSM8K strict-match metric, and assemble commands for a separately
authorized live run.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path
from typing import Any


class BenchmarkStandardError(ValueError):
    """Raised when a benchmark artifact or frozen setting does not match."""


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_artifact(path: Path, *, sha256: str, size_bytes: int) -> None:
    if not path.is_file():
        raise BenchmarkStandardError(f"missing artifact: {path}")
    observed_size = path.stat().st_size
    if observed_size != size_bytes:
        raise BenchmarkStandardError(
            f"artifact size mismatch for {path.name}: {observed_size} != {size_bytes}"
        )
    observed_sha256 = sha256_file(path)
    if observed_sha256 != sha256:
        raise BenchmarkStandardError(
            f"artifact SHA-256 mismatch for {path.name}: {observed_sha256} != {sha256}"
        )


def load_standard_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != "episode1.benchmark-standard.v1":
        raise BenchmarkStandardError("unsupported benchmark-standard manifest")
    return value


def select_sharegpt_requests(
    dataset_path: Path,
    tokenizer: Any,
    *,
    seed: int,
    request_count: int,
    output_tokens: int,
    context_length: int,
    apply_chat_template: bool,
) -> dict[str, Any]:
    """Reproduce SGLang 0.5.20's sampler without retaining prompt text."""

    with dataset_path.open(encoding="utf-8") as handle:
        raw_dataset = json.load(handle)
    if not isinstance(raw_dataset, list):
        raise BenchmarkStandardError("ShareGPT artifact must contain a JSON array")

    candidates: list[tuple[int, str, str]] = []
    for index, row in enumerate(raw_dataset):
        if not isinstance(row, dict):
            continue
        conversation = row.get("conversations", row.get("conversation", []))
        if not isinstance(conversation, list) or len(conversation) < 2:
            continue
        try:
            prompt = conversation[0]["value"]
            completion = conversation[1]["value"]
        except (KeyError, TypeError):
            continue
        if isinstance(prompt, str) and isinstance(completion, str):
            candidates.append((index, prompt, completion))

    random.Random(seed).shuffle(candidates)
    selected: list[dict[str, Any]] = []
    for source_index, raw_prompt, completion in candidates:
        prompt = raw_prompt
        if apply_chat_template:
            prompt = tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt}],
                add_generation_prompt=True,
                tokenize=False,
                return_dict=False,
            )
            if tokenizer.bos_token:
                prompt = prompt.replace(tokenizer.bos_token, "")

        prompt_length = len(tokenizer.encode(prompt))
        completion_length = len(tokenizer.encode(completion))
        if prompt_length < 2 or output_tokens < 2:
            continue
        if prompt_length + output_tokens > context_length:
            continue
        selected.append(
            {
                "source_index": source_index,
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "completion_sha256": hashlib.sha256(completion.encode("utf-8")).hexdigest(),
                "prompt_tokens": prompt_length,
                "source_completion_tokens": completion_length,
                "requested_output_tokens": output_tokens,
            }
        )
        if len(selected) == request_count:
            break

    if len(selected) != request_count:
        raise BenchmarkStandardError(
            f"ShareGPT yielded {len(selected)} eligible rows; expected {request_count}"
        )
    body: dict[str, Any] = {
        "schema_version": "episode1.sharegpt-selection.v1",
        "dataset_sha256": sha256_file(dataset_path),
        "seed": seed,
        "request_count": request_count,
        "output_tokens": output_tokens,
        "context_length": context_length,
        "apply_chat_template": apply_chat_template,
        "total_prompt_tokens": sum(row["prompt_tokens"] for row in selected),
        "total_requested_output_tokens": request_count * output_tokens,
        "requests": selected,
    }
    body["selection_sha256"] = hashlib.sha256(canonical_json(body).encode()).hexdigest()
    return body


_STRICT_GSM8K = re.compile(r"#### (\-?[0-9\.\,]+)")


def gsm8k_strict_extract(response: str) -> str:
    match = _STRICT_GSM8K.search(response)
    return match.group(1) if match else "[invalid]"


def _gsm8k_normalize(value: str) -> str:
    value = re.sub(r"(?s).*#### ", "", value)
    value = value.replace(",", "").replace("$", "")
    value = re.sub(r"\.$", "", value)
    return value.casefold()


def gsm8k_strict_match(response: str, target: str) -> bool:
    """Match lm-evaluation-harness v0.4.13's GSM8K strict-match path."""

    return _gsm8k_normalize(gsm8k_strict_extract(response)) == _gsm8k_normalize(target)


def exercise_gsm8k(test_path: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    with test_path.open(encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            try:
                row = json.loads(line)
                question, answer = row["question"], row["answer"]
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise BenchmarkStandardError(f"invalid GSM8K row {index}") from exc
            if not isinstance(question, str) or not isinstance(answer, str):
                raise BenchmarkStandardError(f"invalid GSM8K fields at row {index}")
            rows.append(
                {
                    "index": index,
                    "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
                    "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
                    "gold_self_match": gsm8k_strict_match(answer, answer),
                }
            )
    matches = sum(row["gold_self_match"] for row in rows)
    return {
        "schema_version": "episode1.gsm8k-fixture-exercise.v1",
        "dataset_sha256": sha256_file(test_path),
        "sample_count": len(rows),
        "gold_self_matches": matches,
        "known_mismatch_rejected": not gsm8k_strict_match("#### 0", "#### 1"),
        "row_manifest_sha256": hashlib.sha256(canonical_json(rows).encode()).hexdigest(),
    }


def serving_command(
    *,
    runtime: str,
    base_url: str,
    model: str,
    tokenizer_path: Path,
    dataset_path: Path,
    output_path: Path,
    concurrency: int,
) -> list[str]:
    backend_by_runtime = {"vllm-0.29.0": "vllm", "sglang-0.5.20": "sglang-oai"}
    try:
        backend = backend_by_runtime[runtime]
    except KeyError as exc:
        raise BenchmarkStandardError(f"unsupported runtime: {runtime}") from exc
    if concurrency not in {1, 4}:
        raise BenchmarkStandardError("serving concurrency must be 1 or 4")
    return [
        "python", "-m", "sglang.bench_serving",
        "--backend", backend,
        "--base-url", base_url,
        "--model", model,
        "--tokenizer", str(tokenizer_path),
        "--dataset-name", "sharegpt",
        "--dataset-path", str(dataset_path),
        "--num-prompts", "32",
        "--sharegpt-output-len", "128",
        "--sharegpt-context-len", "4096",
        "--request-rate", "inf",
        "--max-concurrency", str(concurrency),
        "--warmup-requests", "4",
        "--seed", "20260923",
        "--temperature", "0",
        "--top-p", "1",
        "--apply-chat-template",
        "--output-details",
        "--output-file", str(output_path),
    ]


def gsm8k_command(
    *, base_url: str, model: str, output_path: Path, executable: str = "lm-eval"
) -> list[str]:
    endpoint = base_url.rstrip("/") + "/v1/completions"
    return [
        executable, "run",
        "--model", "local-completions",
        "--model_args",
        f"base_url={endpoint}",
        f"model={model}",
        "tokenizer_backend=none",
        "tokenized_requests=False",
        "num_concurrent=4",
        "max_retries=1",
        "--tasks", "gsm8k",
        "--num_fewshot", "5",
        "--batch_size", "1",
        "--seed", "20260923",
        "--log_samples",
        "--output_path", str(output_path),
    ]
