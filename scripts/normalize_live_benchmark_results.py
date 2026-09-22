#!/usr/bin/env python3
"""Normalize runtime-neutral live benchmark artifacts for charts and dashboard use."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


RUNTIME_LABELS = {
    "vllm": "vLLM",
    "sglang": "SGLang",
    "tgi": "TGI",
    "tensorrt_llm": "TensorRT-LLM",
    "transformers": "Transformers",
}
METRIC_MAP = {
    "client_ttft_ms": "ttft_ms",
    "client_tpot_ms": "tpot_ms",
    "client_itl_ms": "client_inter_chunk_ms",
    "client_e2e_ms": "e2e_ms",
}


def _distribution(summary: Mapping[str, Any], source_name: str) -> dict[str, Any]:
    metric = summary.get("metrics", {}).get(source_name, {})
    if not isinstance(metric, Mapping):
        raise ValueError(f"metric {source_name} is not an object")
    statistics = metric.get("statistics") if isinstance(metric, Mapping) else None
    available = metric.get("available") is True
    envelope: dict[str, Any] = {
        "count": metric.get("count"),
        "percentile_method": metric.get("percentile_method"),
        "source": metric.get("source"),
        "available": available,
        "unavailable_reason": metric.get("unavailable_reason"),
        "warnings": list(metric.get("warnings", [])),
    }
    if available:
        if not isinstance(statistics, Mapping):
            raise ValueError(f"available metric {source_name} has no statistics")
        envelope.update(
            {name: float(statistics[name]) for name in ("p50", "p95", "p99")}
        )
    elif statistics is not None:
        raise ValueError(f"unavailable metric {source_name} must not have statistics")
    return envelope


def _goodput(summary: Mapping[str, Any]) -> dict[str, Any]:
    rate = summary.get("goodput_output_tokens_per_second")
    envelope: dict[str, Any] = {
        "slo_contract": dict(summary.get("slo_contract", {})),
        "available": rate is not None,
        "unavailable_reason": None,
    }
    if rate is not None:
        envelope.update(
            {
                "qualifying_requests": int(summary.get("goodput_requests")),
                "output_tokens": int(summary.get("goodput_output_tokens")),
                "tokens_per_second": float(rate),
            }
        )
    else:
        envelope["unavailable_reason"] = (
            summary.get("metrics", {})
            .get("goodput_tokens_per_second", {})
            .get("unavailable_reason")
            or "goodput evidence unavailable"
        )
    return envelope


def normalize_artifacts(
    artifacts: list[Mapping[str, Any]],
    *,
    gpu: str,
    precision: str,
    runtime_disclosures: Mapping[str, str] | None = None,
    study_facts: Mapping[str, list[str]] | None = None,
) -> dict[str, Any]:
    if not artifacts:
        raise ValueError("at least one artifact is required")
    identities = {
        (artifact.get("model"), artifact.get("model_revision")) for artifact in artifacts
    }
    if len(identities) != 1:
        raise ValueError("all artifacts must use the same model and revision")
    model, model_revision = next(iter(identities))
    if not isinstance(model, str) or not isinstance(model_revision, str):
        raise ValueError("model identity is incomplete")
    cells: list[dict[str, Any]] = []
    for artifact in artifacts:
        if artifact.get("schema_version") != 1:
            raise ValueError("artifact schema_version must be 1")
        runtime_id = artifact.get("runtime")
        if not isinstance(runtime_id, str):
            raise ValueError("runtime is required")
        for cell in artifact.get("cells", []):
            summary = cell.get("summary", {})
            prompt = cell.get("prompt", {})
            input_min = int(prompt.get("actual_input_tokens_min"))
            input_max = int(prompt.get("actual_input_tokens_max"))
            input_label = str(input_min) if input_min == input_max else f"{input_min}-{input_max}"
            normalized = {
                "cell_id": cell.get("cell_id"),
                "repetition": cell.get("repetition"),
                "runtime": RUNTIME_LABELS.get(runtime_id, runtime_id),
                "runtime_id": runtime_id,
                "profile": f"{input_label}tok-c{int(cell.get('concurrency'))}",
                "input_tokens_min": input_min,
                "input_tokens_max": input_max,
                "concurrency": int(cell.get("concurrency")),
                "successful_requests": int(summary.get("successful_requests")),
                "failed_requests": int(summary.get("failed_requests")),
                "successful_output_tokens": summary.get("successful_output_tokens"),
                "output_tokens_per_second": summary.get(
                    "throughput_output_tokens_per_second"
                ),
                "goodput": _goodput(summary),
            }
            for target_name, source_name in METRIC_MAP.items():
                normalized[target_name] = _distribution(summary, source_name)
            cells.append(normalized)
    cells.sort(
        key=lambda cell: (
            cell["input_tokens_min"],
            cell["input_tokens_max"],
            cell["concurrency"],
            cell["runtime"],
        )
    )
    study = {
        "schema_version": 1,
        "classification": "exploratory_noncanonical",
        "model": model,
        "model_revision": model_revision,
        "gpu": gpu,
        "precision": precision,
        "cells": cells,
        "study_facts": {
            "compatibility": [],
            "exclusions": [],
            "preflight": [],
            "future_work": [],
        },
    }
    if runtime_disclosures:
        study["study_facts"]["compatibility"] = [
            f"{runtime}: {disclosure}"
            for runtime, disclosure in runtime_disclosures.items()
        ]
    if study_facts is not None:
        expected = {"compatibility", "exclusions", "preflight", "future_work"}
        if set(study_facts) != expected:
            raise ValueError("study_facts must contain exactly the four publication fact fields")
        for field, values in study_facts.items():
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value for value in values
            ):
                raise ValueError(f"study_facts.{field} must contain non-empty strings")
            study["study_facts"][field].extend(values)
    return study


def parse_runtime_disclosures(values: list[str]) -> dict[str, str]:
    disclosures: dict[str, str] = {}
    for value in values:
        runtime, separator, disclosure = value.partition("=")
        if not separator or not runtime.strip() or not disclosure.strip():
            raise ValueError("runtime disclosures must use RUNTIME=TEXT")
        disclosures[runtime.strip()] = disclosure.strip()
    return disclosures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", action="append", required=True, type=Path)
    parser.add_argument("--gpu", required=True)
    parser.add_argument("--precision", required=True)
    parser.add_argument(
        "--runtime-disclosure",
        action="append",
        default=[],
        metavar="RUNTIME=TEXT",
    )
    for fact in ("compatibility", "exclusions", "preflight", "future-work"):
        parser.add_argument(f"--{fact}", action="append", default=[])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    artifacts = [json.loads(path.read_text(encoding="utf-8")) for path in args.artifact]
    study = normalize_artifacts(
        artifacts,
        gpu=args.gpu,
        precision=args.precision,
        runtime_disclosures=parse_runtime_disclosures(args.runtime_disclosure),
        study_facts={
            "compatibility": args.compatibility,
            "exclusions": args.exclusions,
            "preflight": args.preflight,
            "future_work": args.future_work,
        },
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(study, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
