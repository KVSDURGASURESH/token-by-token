"""Validation for the formal Episode 02 protocol and logical trace."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "episode2.protocol.v1"
TRACE_SCHEMA_VERSION = "episode2.trace.v1"
TITLE = "Equal-work runtime baseline"
CLASS_IDS = (
    "short",
    "long_prefill",
    "output_heavy",
    "structured",
    "code_reasoning",
    "tool_call",
    "conversation",
    "agent_chain",
)
HEX = re.compile(r"[0-9a-f]{64}\Z")
PROTOCOL_KEYS = {
    "schema_version", "episode", "title", "classification", "catalog_sha256",
    "campaign_id", "material", "mixture", "cells", "repetition_blocks", "seed",
    "order_policy", "warmup_reset", "quality", "metrics", "uncertainty",
    "safeguards", "tool_fixtures_sha256", "continuation_version", "exclusions",
}
CLASS_TURNS = dict(zip(CLASS_IDS, (1, 1, 1, 1, 1, 2, 2, 3)))
TRACE_KEYS = {"schema_version", "protocol_sha256", "seed", "mode", "blocks", "logical_sha256", "tool_fixtures_sha256"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError("finite JSON required") from exc


def document_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _immutable(value: object) -> bool:
    return isinstance(value, str) and (HEX.fullmatch(value) is not None or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None)


def loads_strict_json(payload: str | bytes) -> Any:
    """Decode JSON without losing duplicate fields or accepting nonfinite numbers."""
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result

    def invalid_constant(value: str) -> None:
        raise ValueError("nonfinite JSON number")

    value = json.loads(payload, object_pairs_hook=pairs, parse_constant=invalid_constant)
    canonical_bytes(value)
    return value


def _closed(value: Any, keys: set[str], name: str) -> None:
    require(isinstance(value, Mapping) and set(value) == keys, f"{name} fields are closed")


def _text(value: Any, name: str) -> None:
    require(isinstance(value, str) and 1 <= len(value) <= 512, f"invalid {name}")


def _integer(value: Any, minimum: int, maximum: int, name: str) -> None:
    require(type(value) is int and minimum <= value <= maximum, f"invalid {name}")


def _science(protocol: Mapping[str, Any]) -> None:
    order = protocol["order_policy"]
    _closed(order, {"engine", "treatment", "within_session"}, "order_policy")
    require(order == {"engine": "counterbalanced", "treatment": "paired", "within_session": "dependency_order"}, "invalid order policy")
    warm = protocol["warmup_reset"]
    _closed(warm, {"warmup_requests", "cache_reset_between_arms", "cold_separate"}, "warmup_reset")
    _integer(warm["warmup_requests"], 1, 1000, "warmup requests")
    require(type(warm["cache_reset_between_arms"]) is bool and warm["cold_separate"] is True, "invalid warmup/reset policy")
    quality = protocol["quality"]
    quality_keys = {"schema_validity", "semantic_contract", "equal_work"}
    require(isinstance(quality, Mapping) and quality_keys <= set(quality) <= quality_keys | {"output_length_tolerance_fraction"}, "quality fields are closed")
    require({k: quality[k] for k in quality_keys} == {"schema_validity": "required", "semantic_contract": "canonical", "equal_work": "required"}, "invalid quality contract")
    if "output_length_tolerance_fraction" in quality:
        value = quality["output_length_tolerance_fraction"]
        require(type(value) in (int, float) and 0 <= value <= 1, "invalid output length tolerance")
    metrics = protocol["metrics"]
    _closed(metrics, {"primary_tail", "companions", "p99_min_n"}, "metrics")
    require(metrics["primary_tail"] == "request_e2e_ms" and metrics["companions"] == ["ttft_ms", "tpot_ms", "workflow_e2e_ms"], "invalid metrics")
    _integer(metrics["p99_min_n"], 1000, 1000, "p99 minimum")
    uncertainty = protocol["uncertainty"]
    _closed(uncertainty, {"method", "confidence", "seed", "resamples", "minimum_blocks"}, "uncertainty")
    require(uncertainty["method"] == "paired_block_bootstrap" and uncertainty["confidence"] == 0.95, "uncertainty contract mismatch")
    _integer(uncertainty["seed"], 0, 2**32-1, "uncertainty seed")
    _integer(uncertainty["resamples"], 2000, 2000, "resamples")
    _integer(uncertainty["minimum_blocks"], 6, protocol["repetition_blocks"], "minimum paired blocks")
    safeguards = protocol["safeguards"]
    base = {"median_ceiling_ms", "error_rate_max", "quality_min", "cost_status", "resource_pressure"}
    numeric = {"e2e_slo_ms", "ttft_slo_ms", "tpot_slo_ms", "goodput_min_tokens_per_second", "admission_rate_min", "cost_max_usd", "resource_max"}
    require(isinstance(safeguards, Mapping) and base <= set(safeguards) <= base | numeric, "safeguards fields are closed")
    for key in ("e2e_slo_ms", "ttft_slo_ms", "tpot_slo_ms", "goodput_min_tokens_per_second"):
        if key in safeguards:
            value = safeguards[key]
            require(type(value) in (int, float) and 0 < value <= 3600000, f"invalid safeguard {key}")
    if "admission_rate_min" in safeguards:
        value = safeguards["admission_rate_min"]
        require(type(value) in (int, float) and 0 <= value <= 1, "invalid admission floor")
    if "cost_max_usd" in safeguards:
        require(isinstance(safeguards["cost_max_usd"], str) and re.fullmatch(r"(?:0|[1-9][0-9]{0,3})\.[0-9]{2}", safeguards["cost_max_usd"]), "cost ceiling must be a USD decimal string")
    if "resource_max" in safeguards:
        resources = safeguards["resource_max"]
        _closed(resources, {"gpu_memory_fraction", "host_memory_fraction", "host_cpu_percent"}, "resource bounds")
        for key, maximum in (("gpu_memory_fraction", 1), ("host_memory_fraction", 1), ("host_cpu_percent", 100)):
            value = resources[key]
            require(type(value) in (int, float) and 0 < value <= maximum, "invalid resource bound")
    if protocol["material"]["execution_ready"]:
        require(numeric <= set(safeguards) and "output_length_tolerance_fraction" in quality, "complete measured numeric gates required before compiled execution")
    for key, minimum, maximum in (("median_ceiling_ms", 1, 3600000), ("error_rate_max", 0, 1), ("quality_min", 0, 1)):
        value = safeguards[key]
        require(type(value) in (int, float) and minimum <= value <= maximum, f"invalid safeguard {key}")
    require(safeguards["cost_status"] == "required" and safeguards["resource_pressure"] == "reported", "invalid cost/resource safeguards")


TOOL_COMPATIBILITY_PROFILE = {'profile': 'native performance defaults + tool compatibility', 'tool_choice': 'required', 'vllm': ['--enable-auto-tool-choice', '--tool-call-parser', 'hermes'], 'sglang': ['--tool-call-parser', 'qwen25']}


def validate_protocol(protocol: Mapping[str, Any]) -> None:
    require(isinstance(protocol, Mapping) and set(protocol) == PROTOCOL_KEYS, "protocol fields are closed")
    require(protocol["schema_version"] == SCHEMA_VERSION, "invalid protocol schema")
    require(protocol["episode"] == 2 and protocol["title"] == TITLE, "catalog episode identity mismatch")
    require(protocol["classification"] in {"synthetic_mock", "recorded"}, "invalid classification")
    require(isinstance(protocol["catalog_sha256"], str) and HEX.fullmatch(protocol["catalog_sha256"]), "invalid catalog digest")
    require(isinstance(protocol["campaign_id"], str) and protocol["campaign_id"], "campaign id required")
    _text(protocol["campaign_id"], "campaign id")
    catalog = Path(__file__).resolve().parents[2] / "public-data/contracts/episode-catalog.v2.json"
    require(protocol["catalog_sha256"] == hashlib.sha256(catalog.read_bytes()).hexdigest(), "canonical catalog digest mismatch")
    from .episode2_corpus import TOOL_FIXTURES
    require(protocol["tool_fixtures_sha256"] == document_digest(TOOL_FIXTURES), "actual tool fixture digest mismatch")
    blocks = protocol["repetition_blocks"]
    require(type(blocks) is int and 6 <= blocks <= 8, "repetition blocks must be 6 through 8")
    _integer(protocol["seed"], 0, 2**32-1, "seed")

    material = protocol["material"]
    material_keys = {
        "execution_ready", "model_id", "model_revision", "tokenizer_sha256", "template_sha256",
        "artifact_sha256", "vllm_image", "sglang_image", "vllm_defaults_sha256",
        "sglang_defaults_sha256", "physical_gpu_policy", "common_launch_overrides",
        "harness_version", "context_window",
    }
    require(isinstance(material, Mapping) and set(material) in (material_keys, material_keys | {"tool_compatibility"}), "invalid material fields")
    if "tool_compatibility" in material:
        require(canonical_bytes(material["tool_compatibility"]) == canonical_bytes(TOOL_COMPATIBILITY_PROFILE), "invalid tool compatibility profile")
    require(isinstance(material["model_revision"], str) and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", material["model_revision"]), "model_revision must be immutable")
    for name in ("tokenizer_sha256", "template_sha256", "artifact_sha256", "vllm_image", "sglang_image", "vllm_defaults_sha256", "sglang_defaults_sha256"):
        require(_immutable(material[name]), f"{name} must be immutable")
    require(type(material["execution_ready"]) is bool, "execution_ready must be boolean")
    if protocol["classification"] == "synthetic_mock":
        require(material["execution_ready"] is False, "synthetic protocol cannot execute")
    for name in ("model_id", "harness_version"):
        _text(material[name], name)
    require(material["physical_gpu_policy"] == "same-physical-allocation", "invalid physical GPU policy")
    require(isinstance(material["common_launch_overrides"], list) and len(material["common_launch_overrides"]) <= 64 and all(isinstance(item, str) and len(item) <= 512 for item in material["common_launch_overrides"]), "invalid common launch overrides")
    require(type(material["context_window"]) is int and material["context_window"] > 0, "invalid context window")

    mixture = protocol["mixture"]
    require(isinstance(mixture, Mapping) and set(mixture) == {"classes", "weights", "units_per_class"}, "invalid mixture")
    classes = mixture["classes"]
    weights = mixture["weights"]
    require(isinstance(classes, Mapping) and set(classes) == set(CLASS_IDS), "undefined classes")
    require(isinstance(weights, Mapping) and set(weights) == set(CLASS_IDS), "undefined classes in weights")
    require(all(type(value) is int and value > 0 for value in weights.values()), "invalid mixture weights")
    require(len(set(weights.values())) == 1, "synthetic mixture weights must be equal")
    units = mixture["units_per_class"]
    require(type(units) is int and 1 <= units <= 128, "invalid units per class")
    for class_id, spec in classes.items():
        require(isinstance(spec, Mapping) and set(spec) == {"input_tokens_min", "input_tokens_max", "requested_output_tokens", "turns", "corpus_ref", "output_policy"}, f"invalid class {class_id}")
        minimum, maximum = spec["input_tokens_min"], spec["input_tokens_max"]
        output = spec["requested_output_tokens"]
        require(type(minimum) is int and type(maximum) is int and 1 <= minimum <= maximum, "invalid context band")
        require(type(output) is int and 1 <= output <= 512, "invalid output cap")
        require(maximum + output <= material["context_window"], "context overflow")
        require(type(spec["turns"]) is int and spec["turns"] == CLASS_TURNS[class_id], "invalid corpus turn count")
        require(spec["corpus_ref"] == f"episode2.public.{class_id}.v1", "invalid corpus reference")
        _text(spec["output_policy"], "output policy")
    require(classes["short"]["input_tokens_max"] <= 256, "short context band")
    require(classes["long_prefill"]["input_tokens_min"] >= 2048 and classes["long_prefill"]["input_tokens_max"] <= 4096, "long context band")
    require(classes["output_heavy"]["requested_output_tokens"] == 512, "output-heavy cap")

    cells = protocol["cells"]
    require(isinstance(cells, list) and cells, "cells required")
    ids = []
    for cell in cells:
        require(isinstance(cell, Mapping) and set(cell) == {"cell_id", "mode", "temperature", "concurrency", "arrival_policy"}, "invalid cell")
        require(cell["mode"] in {"closed-loop", "open-loop"}, "invalid load mode")
        require(cell["temperature"] in {"cold", "warm"}, "invalid temperature")
        require(type(cell["concurrency"]) is int and cell["concurrency"] in {2, 4, 8, 12, 16, 24}, "invalid concurrency")
        _text(cell["cell_id"], "cell id")
        require(cell["arrival_policy"] == ("completion" if cell["mode"] == "closed-loop" else "seeded_burst"), "arrival policy mismatch")
        ids.append(cell["cell_id"])
    require(len(ids) == len(set(ids)), "duplicate cell")
    _science(protocol)
    require(isinstance(protocol["tool_fixtures_sha256"], str) and HEX.fullmatch(protocol["tool_fixtures_sha256"]), "invalid tool fixture digest")
    require(protocol["continuation_version"] == "episode2.continuation.v1", "invalid continuation version")
    require(isinstance(protocol["exclusions"], list) and len(protocol["exclusions"]) <= 64 and all(isinstance(item, str) and 1 <= len(item) <= 512 for item in protocol["exclusions"]), "invalid exclusions")
    canonical_bytes(protocol)


def validate_trace(trace: Mapping[str, Any], protocol: Mapping[str, Any]) -> None:
    validate_protocol(protocol)
    _closed(trace, TRACE_KEYS, "trace")
    require(trace["schema_version"] == TRACE_SCHEMA_VERSION, "invalid trace schema")
    require(trace["protocol_sha256"] == document_digest(protocol), "protocol digest mismatch")
    require(type(trace["seed"]) is int and trace["seed"] == protocol["seed"], "trace seed mismatch")
    require(trace["mode"] in {cell["mode"] for cell in protocol["cells"]}, "trace load mode mismatch")
    require(trace["tool_fixtures_sha256"] == protocol["tool_fixtures_sha256"], "tool fixture digest mismatch")
    require(isinstance(trace["blocks"], list) and len(trace["blocks"]) == protocol["repetition_blocks"], "block count mismatch")
    require(trace["logical_sha256"] == document_digest(trace["blocks"]), "logical trace digest mismatch")
    composite: set[tuple[str, str]] = set()
    block_ids: set[str] = set()
    reference: bytes | None = None
    units = protocol["mixture"]["units_per_class"]
    expected_counts = {name: units for name in CLASS_IDS}
    turn_keys = {"logical_request_id", "workflow_id", "session_id", "turn_id", "class_id", "predecessor_id", "messages_sha256", "corpus_ref", "output_policy", "tool_fixture_ref", "eligibility"}
    for block in trace["blocks"]:
        _closed(block, {"block_id", "class_counts", "class_weights", "workflows", "turns"}, "block")
        _text(block["block_id"], "block id")
        require(block["block_id"] not in block_ids, "duplicate block id")
        block_ids.add(block["block_id"])
        require(block["class_counts"] == expected_counts and all(type(n) is int for n in block["class_counts"].values()), "trace class counts mismatch")
        require(block["class_weights"] == protocol["mixture"]["weights"] and all(type(n) is int for n in block["class_weights"].values()), "trace class weights mismatch")
        require(isinstance(block["workflows"], list) and len(block["workflows"]) == 8 * units, "workflow volume mismatch")
        require(isinstance(block["turns"], list) and len(block["turns"]) == 12 * units, "turn volume mismatch")
        workflows: dict[str, Any] = {}
        sessions: set[str] = set()
        counts = dict.fromkeys(CLASS_IDS, 0)
        for index, workflow in enumerate(block["workflows"]):
            _closed(workflow, {"workflow_id", "session_id", "class_id", "arrival_index"}, "workflow")
            for name in ("workflow_id", "session_id"):
                _text(workflow[name], name)
            require(workflow["workflow_id"] not in workflows, "duplicate workflow")
            require(workflow["session_id"] not in sessions, "duplicate session")
            require(workflow["class_id"] in CLASS_IDS, "undefined workflow class")
            require(type(workflow["arrival_index"]) is int and workflow["arrival_index"] == index, "invalid arrival index")
            workflows[workflow["workflow_id"]] = workflow
            sessions.add(workflow["session_id"])
            counts[workflow["class_id"]] += 1
        require(counts == expected_counts, "actual workflow mixture mismatch")
        turns: dict[str, Any] = {}
        by_workflow: dict[str, list[Any]] = {key: [] for key in workflows}
        for turn in block["turns"]:
            _closed(turn, turn_keys, "turn")
            for name in ("logical_request_id", "workflow_id", "session_id", "turn_id"):
                _text(turn[name], name)
            require(turn["logical_request_id"] not in turns, "duplicate logical request id")
            key = (block["block_id"], turn["logical_request_id"])
            require(key not in composite, "duplicate composite request id")
            composite.add(key)
            turns[turn["logical_request_id"]] = turn
            require(turn["workflow_id"] in workflows, "missing workflow")
            workflow = workflows[turn["workflow_id"]]
            require(turn["session_id"] == workflow["session_id"] and turn["class_id"] == workflow["class_id"], "workflow/session class mismatch")
            spec = protocol["mixture"]["classes"][turn["class_id"]]
            require(turn["corpus_ref"] == spec["corpus_ref"] and turn["output_policy"] == spec["output_policy"], "corpus policy mismatch")
            require(isinstance(turn["messages_sha256"], str) and HEX.fullmatch(turn["messages_sha256"]), "invalid messages hash")
            from .episode2_corpus import expected_messages
            require(turn["messages_sha256"] == document_digest(expected_messages(turn)), "actual messages hash mismatch")
            require(turn["tool_fixture_ref"] == ("lookup_inventory" if turn["class_id"] in {"tool_call", "agent_chain"} else None), "tool fixture reference mismatch")
            by_workflow[turn["workflow_id"]].append(turn)
        for turn in turns.values():
            seen: set[str] = set()
            current = turn
            while current is not None:
                request_id = current["logical_request_id"]
                require(request_id not in seen, "cycle in predecessor graph")
                seen.add(request_id)
                predecessor = current["predecessor_id"]
                require(predecessor is None or (isinstance(predecessor, str) and predecessor in turns), "missing predecessor")
                parent = turns.get(predecessor)
                require(parent is None or parent["workflow_id"] == turn["workflow_id"], "cross-workflow predecessor")
                current = parent
        for turn in turns.values():
            require(turn["eligibility"] == ("scheduled" if turn["predecessor_id"] is None else "predecessor_valid"), "invalid dependency eligibility")
        for workflow_id, trajectory in by_workflow.items():
            require(len(trajectory) == CLASS_TURNS[workflows[workflow_id]["class_id"]], "workflow turn count mismatch")
            predecessor = None
            for index, turn in enumerate(trajectory, 1):
                require(turn["turn_id"] == f"turn-{index}" and turn["predecessor_id"] == predecessor, "dependency order mismatch")
                predecessor = turn["logical_request_id"]
        logical = canonical_bytes({key: block[key] for key in ("class_counts", "class_weights", "workflows", "turns")})
        require(reference is None or logical == reference, "logical trace differs across blocks")
        reference = logical
