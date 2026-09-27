"""Pure validation and summarization of a remote Episode 1 system source window."""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Any

try:
    from .telemetry_summary import ContractError, Series, Window, summarize
except ImportError:  # standalone private review helper
    from telemetry_summary import ContractError, Series, Window, summarize

HEX64 = re.compile(r"[0-9a-f]{64}\Z")
SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+/@-]{0,255}\Z")
RECORD_KEYS = {"schema_version", "binding", "sequence", "phase", "slot_kind",
    "scheduled_monotonic_ns", "sample_start_monotonic_ns", "observed_monotonic_ns",
    "observed_utc_ns", "clock_uncertainty_ns", "schedule_lag_ns", "missed_slots",
    "observed_gap_ns", "process_expected", "process_identity_before",
    "process_identity_after", "process_identity_status", "metrics"}
BINDING_KEYS = {"run_id", "attempt_id", "block", "clock_domain", "source_boot_id"}
METRIC_KEYS = {"source", "name", "unit", "scope", "value", "status", "reason"}
RECEIPT_KEYS = {"schema_version", "plan_sha256", "run_id", "attempt_id", "block", "runtime",
    "marker", "source_clock_domain", "source_boot_id", "source_sequence",
    "source_record_sha256", "source_observed_monotonic_ns", "source_observed_utc_ns",
    "source_utc_uncertainty_ns", "client_clock_domain", "client_call_started_monotonic_ns",
    "client_call_completed_monotonic_ns"}

class SourceWindowError(ValueError): pass

def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode()

def digest(data: bytes) -> str: return hashlib.sha256(data).hexdigest()

def _reject_constant(_: str) -> None: raise SourceWindowError("nonfinite JSON number")
def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in pairs:
        if key in out: raise SourceWindowError("duplicate JSON key")
        out[key] = value
    return out

def _load(line: bytes) -> dict[str, Any]:
    try:
        value = json.loads(line, object_pairs_hook=_pairs, parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise SourceWindowError("invalid source JSON") from exc
    if not isinstance(value, dict): raise SourceWindowError("source record must be an object")
    return value

def _closed(value: object, keys: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys: raise SourceWindowError(f"{name} is not closed")
    return value

def _integer(value: object, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise SourceWindowError(f"{name} is invalid")
    return value

def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or SAFE.fullmatch(value) is None: raise SourceWindowError(f"{name} is invalid")
    return value

def _receipt(value: object, marker: str, expected: Mapping[str, str]) -> dict[str, Any]:
    item = dict(_closed(value, RECEIPT_KEYS, f"{marker} receipt"))
    if item["schema_version"] != "episode1.system-window-boundary.v1" or item["marker"] != marker:
        raise SourceWindowError("boundary receipt schema or marker mismatch")
    for key in ("plan_sha256", "run_id", "attempt_id", "block", "runtime"):
        if item[key] != expected[key]: raise SourceWindowError(f"boundary receipt {key} mismatch")
    if item["source_clock_domain"] != "linux-clock-monotonic" or item["client_clock_domain"] != "client_monotonic_ns":
        raise SourceWindowError("boundary receipt clock domain mismatch")
    _identifier(item["source_boot_id"], "receipt boot")
    if not isinstance(item["source_record_sha256"], str) or HEX64.fullmatch(item["source_record_sha256"]) is None:
        raise SourceWindowError("boundary source hash invalid")
    for key in ("source_sequence", "source_observed_monotonic_ns", "source_observed_utc_ns",
                "source_utc_uncertainty_ns", "client_call_started_monotonic_ns",
                "client_call_completed_monotonic_ns"):
        _integer(item[key], key, 1 if key != "source_utc_uncertainty_ns" else 0)
    if item["client_call_completed_monotonic_ns"] < item["client_call_started_monotonic_ns"]:
        raise SourceWindowError("boundary client bracket reversed")
    return item

def summarize_system_source_window(*, source: bytes, start_receipt: Mapping[str, Any],
        end_receipt: Mapping[str, Any], plan_sha256: str, run_id: str, attempt_id: str,
        block: str, runtime: str, pid: int, start_ticks: int, metric_name: str, kind: str,
        labels: Mapping[str, str], max_sampling_gap_ns: int,
        first_measured_a_ns: int, last_measured_end_ns: int) -> dict[str, Any]:
    """Derive one series from the exact retained lifecycle stream.

    Client bounds establish causal enclosure only. All arithmetic uses the remote
    source monotonic domain.
    """
    expected = {"plan_sha256": plan_sha256, "run_id": run_id, "attempt_id": attempt_id,
                "block": block, "runtime": runtime}
    if not isinstance(plan_sha256, str) or HEX64.fullmatch(plan_sha256) is None: raise SourceWindowError("plan hash invalid")
    for key in ("run_id", "attempt_id", "block", "runtime", "metric_name"): _identifier(expected.get(key, metric_name) if key != "metric_name" else metric_name, key)
    if kind not in {"gauge", "counter"}: raise SourceWindowError("metric kind invalid")
    if set(labels) != {"source", "unit", "scope"} or not all(isinstance(x, str) and x for x in labels.values()):
        raise SourceWindowError("metric selector invalid")
    for value, name, minimum in ((pid,"pid",1),(start_ticks,"start_ticks",0),(max_sampling_gap_ns,"max gap",1),
                                 (first_measured_a_ns,"first measured a",1),(last_measured_end_ns,"last measured end",1)):
        _integer(value,name,minimum)
    if last_measured_end_ns < first_measured_a_ns: raise SourceWindowError("measured bounds reversed")
    if not isinstance(source, bytes) or not source or not source.endswith(b"\n"): raise SourceWindowError("source stream invalid")
    start = _receipt(start_receipt, "measurement_start", expected)
    end = _receipt(end_receipt, "measurement_end", expected)
    if start["source_boot_id"] != end["source_boot_id"]: raise SourceWindowError("boundary boot changed")
    if start["client_call_completed_monotonic_ns"] > first_measured_a_ns:
        raise SourceWindowError("start boundary does not causally precede measurement")
    if end["client_call_started_monotonic_ns"] < last_measured_end_ns:
        raise SourceWindowError("end boundary does not causally follow measurement")
    if end["client_call_started_monotonic_ns"] < start["client_call_completed_monotonic_ns"]:
        raise SourceWindowError("boundary client ordering reversed")

    parsed: list[tuple[dict[str, Any], bytes]] = []
    prior_sequence = 0; prior_scheduled: int | None = None; prior_observed: int | None = None
    boundary_counts = {"measurement_start_boundary": 0, "measurement_end_boundary": 0}
    binding0: Mapping[str, Any] | None = None
    for line in source.splitlines(keepends=True):
        record = _load(line)
        _closed(record, RECORD_KEYS, "system record")
        if canonical(record) + b"\n" != line: raise SourceWindowError("source record is not canonical")
        if record["schema_version"] != "episode1.system-sample.v1": raise SourceWindowError("system schema mismatch")
        binding = _closed(record["binding"], BINDING_KEYS, "system binding")
        if binding0 is None: binding0 = binding
        elif dict(binding) != dict(binding0): raise SourceWindowError("system binding changed")
        if (binding["run_id"],binding["attempt_id"],binding["block"],binding["clock_domain"],binding["source_boot_id"]) != (
            run_id,attempt_id,block,"linux-clock-monotonic",start["source_boot_id"]):
            raise SourceWindowError("system binding mismatch")
        sequence = _integer(record["sequence"], "sequence", 1)
        if sequence != prior_sequence + 1: raise SourceWindowError("source sequence not contiguous")
        prior_sequence = sequence
        if record["slot_kind"] not in {"periodic","measurement_start_boundary","measurement_end_boundary"}:
            raise SourceWindowError("slot kind invalid")
        if record["slot_kind"] in boundary_counts:
            boundary_counts[record["slot_kind"]] += 1
            if record["phase"] != "measurement":
                raise SourceWindowError("boundary phase invalid")
        _identifier(record["phase"], "phase")
        scheduled = _integer(record["scheduled_monotonic_ns"],"scheduled",1)
        begun = _integer(record["sample_start_monotonic_ns"],"sample start",1)
        observed = _integer(record["observed_monotonic_ns"],"observed",1)
        uncertainty = _integer(record["clock_uncertainty_ns"],"uncertainty",0)
        _integer(record["observed_utc_ns"],"observed utc",1)
        lag = _integer(record["schedule_lag_ns"],"schedule lag",0)
        _integer(record["missed_slots"],"missed slots",0)
        # The source records the midpoint of [collection_end, utc_anchor_after].
        # For odd-width brackets the midpoint floors by one nanosecond.
        if (scheduled > begun or begun > observed or lag != begun-scheduled
                or uncertainty > 2 * (observed - begun) + 1):
            raise SourceWindowError("source clocks inconsistent")
        if prior_scheduled is not None and (scheduled <= prior_scheduled or observed <= prior_observed):
            raise SourceWindowError("source clocks not strictly increasing")
        gap = record["observed_gap_ns"]
        if prior_observed is None:
            if gap is not None: raise SourceWindowError("first observed gap must be null")
        else:
            _integer(gap,"observed gap",1)
            if gap != observed-prior_observed: raise SourceWindowError("observed gap contradicts source clocks")
        target = record["process_expected"]
        before = record["process_identity_before"]
        after = record["process_identity_after"]
        if target is None:
            if before is not None or after is not None or record["process_identity_status"] != "prestart":
                raise SourceWindowError("unbound process identity invalid")
        else:
            target = _closed(target, {"pid","start_ticks","role"}, "process target")
            target_pid = _integer(target["pid"], "process target pid", 1)
            target_ticks = _integer(target["start_ticks"], "process target start ticks", 0)
            _identifier(target["role"], "process target role")
            for identity, name in ((before,"process identity before"),(after,"process identity after")):
                if not isinstance(identity,list) or len(identity) != 2:
                    raise SourceWindowError(f"{name} invalid")
                if (_integer(identity[0],f"{name} pid",1), _integer(identity[1],f"{name} start ticks",0)) != (target_pid,target_ticks):
                    raise SourceWindowError(f"{name} mismatch")
            if record["process_identity_status"] != "ok":
                raise SourceWindowError("bound process identity status invalid")
        prior_scheduled, prior_observed = scheduled, observed
        parsed.append((record,line))

    if boundary_counts != {"measurement_start_boundary": 1, "measurement_end_boundary": 1}:
        raise SourceWindowError("source must contain exactly one start and one end boundary")

    by_sequence = {record["sequence"]:(record,line) for record,line in parsed}
    start_pair = by_sequence.get(start["source_sequence"]); end_pair = by_sequence.get(end["source_sequence"])
    if start_pair is None or end_pair is None: raise SourceWindowError("boundary record absent")
    for receipt, pair, slot_kind in ((start,start_pair,"measurement_start_boundary"),(end,end_pair,"measurement_end_boundary")):
        record,line = pair
        if digest(line) != receipt["source_record_sha256"] or record["observed_monotonic_ns"] != receipt["source_observed_monotonic_ns"] or record["observed_utc_ns"] != receipt["source_observed_utc_ns"] or record["clock_uncertainty_ns"] != receipt["source_utc_uncertainty_ns"]:
            raise SourceWindowError("boundary receipt contradicts source")
        if record["slot_kind"] != slot_kind or record["phase"] != "measurement": raise SourceWindowError("boundary source marker invalid")
    start_seq=start["source_sequence"]; end_seq=end["source_sequence"]
    if end_seq <= start_seq: raise SourceWindowError("boundary sequence reversed")
    selected = [record for record,_line in parsed if start_seq <= record["sequence"] <= end_seq]
    samples=[]
    for record in selected:
        if record["phase"] != "measurement": raise SourceWindowError("selected source phase changed")
        target = _closed(record["process_expected"], {"pid","start_ticks","role"}, "process target")
        if (_integer(target["pid"],"process target pid",1), _integer(target["start_ticks"],"process target start ticks",0)) != (pid,start_ticks):
            raise SourceWindowError("process target changed")
        if target["role"] != runtime:
            raise SourceWindowError("process target runtime changed")
        for identity,name in ((record["process_identity_before"],"process identity before"),(record["process_identity_after"],"process identity after")):
            if not isinstance(identity,list) or len(identity) != 2:
                raise SourceWindowError(f"{name} invalid")
            if (_integer(identity[0],f"{name} pid",1),_integer(identity[1],f"{name} start ticks",0)) != (pid,start_ticks):
                raise SourceWindowError(f"{name} changed")
        identity_ok = record["process_identity_status"] == "ok"
        if not identity_ok: raise SourceWindowError("selected process identity changed")
        metrics = record["metrics"]
        if not isinstance(metrics,list): raise SourceWindowError("metrics invalid")
        matches=[]
        for raw in metrics:
            metric=_closed(raw,METRIC_KEYS,"metric")
            if metric["name"]==metric_name and metric["source"]==labels["source"] and metric["unit"]==labels["unit"] and metric["scope"]==labels["scope"]: matches.append(metric)
        if len(matches)!=1: raise SourceWindowError("selected metric not unique")
        metric=matches[0]
        if identity_ok and metric["status"]=="ok":
            if metric["reason"] is not None:
                raise SourceWindowError("ok metric reason must be null")
            value=metric["value"]
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value): raise SourceWindowError("metric value invalid")
            status,reason="ok",None
        elif not identity_ok: value,status,reason=None,"error","parse_failed"
        elif metric["status"]=="unavailable" and metric["value"] is not None:
            raise SourceWindowError("unavailable metric value must be null")
        elif metric["status"]=="unavailable" and metric["reason"] in {"prestart","not_reported"}: value,status,reason=None,"missing","not_reported"
        elif metric["status"]=="unavailable" and metric["reason"]=="not_supported": value,status,reason=None,"unsupported","unsupported"
        elif metric["status"]=="unavailable" and isinstance(metric["reason"],str) and metric["reason"]: value,status,reason=None,"error","scrape_failed"
        else: raise SourceWindowError("metric status invalid")
        samples.append({"clock_domain":"linux-clock-monotonic","monotonic_ns":record["observed_monotonic_ns"],
            "process_identity":f"pid:{pid}" if identity_ok else "identity-changed","process_start_identity":f"ticks:{start_ticks}",
            "runtime":runtime.split("-",1)[0],"block":block,"metric_name":metric_name,"labels":dict(labels),
            "value":value,"status":status,"reason":reason})
    window=Window("linux-clock-monotonic", start["source_observed_monotonic_ns"], end["source_observed_monotonic_ns"],
                  max_sampling_gap_ns,f"pid:{pid}",f"ticks:{start_ticks}",runtime.split("-",1)[0],block)
    try: derived=summarize(samples,window,Series.create(kind,metric_name,labels))
    except (ContractError,TypeError,ValueError) as exc: raise SourceWindowError("summary input invalid") from exc
    selected_count=len(samples); observed_count=sum(sample["status"]=="ok" for sample in samples)
    reason_map={"no_samples":"not_reported","missing_left_bracket":"sampling_gap","missing_right_bracket":"sampling_gap",
        "sampling_gap_exceeded":"sampling_gap","out_of_order":"sampling_gap","duplicate_timestamp":"sampling_gap",
        "sample_missing":"not_reported","sample_error":"scrape_failed","sample_unsupported":"unsupported",
        "counter_decreased":"counter_reset","counter_negative":"counter_reset","identity_changed":"identity_changed",
        "incompatible_clock_domain":"identity_changed","nonfinite_value":"nonfinite","derived_nonfinite":"nonfinite"}
    if derived["available"]:
        if kind=="gauge":
            gauge=derived["gauge"]; value={k:gauge[k] for k in ("minimum","maximum","mean")}
        else:
            counter=derived["counter"]; value={**counter,"elapsed_seconds":derived["sampled_interval_seconds"]}
        status="available"; unavailable=None
    else:
        unavailable=reason_map.get(str(derived["unavailable_reason"]))
        if unavailable is None: raise SourceWindowError("unsupported unavailable reason")
        status="unavailable"; value=None
    observation_window={"schema_version":"episode1.source-domain-window.v1",
        "interval_role":"measured-block-observation","basis":"remote_source_monotonic",
        "source_clock_domain":"linux-clock-monotonic","source_boot_id_sha256":digest(start["source_boot_id"].encode()),
        "source_start_monotonic_ns":start["source_observed_monotonic_ns"],"source_end_monotonic_ns":end["source_observed_monotonic_ns"],
        "duration_ns":end["source_observed_monotonic_ns"]-start["source_observed_monotonic_ns"],
        "start_boundary_receipt_sha256":digest(canonical(start)),"end_boundary_receipt_sha256":digest(canonical(end)),
        "client_start_completed_monotonic_ns":start["client_call_completed_monotonic_ns"],
        "client_end_started_monotonic_ns":end["client_call_started_monotonic_ns"],
        "association":"causal_enclosure_no_clock_mapping"}
    return {"metric_name":metric_name,"kind":kind,"status":status,"value":value,"unavailable_reason":unavailable,
        "expected_samples":selected_count,"observed_samples":observed_count,"missing_samples":selected_count-observed_count,
        "source_kind":"system_source_window","observation_window":observation_window,"samples_sha256":digest(source)}
