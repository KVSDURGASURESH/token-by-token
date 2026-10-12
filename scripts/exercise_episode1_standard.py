#!/usr/bin/env python3
"""Verify and locally exercise Episode 1's pinned benchmark artifacts."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from runpod_benchmark.benchmark_standard import (
    exercise_gsm8k,
    load_standard_manifest,
    select_sharegpt_requests,
    sha256_file,
    verify_artifact,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--sharegpt", type=Path, required=True)
    parser.add_argument("--gsm8k-test", type=Path, required=True)
    parser.add_argument("--gsm8k-train", type=Path, required=True)
    parser.add_argument("--gsm8k-task-config", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = load_standard_manifest(args.manifest)
    serving = manifest["serving"]
    quality = manifest["quality"]
    adapter = manifest["adapter"]
    repository_root = args.manifest.resolve().parents[2]
    verify_artifact(
        repository_root / adapter["path"],
        sha256=adapter["sha256"],
        size_bytes=adapter["size_bytes"],
    )
    for path, record in (
        (args.sharegpt, serving["dataset"]),
        (args.gsm8k_test, quality["test_dataset"]),
        (args.gsm8k_train, quality["train_dataset"]),
        (args.gsm8k_task_config, quality["task_config"]),
    ):
        verify_artifact(path, sha256=record["sha256"], size_bytes=record["size_bytes"])

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        args.tokenizer, local_files_only=True, trust_remote_code=False
    )
    protocol = serving["protocol"]
    selection = select_sharegpt_requests(
        args.sharegpt,
        tokenizer,
        seed=protocol["seed"],
        request_count=protocol["request_count"],
        output_tokens=protocol["output_tokens"],
        context_length=protocol["context_length"],
        apply_chat_template=protocol["apply_chat_template"],
    )
    if selection["selection_sha256"] != protocol["expected_selection_sha256"]:
        raise ValueError("ShareGPT selection does not match the frozen protocol")
    gsm8k = exercise_gsm8k(args.gsm8k_test)
    if gsm8k["sample_count"] != quality["protocol"]["sample_count"]:
        raise ValueError("GSM8K sample count does not match the frozen protocol")
    if gsm8k["gold_self_matches"] != gsm8k["sample_count"]:
        raise ValueError("GSM8K strict-match fixture exercise failed")
    if not gsm8k["known_mismatch_rejected"]:
        raise ValueError("GSM8K negative control failed")

    evidence = {
        "schema_version": "episode1.benchmark-standard-exercise.v1",
        "manifest_sha256": sha256_file(args.manifest),
        "sharegpt_selection": selection,
        "gsm8k": gsm8k,
        "scope": "local-artifact-and-adapter-exercise; no model inference; no provider resources",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.chmod(args.output, 0o600)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sharegpt_selection_sha256": selection["selection_sha256"],
                "sharegpt_requests": selection["request_count"],
                "gsm8k_samples": gsm8k["sample_count"],
                "gsm8k_fixture_matches": gsm8k["gold_self_matches"],
                "provider_resources_created": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
