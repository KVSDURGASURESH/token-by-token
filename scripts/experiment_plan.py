#!/usr/bin/env python3
"""Closed, provider-free validator and canonical digest for planning configs."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = {item["id"]: item for item in json.loads((ROOT / "dashboard/src/data/experiment-templates.v1.json").read_text())["templates"]}
MONEY = re.compile(r"^(0|[1-9]\d*)(\.\d{1,2})?$")
FORBIDDEN = re.compile(r"https?://|\b(?:api[_-]?key|token|password|secret)\b|(?:^|\s)(?:bash|sh|curl|wget)\s", re.I)
KEYS = {
    "root": {"schema_version","planning_only","execution_ready","execution_authorized","identity","hypothesis","model","runtime_lanes","hardware","optimizations","workload","quality","slos","cost"},
    "identity": {"episode","track","template_id","template_version","label"}, "model": {"model_id","revision","tokenizer_id","tokenizer_revision","template_id"},
    "lane": {"engine","selected","requested_version","image_digest"}, "hardware": {"gpu_type","gpu_memory_gb","gpu_count","node_count"},
    "optimizations": {"prefix_caching","cache_policy","chunked_prefill","chunk_token_budget","attention_backend","weight_precision","weight_artifact","kv_precision","speculative_method","draft_model_id","structured_output"},
    "workload": {"input_tokens","output_tokens","output_contract","load_mode","concurrency","arrival_rate_rps","warmup_requests","requests","repetitions","timeout_seconds","cache_state"},
    "quality": {"dataset","dataset_version","metric","threshold","require_schema_validity","require_semantic_correctness"},
    "slos": {"ttft_ms","tpot_ms","end_to_end_ms","max_error_rate"}, "cost": {"desired_budget_usd","hourly_rate_usd","rate_source","rate_date","planned_duration_hours"},
}

def _closed(value: Any, key: str) -> bool:
    return isinstance(value, dict) and set(value) == KEYS[key]

def _integer(value: Any, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high

def _number(value: Any, low: float, high: float) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high

def validate_plan(plan: Any) -> list[str]:
    errors: list[str] = []
    if not _closed(plan, "root"):
        return ["Plan has missing or unknown top-level fields."]
    if plan["schema_version"] != "inference-lab.experiment-plan.v1": errors.append("Unsupported schema version.")
    if plan["planning_only"] is not True or plan["execution_ready"] is not False or plan["execution_authorized"] is not False: errors.append("Safety constants were changed.")
    for section in ("identity","model","hardware","optimizations","workload","quality","slos","cost"):
        if not _closed(plan.get(section), section): errors.append(f"{section} has missing or unknown fields.")
    lanes = plan.get("runtime_lanes")
    if not isinstance(lanes, list) or len(lanes) != 2 or any(not _closed(lane, "lane") for lane in lanes): errors.append("Runtime lanes must contain exactly two closed records.")
    if errors: return errors
    identity, workload, optimization = plan["identity"], plan["workload"], plan["optimizations"]
    required_strings = (
        (identity["label"], "Draft label"), (plan["model"]["model_id"], "Model identity"),
        (plan["model"]["revision"], "Model revision"), (plan["model"]["tokenizer_id"], "Tokenizer identity"),
        (plan["model"]["tokenizer_revision"], "Tokenizer revision"), (plan["model"]["template_id"], "Prompt template identity"),
        (plan["hardware"]["gpu_type"], "GPU type"), (optimization["weight_artifact"], "Weight artifact"),
        (plan["quality"]["dataset"], "Quality dataset"), (plan["quality"]["dataset_version"], "Dataset version"),
        (plan["quality"]["metric"], "Quality metric"), (plan["cost"]["rate_source"], "Rate source"),
    )
    for value, label in required_strings:
        if not isinstance(value, str) or not value.strip(): errors.append(f"{label} must be a nonempty string.")
    if not isinstance(optimization["draft_model_id"], str): errors.append("Draft model identity must be a string.")
    if type(plan["quality"]["require_schema_validity"]) is not bool or type(plan["quality"]["require_semantic_correctness"]) is not bool: errors.append("Quality requirements must be booleans.")
    rate_date = plan["cost"]["rate_date"]
    if rate_date is not None and (not isinstance(rate_date, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", rate_date) is None): errors.append("Rate date must be null or an ISO date.")
    template = TEMPLATES.get(identity["template_id"]) if isinstance(identity["template_id"], str) else None
    if not template or (template["episode"],template["version"],template["track"]) != (identity["episode"],identity["template_version"],identity["track"]): errors.append("Episode and template identity are inconsistent.")
    enum_checks = (
        (plan["hypothesis"], {"slow_first_token","slow_decode","throughput_collapse","high_cost"}, "Hypothesis"),
        (optimization["prefix_caching"], {"off","requested"}, "Prefix caching"), (optimization["cache_policy"], {"cold","warm","mixed"}, "Cache policy"),
        (optimization["chunked_prefill"], {"off","requested"}, "Chunked prefill"), (optimization["attention_backend"], {"auto","flashattention2","flashattention3","triton"}, "Attention backend"),
        (optimization["weight_precision"], {"bf16","fp16","fp8","int8","int4"}, "Weight precision"), (optimization["kv_precision"], {"auto","fp16","fp8"}, "KV precision"),
        (optimization["speculative_method"], {"none","draft_model"}, "Speculative method"), (optimization["structured_output"], {"none","json_schema","grammar"}, "Structured output"),
        (workload["load_mode"], {"concurrency","arrival_rate"}, "Load mode"), (workload["output_contract"], {"natural_stop","fixed_output"}, "Output contract"), (workload["cache_state"], {"cold","warm","mixed"}, "Workload cache state"),
    )
    for value, allowed, label in enum_checks:
        if not isinstance(value, str) or value not in allowed: errors.append(f"{label} is unsupported.")
    engines = [lane["engine"] for lane in lanes]
    if sorted(engines) != ["sglang","vllm"]: errors.append("Runtime lanes must be unique vLLM and SGLang lanes.")
    if any(type(lane["selected"]) is not bool or (lane["requested_version"] is not None and not isinstance(lane["requested_version"], str)) or (lane["image_digest"] is not None and not isinstance(lane["image_digest"], str)) for lane in lanes): errors.append("Runtime lane values are malformed.")
    if identity["track"] in {"model","training","decision","platform"} and any(lane["selected"] for lane in lanes): errors.append("Serving lanes are not applicable to this template.")
    if FORBIDDEN.search(json.dumps(plan, ensure_ascii=False)): errors.append("Endpoint URLs, credentials and shell commands are not accepted.")
    for value, low, high, label in ((plan["hardware"]["gpu_count"],1,64,"GPU count"),(plan["hardware"]["node_count"],1,64,"Node count"),(workload["input_tokens"],1,1048576,"Input tokens"),(workload["output_tokens"],1,1048576,"Output tokens"),(workload["warmup_requests"],0,100000,"Warm-up requests"),(workload["requests"],1,1000000,"Requests"),(workload["repetitions"],1,100,"Repetitions"),(workload["timeout_seconds"],1,86400,"Timeout")):
        if not _integer(value, low, high): errors.append(f"{label} is outside its allowed range.")
    memory = plan["hardware"]["gpu_memory_gb"]
    if memory is not None and not _number(memory,1,1000): errors.append("GPU memory is outside its allowed range.")
    for value, low, high, label in ((plan["quality"]["threshold"],0,1,"Quality threshold"),(plan["slos"]["ttft_ms"],.01,3600000,"TTFT SLO"),(plan["slos"]["tpot_ms"],.01,3600000,"TPOT SLO"),(plan["slos"]["end_to_end_ms"],.01,3600000,"End-to-end SLO"),(plan["slos"]["max_error_rate"],0,1,"Error-rate SLO")):
        if not _number(value, low, high): errors.append(f"{label} is outside its allowed range.")
    if workload["load_mode"] == "concurrency" and (not _integer(workload["concurrency"],1,100000) or workload["arrival_rate_rps"] is not None): errors.append("Concurrency mode is contradictory.")
    if workload["load_mode"] == "arrival_rate" and (not _number(workload["arrival_rate_rps"],.001,100000) or workload["concurrency"] is not None): errors.append("Arrival-rate mode is contradictory.")
    if optimization["chunked_prefill"] == "off" and optimization["chunk_token_budget"] is not None: errors.append("Chunk token budget requires chunked prefill.")
    if optimization["speculative_method"] == "draft_model" and (not isinstance(optimization["draft_model_id"], str) or not optimization["draft_model_id"].strip()): errors.append("Draft-model speculation requires a draft model identity.")
    for value, label in ((plan["cost"]["desired_budget_usd"],"Desired budget"),(plan["cost"]["planned_duration_hours"],"Planned duration"),(plan["cost"]["hourly_rate_usd"],"Hourly rate")):
        if value is not None and (not isinstance(value, str) or not MONEY.fullmatch(value)): errors.append(f"{label} must be a decimal string.")
    return errors

def canonical_digest(plan: dict[str, Any]) -> str:
    canonical = json.dumps(plan, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
