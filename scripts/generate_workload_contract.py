#!/usr/bin/env python3
"""Print runner-enforced prompt and tokenizer hashes for private plan authoring."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json

from run_live_openai_benchmark import parse_matrix, workload_contract


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--matrix", required=True)
    parser.add_argument("--request-count", type=int, required=True)
    parser.add_argument("--repetitions", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--transformers-version", required=True)
    args = parser.parse_args()
    installed = importlib.metadata.version("transformers")
    if installed != args.transformers_version:
        raise RuntimeError(
            f"installed Transformers {installed} does not match {args.transformers_version}"
        )
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=args.model_revision)
    template = tokenizer.get_chat_template()
    if not isinstance(template, str) or not template:
        raise RuntimeError("loaded tokenizer has no concrete chat template")
    contract = workload_contract(
        model=args.model,
        model_revision=args.model_revision,
        matrix=parse_matrix(args.matrix),
        request_count=args.request_count,
        repetitions=args.repetitions,
        seed=args.seed,
    )
    contract["model"] = {
        "tokenizer_repository": args.model,
        "tokenizer_revision": args.model_revision,
        "chat_template": {
            "revision": args.model_revision,
            "sha256": hashlib.sha256(template.encode("utf-8")).hexdigest(),
        },
    }
    print(json.dumps(contract, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
