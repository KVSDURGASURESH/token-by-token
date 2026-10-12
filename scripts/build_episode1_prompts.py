#!/usr/bin/env python3
"""Build and verify Episode 1 prompts from an offline pinned tokenizer directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from runpod_benchmark.episode1 import MODEL_REVISION, authored_quality_corpus  # noqa: E402

ASSET_HASHES = {
    "config.json": "9c6772f138ef9e5b3d1c18f2c87e451bbc01f5f1a4eabb36f9bf4f53829b903e",
    "tokenizer.json": "c0382117ea329cdf097041132f6d735924b697924d6f6fc3945713e96ce87539",
    "tokenizer_config.json": "5b5d4f65d0acd3b2d56a35b56d374a36cbc1c8fa5cf3b3febbbfabf22f359583",
    "vocab.json": "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910",
    "merges.txt": "599bab54075088774b1733fde865d5bd747cbcc7a547c5bc12610e874e26f5e3",
}
EXPECTED_ID_HASHES = {
    512: "22c030f9b84e937cb921ba79597ab2ac6ac73b93c9ee87c3d6de0d576ace2426",
    2048: "701f3d70021261d26c248b5247bc5f63408fbd4d305296fc98c43de435868a2b",
}
EXPECTED_CHAT_TEMPLATE_SHA256 = "cd8e9439f0570856fd70470bf8889ebd8b5d1107207f67a5efb46e342330527f"
PREFIX = "Extract a concise answer from this deterministic synthetic service note. Synthetic benchmark content:"


def _sha_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def build(tokenizer_directory: Path) -> dict[str, object]:
    try:
        import tokenizers
        import transformers
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise RuntimeError("install the explicit live extra before building prompts") from exc

    observed = {name: _sha_bytes(tokenizer_directory / name) for name in ASSET_HASHES}
    if observed != ASSET_HASHES:
        raise ValueError("tokenizer assets do not match the pinned revision hashes")
    tokenizer = AutoTokenizer.from_pretrained(
        tokenizer_directory, local_files_only=True, trust_remote_code=False
    )
    template = tokenizer.chat_template
    if not isinstance(template, str) or hashlib.sha256(template.encode()).hexdigest() != EXPECTED_CHAT_TEMPLATE_SHA256:
        raise ValueError("chat template differs from reviewed evidence")
    fixed = []
    for target in EXPECTED_ID_HASHES:
        content = PREFIX + " x" * (target - 44)
        messages = [{"role": "user", "content": content}]
        token_ids = tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True
        )
        if hasattr(token_ids, "input_ids"):
            token_ids = token_ids.input_ids
        if token_ids and isinstance(token_ids[0], list):
            token_ids = token_ids[0]
        if len(token_ids) != target or _canonical_sha(token_ids) != EXPECTED_ID_HASHES[target]:
            raise ValueError(f"rendered {target}-token prompt differs from reviewed evidence")
        fixed.append({
            "target_input_tokens": target,
            "messages": messages,
            "token_ids": token_ids,
            "token_ids_sha256": EXPECTED_ID_HASHES[target],
        })
    quality = []
    for task in authored_quality_corpus():
        messages = [{"role": "user", "content": task["note"]}]
        token_ids = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
        if hasattr(token_ids, "input_ids"):
            token_ids = token_ids.input_ids
        if token_ids and isinstance(token_ids[0], list):
            token_ids = token_ids[0]
        quality.append({
            "task_id": task["task_id"], "messages": messages, "gold_json": task["gold_json"],
            "input_token_count": len(token_ids), "token_ids": token_ids,
            "token_ids_sha256": _canonical_sha(token_ids),
        })
    return {
        "classification": "public_authored_synthetic",
        "model_revision": MODEL_REVISION,
        "tool_versions": {"transformers": transformers.__version__, "tokenizers": tokenizers.__version__},
        "asset_sha256": observed,
        "chat_template_sha256": EXPECTED_CHAT_TEMPLATE_SHA256,
        "fixed": fixed,
        "natural_quality": quality,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tokenizer-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = build(args.tokenizer_directory.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    os.chmod(args.output, 0o600)
    print(json.dumps({"provider_calls": 0, "verified_targets": [512, 2048], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
