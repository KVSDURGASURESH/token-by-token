"""Purpose-written public corpus and deterministic logical traces for Episode 02."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .episode2_contract import CLASS_IDS, TRACE_SCHEMA_VERSION, canonical_bytes, document_digest, require, validate_protocol


ROOT = Path(__file__).resolve().parents[2]

CLASS_SPECS = {
    "short": (1, 256, 64, 1, "Explain equal work in one sentence.", "nonempty_text"),
    "long_prefill": (2048, 4096, 64, 1, "Retrieve declared indexed rows into JSON.", "indexed_rows_json"),
    "output_heavy": (1, 2048, 512, 1, "Produce an ordered numbered reference summary.", "ordered_concepts_and_length"),
    "structured": (1, 2048, 64, 1, 'Return exactly {"answer":6,"unit":"items"}.', "closed_json_answer"),
    "code_reasoning": (1, 2048, 96, 1, 'Return {"value":42,"expression":"6*7"}.', "allowlisted_expression_json"),
    "tool_call": (1, 2048, 64, 2, "Call lookup_inventory for sku widget, then return stock.", "tool_call_then_answer"),
    "conversation": (1, 2048, 64, 2, "Select orange, then return the validated selected color.", "validated_conversation_state"),
    "agent_chain": (1, 2048, 96, 3, "Extract widget, look up stock, then compute order to target 10.", "dependent_agent_chain"),
}

TOOL_FIXTURES = {
    "lookup_inventory": {
        "schema": {"type": "object", "additionalProperties": False, "required": ["sku"], "properties": {"sku": {"const": "widget"}}},
        "arguments": {"sku": "widget"},
        "result": {"stock": 6},
    }
}


def _catalog_sha256() -> str:
    return hashlib.sha256((ROOT / "public-data/contracts/episode-catalog.v2.json").read_bytes()).hexdigest()


def _class_contracts() -> dict[str, dict[str, Any]]:
    return {
        name: {
            "input_tokens_min": values[0],
            "input_tokens_max": values[1],
            "requested_output_tokens": values[2],
            "turns": values[3],
            "corpus_ref": f"episode2.public.{name}.v1",
            "output_policy": values[5],
        }
        for name, values in CLASS_SPECS.items()
    }


def make_synthetic_protocol(*, blocks: int = 6, units_per_class: int = 1, mode: str = "closed-loop") -> dict[str, Any]:
    return {
        "schema_version": "episode2.protocol.v1",
        "episode": 2,
        "title": "Equal-work runtime baseline",
        "classification": "synthetic_mock",
        "catalog_sha256": _catalog_sha256(),
        "campaign_id": "episode2-synthetic-rehearsal-v1",
        "material": {
            "execution_ready": False,
            "model_id": "fixture/model",
            "model_revision": "1" * 64,
            "tokenizer_sha256": "2" * 64,
            "template_sha256": "3" * 64,
            "artifact_sha256": "4" * 64,
            "vllm_image": "sha256:" + "5" * 64,
            "sglang_image": "sha256:" + "6" * 64,
            "vllm_defaults_sha256": "7" * 64,
            "sglang_defaults_sha256": "8" * 64,
            "physical_gpu_policy": "same-physical-allocation",
            "common_launch_overrides": [],
            "harness_version": "episode2-harness.v1",
            "context_window": 8192,
        },
        "mixture": {
            "classes": _class_contracts(),
            "weights": {name: 1 for name in CLASS_IDS},
            "units_per_class": units_per_class,
        },
        "cells": [{"cell_id": f"{mode}-c2-warm", "mode": mode, "temperature": "warm", "concurrency": 2, "arrival_policy": "completion" if mode == "closed-loop" else "seeded_burst"}],
        "repetition_blocks": blocks,
        "seed": 42,
        "order_policy": {"engine": "counterbalanced", "treatment": "paired", "within_session": "dependency_order"},
        "warmup_reset": {"warmup_requests": 1, "cache_reset_between_arms": True, "cold_separate": True},
        "quality": {"schema_validity": "required", "semantic_contract": "canonical", "equal_work": "required"},
        "metrics": {"primary_tail": "request_e2e_ms", "companions": ["ttft_ms", "tpot_ms", "workflow_e2e_ms"], "p99_min_n": 1000},
        "uncertainty": {"method": "paired_block_bootstrap", "confidence": 0.95, "seed": 42, "resamples": 2000, "minimum_blocks": 6},
        "safeguards": {"median_ceiling_ms": 30000, "error_rate_max": 0.01, "quality_min": 1.0, "cost_status": "required", "resource_pressure": "reported"},
        "tool_fixtures_sha256": document_digest(TOOL_FIXTURES),
        "continuation_version": "episode2.continuation.v1",
        "exclusions": ["external tool latency", "synthetic result values", "speculative decoding"],
    }


OUTPUT_CONCEPTS = (
    "equal work", "model revision", "tokenizer", "chat template",
    "input length", "output length", "sampling", "warmup",
    "time to first token", "end to end latency", "decode time", "goodput",
    "tail latency", "schema validity", "telemetry", "attributable cost",
)
LONG_TABLE = "\n".join(f"row_{index:03d}={index}; reference item." for index in range(256))
TOOL_SEMANTIC = {"name": "lookup_inventory", "arguments": {"sku": "widget"}}


def initial_messages(turn: dict[str, Any]) -> list[dict[str, str]]:
    """Concrete public first-turn content; token-band admission occurs after rendering."""
    require(turn["turn_id"] == "turn-1", "initial turn required")
    prompts = {
        "short": "Explain equal work in one sentence.",
        "long_prefill": "Use the indexed reference below. Return exactly the JSON object containing row_003 and row_127 as integer values, with no other keys.\n" + LONG_TABLE,
        "output_heavy": "Write exactly 16 numbered lines, in the supplied order. Use the exact format N. concept: explanation. Each explanation must contain 12 to 18 words, excluding its concept and number. Include no preface or conclusion.\n" + "\n".join(f"{i}. {concept}" for i, concept in enumerate(OUTPUT_CONCEPTS, 1)),
        "structured": 'Return exactly {"answer":6,"unit":"items"}. No extra keys or prose.',
        "code_reasoning": 'Return exactly {"value":42,"expression":"6*7"}. No extra keys or prose.',
        "tool_call": "Call lookup_inventory with exactly the argument sku widget. Do not return text.",
        "conversation": 'Select orange. Return exactly {"selected":"orange"}. No extra keys or prose.',
        "agent_chain": 'Extract the product sku widget. Return exactly {"sku":"widget"}. No extra keys or prose.',
    }
    require(turn["class_id"] in prompts, "unknown corpus class")
    return [{"role": "user", "content": prompts[turn["class_id"]]}]


def build_continuation(turn: dict[str, Any], semantic: dict[str, Any], tool_result: dict[str, Any] | None) -> list[dict[str, str]]:
    """Canonical continuation from validated real state; never substitutes model output."""
    contracts = {
        ("conversation", "turn-2"): ({"selected": "orange"}, None, 'Return exactly {"color":"orange"} using the validated selected state.'),
        ("tool_call", "turn-2"): (TOOL_SEMANTIC, {"stock": 6}, 'Return exactly {"answer":6} using the verified inventory stock.'),
        ("agent_chain", "turn-2"): ({"sku": "widget"}, None, "Call lookup_inventory with exactly the validated sku. Do not return text."),
        ("agent_chain", "turn-3"): (TOOL_SEMANTIC, {"stock": 6}, 'For target stock 10, subtract verified inventory stock. Return exactly {"order":4}.'),
    }
    key = (turn["class_id"], turn["turn_id"])
    require(key in contracts, "unsupported continuation")
    expected_semantic, expected_tool, instruction = contracts[key]
    require(canonical_bytes(semantic) == canonical_bytes(expected_semantic), "divergent semantic state")
    require(canonical_bytes(tool_result) == canonical_bytes(expected_tool), "divergent tool result")
    payload = {"semantic": semantic, "tool_result": tool_result, "turn_id": turn["turn_id"]}
    return [{"role": "user", "content": instruction + "\nValidated state: " + canonical_bytes(payload).decode("utf-8")}]


def expected_messages(turn: dict[str, Any]) -> list[dict[str, str]]:
    """Expected message identity; callers must validate real predecessors before using it."""
    if turn["turn_id"] == "turn-1":
        return initial_messages(turn)
    if turn["class_id"] == "conversation":
        semantic, result = {"selected": "orange"}, None
    elif turn["class_id"] == "agent_chain" and turn["turn_id"] == "turn-2":
        semantic, result = {"sku": "widget"}, None
    else:
        semantic, result = TOOL_SEMANTIC, {"stock": 6}
    return build_continuation(turn, semantic, result)


def _messages_hash(class_id: str, turn_index: int) -> str:
    return document_digest(expected_messages({"class_id": class_id, "turn_id": f"turn-{turn_index + 1}"}))


def build_trace(protocol: dict[str, Any]) -> dict[str, Any]:
    validate_protocol(protocol)
    units = protocol["mixture"]["units_per_class"]
    blocks = []
    for block_index in range(protocol["repetition_blocks"]):
        workflows = []
        turns = []
        counts = {name: units for name in CLASS_IDS}
        for class_id in CLASS_IDS:
            for unit in range(units):
                workflow_id = f"wf-{class_id}-{unit + 1:03d}"
                session_id = f"session-{class_id}-{unit + 1:03d}"
                workflows.append({"workflow_id": workflow_id, "session_id": session_id, "class_id": class_id, "arrival_index": len(workflows)})
                predecessor = None
                for turn_index in range(CLASS_SPECS[class_id][3]):
                    request_id = f"req-{class_id}-{unit + 1:03d}-t{turn_index + 1}"
                    turns.append({
                        "logical_request_id": request_id,
                        "workflow_id": workflow_id,
                        "session_id": session_id,
                        "turn_id": f"turn-{turn_index + 1}",
                        "class_id": class_id,
                        "predecessor_id": predecessor,
                        "messages_sha256": _messages_hash(class_id, turn_index),
                        "corpus_ref": protocol["mixture"]["classes"][class_id]["corpus_ref"],
                        "output_policy": protocol["mixture"]["classes"][class_id]["output_policy"],
                        "tool_fixture_ref": "lookup_inventory" if class_id in {"tool_call", "agent_chain"} else None,
                        "eligibility": "predecessor_valid" if predecessor else "scheduled",
                    })
                    predecessor = request_id
        blocks.append({
            "block_id": f"block-{block_index + 1:02d}",
            "class_counts": counts,
            "class_weights": dict(protocol["mixture"]["weights"]),
            "workflows": workflows,
            "turns": turns,
        })
    trace = {
        "schema_version": TRACE_SCHEMA_VERSION,
        "protocol_sha256": document_digest(protocol),
        "seed": protocol["seed"],
        "mode": protocol["cells"][0]["mode"],
        "blocks": blocks,
        "logical_sha256": document_digest(blocks),
        "tool_fixtures_sha256": protocol["tool_fixtures_sha256"],
    }
    return trace


def trace_digest(trace: dict[str, Any]) -> str:
    return document_digest(trace)
