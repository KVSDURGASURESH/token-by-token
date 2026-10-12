#!/usr/bin/env python3
"""Validate the public recommended profile without contacting a provider."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


EXPECTED = {
    "vllm": ("0.29.0", "vllm/vllm-openai:v0.29.0"),
    "sglang": ("0.5.20", "lmsysorg/sglang:v0.5.20"),
}


def validate(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("status") != "recommended_new_run_not_historical_provenance":
        raise ValueError("profile must distinguish recommendations from historical provenance")
    model = data.get("model", {})
    expected_model = {
        "repository": "Qwen/Qwen2.5-32B-Instruct",
        "revision": "5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd",
        "dtype": "bfloat16",
        "max_model_len": 16384,
    }
    if model != expected_model:
        raise ValueError("model contract drift")
    if data.get("client") != {"python": "3.12", "transformers": "5.17.0"}:
        raise ValueError("client dependency contract drift")
    runtimes = data.get("runtimes")
    if not isinstance(runtimes, list) or {item.get("id") for item in runtimes} != set(EXPECTED):
        raise ValueError("runtime set drift")
    for item in runtimes:
        version, tag = EXPECTED[item["id"]]
        if item.get("version") != version or item.get("recommended_image_tag") != tag:
            raise ValueError(f"{item['id']} version or image tag drift")
        if item.get("image_digest") is not None:
            raise ValueError("public recommendation must not pretend an unverified digest is bound")
        if item.get("prefix_cache") is not True or item.get("chunked_prefill") is not True:
            raise ValueError(f"{item['id']} cache/prefill contract drift")
    return {"valid": True, "provider_calls": 0, "execution_ready": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.profile), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
