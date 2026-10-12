"""Crash-conscious private Episode 1 evidence capture (provider-free helper).

This module performs filesystem work only.  It never contacts a provider and
never treats a caller supplied success receipt as proof of an observation.
"""
from __future__ import annotations

import hashlib
import base64
import json
import math
import os
import re
import stat
import threading
from decimal import Decimal, InvalidOperation
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .telemetry_summary import ContractError as TelemetryContractError
from .telemetry_summary import Series, Window, summarize
from .native_sampler import SamplerError as NativeSamplerError
from .native_sampler import parse_prometheus
from .source_window import summarize_system_source_window

ZERO = "0" * 64
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
LEDGER_KEYS = {"schema_version", "sequence", "event", "monotonic_ns", "utc_ns",
               "clock_domain", "boot_id", "previous_sha256", "details_sha256",
               "record_sha256"}
STREAM_KEYS = {"schema_version", "sequence", "previous_sha256", "payload_sha256",
               "record_sha256", "payload"}
ALLOWED_EVENTS = {
    "allocation-create-intent", "authorization-verified", "deletion-authority-owned",
    "allocation-owned", "allocation-readback", "termination-guard-armed",
    "block-attested", "startup-retry", "runtime-ready", "warmup-complete", "cell-complete",
    "runtime-stopped", "runtime-stopped-on-abort",
    "runtime-stop-failed", "essential-export-complete",
    "essential-export-failed", "deletion-verified", "provider-settlement-observed",
    "provider-observation", "capture-closed", "block-start", "startup-failed",
    "failed-start-cleanup", "block-stop", "cleanup-attempt-observed",
    "failed-telemetry-source",
}
CALLER_BOUNDARY_EVENTS = {
    "authorization-verified", "allocation-readback", "termination-guard-armed",
    "block-attested", "startup-retry", "runtime-ready",
    "runtime-stopped", "runtime-stopped-on-abort",
    "runtime-stop-failed", "essential-export-failed",
}
class CaptureError(RuntimeError): pass
class IntegrityError(CaptureError): pass
class IncompleteEvidence(CaptureError): pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest()


def _sealed_artifact(value: Mapping[str,Any]) -> dict[str,Any]:
    result=dict(value)
    if "artifact_sha256" in result: raise ValueError("artifact already sealed")
    result["artifact_sha256"]=sha(canonical(result))
    return result


def _json_loads_strict(data: bytes) -> Any:
    def pairs(items: list[tuple[str,Any]]) -> dict[str,Any]:
        result={}
        for key,value in items:
            if key in result: raise IntegrityError("duplicate JSON object key")
            result[key]=value
        return result
    def constant(value: str) -> Any: raise IntegrityError(f"nonfinite JSON value: {value}")
    try: return json.loads(data,object_pairs_hook=pairs,parse_constant=constant)
    except (json.JSONDecodeError,UnicodeDecodeError) as exc: raise IntegrityError("invalid JSON") from exc


def _integer(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return float(value)


def _deadline_ns(value: int | float, name: str) -> int:
    """Accept exact nanoseconds, or legacy finite seconds without float equality."""
    if isinstance(value, bool): raise ValueError(f"{name} is invalid")
    if isinstance(value, int): return _integer(value, name, 1)
    if not isinstance(value, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} is invalid")
    try: return int((Decimal(str(value)) * Decimal(1_000_000_000)).to_integral_value())
    except (InvalidOperation, ValueError) as exc: raise ValueError(f"{name} is invalid") from exc


NATIVE_ENVELOPE_KEYS = {"schema_version", "binding", "sequence", "scheduled_monotonic_ns",
    "observed_monotonic_ns", "observed_utc_ns", "clock_uncertainty_ns",
    "scrape_start_monotonic_ns", "scrape_end_monotonic_ns", "scrape_deadline_monotonic_ns",
    "scrape_status", "scrape_reason", "schedule_lag_ns", "observed_process_identity_before",
    "observed_process_identity_after", "raw_kind", "raw_sha256", "raw_base64",
    "native_samples", "counter_resets"}
NATIVE_SAMPLE_KEYS = {"clock_domain", "monotonic_ns", "process_identity",
    "process_start_identity", "runtime", "block", "metric_name", "labels", "value",
    "status", "reason", "kind", "unit", "help", "declared_type", "declared_unit"}
SYSTEM_ENVELOPE_KEYS = {"schema_version","binding","sequence","phase",
    "scheduled_monotonic_ns","sample_start_monotonic_ns","observed_monotonic_ns",
    "observed_utc_ns","clock_uncertainty_ns","schedule_lag_ns","missed_slots",
    "observed_gap_ns","process_expected","process_identity_before","process_identity_after",
    "process_identity_status","metrics"}
SYSTEM_METRIC_KEYS = {"source","name","unit","scope","value","status","reason"}
SYSTEM_SOURCE_PAYLOAD_KEYS = {"schema_version", "plan_sha256", "block_id", "runtime",
    "run_attempt_id", "startup_attempt_id", "block_attempt", "source_sha256", "record"}
MAX_SYSTEM_SOURCE_BYTES_PER_BLOCK = 16 * 1024 * 1024
MAX_SYSTEM_SOURCE_RECORDS = 20_000
MAX_SYSTEM_SOURCE_STREAM_BYTES = 128 * 1024 * 1024


COUNTER_SEMANTICS = "delta_over_actual_bracketing_interval"
COUNTER_PROJECTION_KEYS = {
    "unit", "counter_semantics", "first_sample_monotonic_ns",
    "last_sample_monotonic_ns", "coverage",
}


def _summary_projection(samples: list[dict[str,Any]], win: Window, ser: Series,
                        metric_name: str, kind: str, unit: str,
                        source: bytes) -> tuple[dict[str,Any],str]:
    try: derived=summarize(samples,win,ser)
    except (TelemetryContractError,TypeError,ValueError) as exc:
        raise IntegrityError("telemetry samples are invalid") from exc
    expected=len(samples); ok=sum(1 for sample in samples if sample["status"]=="ok"); missing=expected-ok
    reason_map={"no_samples":"not_reported","missing_left_bracket":"sampling_gap",
        "missing_right_bracket":"sampling_gap","sampling_gap_exceeded":"sampling_gap",
        "out_of_order":"sampling_gap","duplicate_timestamp":"sampling_gap",
        "sample_missing":"not_reported","sample_error":"scrape_failed",
        "sample_unsupported":"unsupported","counter_decreased":"counter_reset",
        "counter_negative":"counter_reset","identity_changed":"identity_changed",
        "incompatible_clock_domain":"identity_changed","nonfinite_value":"nonfinite",
        "derived_nonfinite":"nonfinite"}
    if derived["available"]:
        # summarize() chooses the actual bracketing samples for the requested
        # window.  Do not let retained startup/drain samples outside that
        # bracket alter the promoted value projection.
        left=derived["first_sample_monotonic_ns"]
        right=derived["last_sample_monotonic_ns"]
        values=[float(sample["value"]) for sample in samples
            if sample["status"]=="ok" and left<=sample["monotonic_ns"]<=right]
        if not values: raise IntegrityError("available telemetry has no selected values")
        if kind=="counter":
            counter=derived["counter"]
            if not isinstance(counter,Mapping): raise IntegrityError("available counter lacks derivation")
            value={**counter,"elapsed_seconds":derived["sampled_interval_seconds"]}
        else:
            value={"minimum":min(values),"maximum":max(values),"mean":sum(values)/len(values)}
        status,unavailable="available",None
    else:
        unavailable=reason_map.get(str(derived["unavailable_reason"]))
        if unavailable is None: raise IntegrityError("unsupported telemetry unavailability reason")
        status,value="unavailable",None
    result={"metric_name":metric_name,"kind":kind,"status":status,"value":value,
        "unavailable_reason":unavailable,"expected_samples":expected,"observed_samples":ok,
        "missing_samples":missing}
    if kind=="counter":
        if not isinstance(unit,str) or not unit: raise IntegrityError("counter unit is invalid")
        result.update(unit=unit,counter_semantics=COUNTER_SEMANTICS,
            first_sample_monotonic_ns=derived["first_sample_monotonic_ns"],
            last_sample_monotonic_ns=derived["last_sample_monotonic_ns"],
            coverage=derived["coverage"])
    return result,sha(source)


def _native_source_summary(source: bytes, *, run_id: str, attempt_id: str,
                           block: str, runtime: str, clock_domain: str,
                           metric_name: str, kind: str,
                           labels: Mapping[str, str], window: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    """Recompute from exact newline-concatenated native_sampler slot artifacts.

    For a successful scrape, the selected native sample is checked against a
    fresh parse of the retained HTTP body.  The sampler's projection is not an
    independent source of truth.
    """
    if not source.endswith(b"\n"): raise IntegrityError("native artifact stream must preserve final newline")
    lines=source.splitlines(keepends=True)
    if not lines: raise IntegrityError("native artifact stream is empty")
    samples=[]; prior_sequence=0; binding0=None; units=set()
    for line in lines:
        envelope=_json_loads_strict(line)
        if not isinstance(envelope,dict): raise IntegrityError("native scrape artifact is not an object")
        _closed(envelope,NATIVE_ENVELOPE_KEYS,"native scrape artifact")
        if envelope["schema_version"]!="episode1.native-scrape.v1": raise IntegrityError("native scrape schema unsupported")
        binding=envelope["binding"]
        if not isinstance(binding,dict): raise IntegrityError("native scrape binding invalid")
        _closed(binding,{"run_id","attempt_id","process_identity","process_start_identity","runtime","block","clock_domain"},"native scrape binding")
        if binding["run_id"]!=run_id or binding["attempt_id"]!=attempt_id or binding["block"]!=block:
            raise IntegrityError("native scrape capture binding mismatch")
        if binding["runtime"]!=runtime or binding["clock_domain"]!=clock_domain:
            raise IntegrityError("native scrape runtime or clock binding mismatch")
        if not all(isinstance(binding[key],str) and SAFE_ID.fullmatch(binding[key]) is not None
                   for key in ("process_identity","process_start_identity","runtime","block","clock_domain")):
            raise IntegrityError("native scrape binding identity invalid")
        if binding0 is None: binding0=dict(binding)
        elif binding!=binding0: raise IntegrityError("native scrape identity changed")
        sequence=_integer(envelope["sequence"],"native scrape sequence",1)
        if sequence!=prior_sequence+1: raise IntegrityError("native scrape sequence is not contiguous")
        prior_sequence=sequence
        try: raw=base64.b64decode(envelope["raw_base64"],validate=True)
        except (ValueError,TypeError) as exc: raise IntegrityError("native scrape raw payload invalid") from exc
        if sha(raw)!=envelope["raw_sha256"]: raise IntegrityError("native scrape raw hash mismatch")
        observed=_integer(envelope["observed_monotonic_ns"],"native observed time",1)
        _integer(envelope["observed_utc_ns"],"native observed UTC",1)
        uncertainty=_integer(envelope["clock_uncertainty_ns"],"native clock uncertainty")
        scrape_start=_integer(envelope["scrape_start_monotonic_ns"],"native scrape start",1)
        scrape_end=_integer(envelope["scrape_end_monotonic_ns"],"native scrape end",scrape_start)
        scrape_deadline=_integer(envelope["scrape_deadline_monotonic_ns"],"native scrape deadline",1)
        scheduled=_integer(envelope["scheduled_monotonic_ns"],"native scheduled time",1)
        lag=_integer(envelope["schedule_lag_ns"],"native schedule lag")
        observation_before=observed-(uncertainty//2)
        observation_after=observation_before+uncertainty
        if (scheduled>scrape_start or lag!=scrape_start-scheduled or
            observation_before<scrape_start or observation_after>scrape_end):
            raise IntegrityError("native scrape clocks are inconsistent")
        scrape_status=envelope["scrape_status"]
        scrape_reason=envelope["scrape_reason"]
        if scrape_status not in {"ok","error","unsupported"}:
            raise IntegrityError("native scrape status invalid")
        parsed=None
        if scrape_status=="ok":
            if (scrape_start>=scrape_deadline or scrape_reason is not None or envelope["raw_kind"]!="body" or
                envelope["observed_process_identity_before"]!=[binding["process_identity"],binding["process_start_identity"]] or
                envelope["observed_process_identity_after"]!=[binding["process_identity"],binding["process_start_identity"]]):
                raise IntegrityError("successful native scrape lacks stable bound identity")
            try: parsed=parse_prometheus(raw)
            except NativeSamplerError as exc: raise IntegrityError("successful native scrape body is invalid") from exc
        elif not isinstance(scrape_reason,str) or not scrape_reason:
            raise IntegrityError("failed native scrape lacks reason")
        native=envelope["native_samples"]
        if not isinstance(native,list): raise IntegrityError("native samples are not an array")
        matching=[]
        for sample in native:
            if not isinstance(sample,dict): raise IntegrityError("native sample is not an object")
            _closed(sample,NATIVE_SAMPLE_KEYS,"native sample")
            if sample["metric_name"]==metric_name and sample["kind"]==kind and sample["labels"]==dict(labels):
                matching.append(sample)
        if len(matching)!=1: raise IntegrityError("native slot does not contain exactly one selected series")
        selected=matching[0]
        if any(selected[key]!=binding[key] for key in ("clock_domain","process_identity","process_start_identity","runtime","block")):
            raise IntegrityError("native sample identity differs from envelope binding")
        if selected["monotonic_ns"]!=observed:
            raise IntegrityError("native sample clock differs from envelope observation")
        if not isinstance(selected["unit"],str) or not selected["unit"]:
            raise IntegrityError("native sample unit invalid")
        units.add(selected["unit"])
        if scrape_status=="unsupported":
            expected={"status":"unsupported","reason":"unsupported","value":None,"help":None,
                      "declared_type":None,"declared_unit":None}
        elif scrape_status!="ok":
            expected={"status":"error","reason":"parse_failed" if scrape_reason=="parse_failed" else "scrape_failed",
                      "value":None,"help":None,"declared_type":None,"declared_unit":None}
        else:
            assert parsed is not None
            points=[point for point in parsed.points
                    if point.metric_name==metric_name and dict(point.labels)==dict(labels)]
            if not points:
                expected={"status":"missing","reason":"not_reported","value":None,"help":None,
                          "declared_type":None,"declared_unit":None}
            elif len(points)!=1:
                expected={"status":"error","reason":"parse_failed","value":None,"help":None,
                          "declared_type":None,"declared_unit":None}
            else:
                point=points[0]
                expected={"status":"ok","reason":None,"value":point.value,"help":point.help,
                          "declared_type":point.declared_type,"declared_unit":point.declared_unit}
                allowed={"counter"} if kind=="counter" else {"gauge","untyped"}
                # Prometheus associates TYPE metadata with the histogram family,
                # while its monotonic ``*_sum`` sample is selected as a counter.
                if kind=="counter" and metric_name.endswith("_sum"):
                    allowed.add("histogram")
                if ((point.declared_type is not None and point.declared_type not in allowed) or
                    (point.declared_unit is not None and point.declared_unit!=selected["unit"])):
                    expected.update(status="error",reason="parse_failed",value=None)
        if any(selected[key]!=expected[key] for key in expected):
            raise IntegrityError("native sample projection contradicts retained scrape body")
        samples.append({key:selected[key] for key in ("clock_domain","monotonic_ns","process_identity",
            "process_start_identity","runtime","block","metric_name","labels","value","status","reason")})
    _closed(window,{"start_monotonic_ns","end_monotonic_ns","max_sampling_gap_ns"},"telemetry window")
    assert binding0 is not None
    try:
        runtime_family=runtime.split("-",1)[0]
        samples=[{**sample,"runtime":runtime_family} for sample in samples]
        win=Window(clock_domain=binding0["clock_domain"],process_identity=binding0["process_identity"],
            process_start_identity=binding0["process_start_identity"],runtime=runtime_family,block=block,
            start_monotonic_ns=window["start_monotonic_ns"],end_monotonic_ns=window["end_monotonic_ns"],
            max_sampling_gap_ns=window["max_sampling_gap_ns"])
        ser=Series.create(kind,metric_name,labels)
    except (TelemetryContractError,TypeError,ValueError) as exc:
        raise IntegrityError("native telemetry samples are invalid") from exc
    if len(units)!=1: raise IntegrityError("native sample unit changed")
    return _summary_projection(samples,win,ser,metric_name,kind,next(iter(units)),source)


def _system_source_summary(source: bytes, *, run_id: str, attempt_id: str, block: str,
                           runtime: str, clock_domain: str, metric_name: str, kind: str,
                           labels: Mapping[str,str], window: Mapping[str,Any]) -> tuple[dict[str,Any],str]:
    """Recompute one numeric series from exact system_sampler emitted records."""
    if set(labels)!={"source","unit","scope"} or not all(isinstance(x,str) and x for x in labels.values()):
        raise IntegrityError("system metric selector must be source/unit/scope strings")
    _closed(window,{"start_monotonic_ns","end_monotonic_ns","max_sampling_gap_ns","pid","start_ticks"},"system telemetry window")
    pid=_integer(window["pid"],"system pid",1); ticks=_integer(window["start_ticks"],"system start ticks",0)
    if not source.endswith(b"\n"): raise IntegrityError("system artifact stream must preserve final newline")
    samples=[]; prior_sequence=0; prior_scheduled=None; prior_observed=None; binding0=None
    for line in source.splitlines(keepends=True):
        record=_json_loads_strict(line)
        if not isinstance(record,dict): raise IntegrityError("system sample artifact is not an object")
        _closed(record,SYSTEM_ENVELOPE_KEYS,"system sample artifact")
        if record["schema_version"]!="episode1.system-sample.v1": raise IntegrityError("system sample schema unsupported")
        if not isinstance(record["phase"],str) or SAFE_ID.fullmatch(record["phase"]) is None:
            raise IntegrityError("system sample phase is invalid")
        binding=record["binding"]
        if not isinstance(binding,dict): raise IntegrityError("system sample binding invalid")
        _closed(binding,{"run_id","attempt_id","block","clock_domain"},"system sample binding")
        if binding["run_id"]!=run_id or binding["attempt_id"]!=attempt_id or binding["block"]!=block:
            raise IntegrityError("system sample capture binding mismatch")
        if binding["clock_domain"]!=clock_domain:
            raise IntegrityError("system sample clock binding mismatch")
        if binding0 is None: binding0=dict(binding)
        elif binding!=binding0: raise IntegrityError("system sample binding changed")
        sequence=_integer(record["sequence"],"system sample sequence",1)
        if sequence!=prior_sequence+1: raise IntegrityError("system sample sequence is not contiguous")
        prior_sequence=sequence
        scheduled=_integer(record["scheduled_monotonic_ns"],"system scheduled time")
        started=_integer(record["sample_start_monotonic_ns"],"system sample start")
        observed=_integer(record["observed_monotonic_ns"],"system observed time")
        _integer(record["observed_utc_ns"],"system observed UTC",1)
        uncertainty=_integer(record["clock_uncertainty_ns"],"system clock uncertainty")
        _integer(record["schedule_lag_ns"],"system schedule lag"); _integer(record["missed_slots"],"system missed slots")
        gap=record["observed_gap_ns"]
        if gap is not None: _integer(gap,"system observed gap",0)
        if started<scheduled or observed<started or uncertainty>observed-started:
            raise IntegrityError("system paired clock observation is inconsistent")
        if prior_scheduled is not None and (scheduled<=prior_scheduled or observed<=prior_observed):
            raise IntegrityError("system sample clocks are not strictly increasing")
        prior_scheduled,prior_observed=scheduled,observed
        target=record["process_expected"]
        expected=[pid,ticks]
        before,after=record["process_identity_before"],record["process_identity_after"]
        prestart=target is None
        if prestart:
            if (record["process_identity_status"]!="prestart" or before is not None or after is not None):
                raise IntegrityError("system prestart process identity is inconsistent")
            identity_ok=True
        else:
            if not isinstance(target,dict): raise IntegrityError("system process target is invalid")
            _closed(target,{"pid","start_ticks","role"},"system process target")
            if (target["pid"]!=pid or target["start_ticks"]!=ticks or
                not isinstance(target["role"],str) or SAFE_ID.fullmatch(target["role"]) is None):
                raise IntegrityError("system process target changed")
            identity_ok=(record["process_identity_status"]=="ok" and before==expected and after==expected)
        metrics=record["metrics"]
        if not isinstance(metrics,list): raise IntegrityError("system metrics are not an array")
        matches=[]
        for metric in metrics:
            if not isinstance(metric,dict): raise IntegrityError("system metric is not an object")
            _closed(metric,SYSTEM_METRIC_KEYS,"system metric")
            if (metric["name"]==metric_name and metric["source"]==labels["source"] and
                metric["unit"]==labels["unit"] and metric["scope"]==labels["scope"]): matches.append(metric)
        if len(matches)!=1: raise IntegrityError("system slot does not contain exactly one selected metric")
        metric=matches[0]; raw_status=metric["status"]; raw_reason=metric["reason"]
        if identity_ok and raw_status=="ok":
            value=metric["value"]
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
                raise IntegrityError("system numeric metric is invalid")
            status,reason="ok",None
        else:
            value=None
            if not identity_ok: status,reason="error","parse_failed"
            elif raw_status=="unavailable" and raw_reason in {"prestart","not_reported"}:
                status,reason="missing","not_reported"
            elif raw_status=="unavailable" and raw_reason=="not_supported": status,reason="unsupported","unsupported"
            elif raw_status=="unavailable" and isinstance(raw_reason,str) and raw_reason: status,reason="error","scrape_failed"
            else: raise IntegrityError("system metric unavailable state is invalid")
        samples.append({"clock_domain":binding["clock_domain"],"monotonic_ns":observed,
            # Preserve a detected identity mismatch for the reviewed pure
            # summarizer.  It must derive identity_changed rather than turn a
            # restarted process into an ordinary scrape failure.
            "process_identity":f"pid:{pid}" if identity_ok else "identity-changed",
            "process_start_identity":f"ticks:{ticks}",
            "runtime":runtime,"block":block,"metric_name":metric_name,"labels":dict(labels),
            "value":value,"status":status,"reason":reason})
    if binding0 is None: raise IntegrityError("system artifact stream is empty")
    try:
        runtime_family=runtime.split("-",1)[0]
        samples=[{**sample,"runtime":runtime_family} for sample in samples]
        win=Window(clock_domain=binding0["clock_domain"],process_identity=f"pid:{pid}",
            process_start_identity=f"ticks:{ticks}",runtime=runtime_family,block=block,
            start_monotonic_ns=window["start_monotonic_ns"],end_monotonic_ns=window["end_monotonic_ns"],
            max_sampling_gap_ns=window["max_sampling_gap_ns"])
        ser=Series.create(kind,metric_name,labels)
    except (TelemetryContractError,TypeError,ValueError) as exc:
        raise IntegrityError("system telemetry selector is invalid") from exc
    return _summary_projection(samples,win,ser,metric_name,kind,labels["unit"],source)


def _closed(value: Mapping[str, Any], keys: set[str], name: str) -> None:
    if set(value) != keys: raise ValueError(f"{name} fields are not closed")


def _full_write(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        count = os.write(fd, view)
        if count <= 0: raise OSError("short write made no progress")
        view = view[count:]


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try: os.fsync(fd)
    finally: os.close(fd)


def _atomic(path: Path, data: bytes) -> None:
    tmp = path.parent / ("." + path.name + f".{os.getpid()}.{threading.get_ident()}." + os.urandom(8).hex() + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        _full_write(fd, data)
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        try: tmp.unlink()
        except FileNotFoundError: pass
        raise
    else: os.close(fd)
    try:
        # link() gives create-if-absent semantics; immutable evidence is never
        # replaced, including by a symlink introduced at the destination.
        os.link(tmp, path)
        os.unlink(tmp)
        os.chmod(path, 0o600)
        _fsync_dir(path.parent)
    except BaseException:
        try: tmp.unlink()
        except FileNotFoundError: pass
        raise


def _append(path: Path, data: bytes) -> None:
    existed = path.exists()
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise IntegrityError("evidence stream is not a singly linked regular file")
        _full_write(fd, data)
        os.fsync(fd)
    finally: os.close(fd)
    if not existed: _fsync_dir(path.parent)


def _safe_new_directory(path: Path) -> None:
    if not path.is_absolute(): raise ValueError("evidence directory must be absolute")
    cursor = path.parent
    while True:
        info = os.lstat(cursor)
        if stat.S_ISLNK(info.st_mode): raise ValueError("symlink parent is forbidden")
        if not stat.S_ISDIR(info.st_mode): raise ValueError("parent must be a directory")
        if cursor == cursor.parent: break
        cursor = cursor.parent
    os.mkdir(path, 0o700)
    os.chmod(path, 0o700)
    _fsync_dir(path.parent)


@dataclass(frozen=True)
class RunContract:
    run_id: str
    attempt_id: str
    plan_sha256: str
    source_sha256: str
    material_sha256: str
    blocks: tuple[tuple[str, str], ...]
    request_counts: Mapping[str, int]  # key: block|cell|0-or-1(warmup)
    telemetry_series: tuple[str, ...]
    original_t0_monotonic_ns: int
    original_t0_utc_ns: int
    hard_deadline_monotonic_ns: int
    teardown_deadline_monotonic_ns: int
    clock_domain: str
    boot_id: str

    def checked(self) -> "RunContract":
        for name in ("run_id", "attempt_id", "clock_domain", "boot_id"):
            if not SAFE_ID.fullmatch(getattr(self, name)): raise ValueError(f"invalid {name}")
        for name in ("plan_sha256", "source_sha256", "material_sha256"):
            if not HEX64.fullmatch(getattr(self, name)): raise ValueError(f"invalid {name}")
        if len(self.blocks) != 6 or len(set(self.blocks)) != 6: raise ValueError("exactly six distinct blocks required")
        for pair in self.blocks:
            if len(pair) != 2 or not all(SAFE_ID.fullmatch(x) for x in pair): raise ValueError("invalid block binding")
        for key, count in self.request_counts.items():
            if not isinstance(key, str) or len(key.split("|")) != 3: raise ValueError("invalid request-count key")
            block, cell, warm = key.split("|")
            if block not in {x[0] for x in self.blocks} or not SAFE_ID.fullmatch(cell) or warm not in {"0","1"}:
                raise ValueError("request-count key is outside the block schedule")
            _integer(count, "request count", 1)
        warmups=sum(n for key,n in self.request_counts.items() if key.endswith("|1"))
        measured=sum(n for key,n in self.request_counts.items() if key.endswith("|0"))
        if (warmups,measured)!=(72,528): raise ValueError("Episode 1 requires exactly 72 warmups and 528 measurements")
        if not self.telemetry_series or len(set(self.telemetry_series)) != len(self.telemetry_series):
            raise ValueError("telemetry series must be a nonempty unique tuple")
        for value, name in ((self.original_t0_monotonic_ns,"t0"),(self.original_t0_utc_ns,"utc"),
            (self.hard_deadline_monotonic_ns,"hard deadline"),(self.teardown_deadline_monotonic_ns,"teardown deadline")):
            _integer(value, name, 1)
        if not self.original_t0_monotonic_ns < self.teardown_deadline_monotonic_ns <= self.hard_deadline_monotonic_ns:
            raise ValueError("original deadlines are inconsistent")
        return self

    def json(self) -> dict[str, Any]:
        value = asdict(self); value["blocks"] = [list(x) for x in self.blocks]
        value["telemetry_series"] = list(self.telemetry_series)
        value["schema_version"] = "episode1.capture-contract.v2"
        return value


@dataclass(frozen=True)
class CleanupOnlyAuthority:
    private_id: str
    unique_name: str
    client_correlation_token: str
    billing_started_monotonic_ns: int
    original_t0_monotonic_ns: int
    hard_deadline_monotonic_ns: int
    teardown_deadline_monotonic_ns: int
    clock_domain: str
    boot_id: str
    deadline_comparable: bool
    ledger_integrity: str
    mode: str = "cleanup_only"


@dataclass(frozen=True)
class AmbiguousCreateIntent:
    unique_name: str
    client_correlation_token: str
    plan_sha256: str
    mode: str = "fresh_inventory_recovery_only"


class EvidenceCaptureV2:
    def __init__(self, directory: Path, contract: RunContract, *,
                 monotonic_ns: Callable[[], int], utc_ns: Callable[[], int],
                 observation_validator: Callable[[Mapping[str, Any]], Mapping[str, Any]]):
        contract.checked(); _safe_new_directory(directory)
        self.directory, self.contract = directory, contract
        self.monotonic_ns, self.utc_ns = monotonic_ns, utc_ns
        self.observation_validator = observation_validator
        self._lock = threading.RLock(); self._closed = False; self._seal_pending = False
        self._ledger_seq = 0; self._ledger_prev = ZERO
        self._stream = {"requests": [0, ZERO], "request-lifecycle": [0, ZERO],
                        "telemetry": [0, ZERO], "system-source": [0, ZERO]}
        self._system_source_bytes: dict[tuple[str, str, str, str], int] = {}
        self._request_lifecycle: dict[str, tuple[str, str, int, str, int]] = {}
        self._last_mono = contract.original_t0_monotonic_ns
        self._resource_identity_sha256: str|None = None
        self._cleanup_resource_identity_sha256: str|None = None
        _atomic(directory / "contract.json", canonical(contract.json()) + b"\n")
        _atomic(directory / "requests.jsonl", b"")
        _atomic(directory / "request-lifecycle.jsonl", b"")
        _atomic(directory / "telemetry.jsonl", b"")
        _atomic(directory / "system-source.jsonl", b"")

    def _times(self) -> tuple[int, int]:
        mono, utc = self.monotonic_ns(), self.utc_ns()
        _integer(mono, "monotonic clock", 0); _integer(utc, "UTC clock", 0)
        if mono < self._last_mono: raise IntegrityError("monotonic clock moved backward")
        self._last_mono = mono
        return mono, utc

    def _ledger(self, event: str, details: Mapping[str, Any]) -> None:
        if event not in ALLOWED_EVENTS: raise ValueError("event is outside the closed v2 vocabulary")
        if self._closed: raise CaptureError("capture is closed")
        payload = canonical(dict(details)); digest = sha(payload)
        mono, utc = self._times(); seq = self._ledger_seq + 1
        _atomic(self.directory / f"event-{seq:06d}-{digest}.json", payload + b"\n")
        entry = {"schema_version":"episode1.private-ledger.v2", "sequence":seq,
            "event":event, "monotonic_ns":mono, "utc_ns":utc,
            "clock_domain":self.contract.clock_domain, "boot_id":self.contract.boot_id,
            "previous_sha256":self._ledger_prev, "details_sha256":digest}
        entry["record_sha256"] = sha(canonical(entry))
        _append(self.directory / "lifecycle.jsonl", canonical(entry) + b"\n")
        self._ledger_seq, self._ledger_prev = seq, entry["record_sha256"]

    def _stream_record(self, stream: str, payload: Mapping[str, Any]) -> None:
        seq, previous = self._stream[stream]; seq += 1
        body = dict(payload); digest = sha(canonical(body))
        entry = {"schema_version":f"episode1.{stream}-stream.v2", "sequence":seq,
                 "previous_sha256":previous, "payload_sha256":digest, "payload":body}
        entry["record_sha256"] = sha(canonical({k:v for k,v in entry.items() if k != "record_sha256"}))
        _append(self.directory / f"{stream}.jsonl", canonical(entry) + b"\n")
        self._stream[stream] = [seq, entry["record_sha256"]]

    def prepare(self, plan: Mapping[str, Any], unique_name: str, ownership_token: str) -> None:
        with self._lock:
            if plan.get("plan_sha256") != self.contract.plan_sha256: raise ValueError("plan mismatch")
            if not SAFE_ID.fullmatch(unique_name) or not isinstance(ownership_token, str) or len(ownership_token) < 32:
                raise ValueError("invalid create identity")
            intent = {"schema_version":"episode1.create-intent.v2", "run_id":self.contract.run_id,
                "plan_sha256":self.contract.plan_sha256, "source_sha256":self.contract.source_sha256,
                "material_sha256":self.contract.material_sha256, "unique_name":unique_name,
                "client_correlation_token":ownership_token,
                "original_t0_monotonic_ns":self.contract.original_t0_monotonic_ns,
                "original_t0_utc_ns":self.contract.original_t0_utc_ns,
                "hard_deadline_monotonic_ns":self.contract.hard_deadline_monotonic_ns,
                "teardown_deadline_monotonic_ns":self.contract.teardown_deadline_monotonic_ns,
                "clock_domain":self.contract.clock_domain, "boot_id":self.contract.boot_id}
            _atomic(self.directory / "create-intent.json", canonical(intent)+b"\n")
            self._ledger("allocation-create-intent", {"intent_sha256":sha(canonical(intent))})

    def owned(
        self,
        authority: Any,
        plan: Mapping[str, Any],
        *,
        cleanup_deadline_monotonic: int | float,
    ) -> None:
        with self._lock:
            intent = _load_json(self.directory / "create-intent.json")
            if plan.get("plan_sha256") != self.contract.plan_sha256: raise ValueError("plan mismatch")
            if _deadline_ns(cleanup_deadline_monotonic,"cleanup deadline") != self.contract.hard_deadline_monotonic_ns:
                raise ValueError("cleanup deadline must be the original hard deadline")
            private_id, name, token = authority.private_id, authority.unique_name, authority.ownership_token
            if not SAFE_ID.fullmatch(private_id) or name != intent["unique_name"] or token != intent["client_correlation_token"]:
                raise ValueError("deletion authority does not match create intent")
            billing = authority.billing_started_monotonic
            if billing is None: raise ValueError("billing start is required for owned authority")
            billing_ns = int(_finite(billing, "billing start") * 1_000_000_000)
            if not self.contract.original_t0_monotonic_ns <= billing_ns <= self.contract.hard_deadline_monotonic_ns:
                raise ValueError("billing start is outside the original lifetime")
            value = {"schema_version":"episode1.cleanup-authority.v2", "plan_sha256":self.contract.plan_sha256,
                "private_id":private_id, "unique_name":name, "client_correlation_token":token,
                "billing_started_monotonic_ns":billing_ns,
                "original_t0_monotonic_ns":self.contract.original_t0_monotonic_ns,
                "hard_deadline_monotonic_ns":self.contract.hard_deadline_monotonic_ns,
                "teardown_deadline_monotonic_ns":self.contract.teardown_deadline_monotonic_ns,
                "clock_domain":self.contract.clock_domain, "boot_id":self.contract.boot_id}
            _atomic(self.directory / "cleanup-authority.json", canonical(value)+b"\n")
            self._cleanup_resource_identity_sha256=sha(canonical({
                "provider":"runpod-rest-v2", "private_id":private_id,
                "unique_name":name,
                "ownership_token_sha256":sha(token.encode()),
                "billing_started_monotonic":authority.billing_started_monotonic,
            }))
            self._ledger("deletion-authority-owned", {"authority_sha256":sha(canonical(value))})

    def start(
        self,
        allocation: Any,
        plan: Mapping[str, Any],
        *,
        cleanup_deadline_monotonic: int | float,
    ) -> None:
        with self._lock:
            authority = _load_json(self.directory / "cleanup-authority.json")
            if plan.get("plan_sha256") != self.contract.plan_sha256:
                raise ValueError("plan mismatch")
            if allocation.private_id != authority["private_id"] or allocation.unique_name != authority["unique_name"]:
                raise ValueError("allocation differs from durable deletion authority")
            resource=allocation.resource_identity_sha256
            immutable=allocation.immutable_allocation_sha256
            if not isinstance(resource,str) or HEX64.fullmatch(resource) is None or not isinstance(immutable,str) or HEX64.fullmatch(immutable) is None:
                raise ValueError("allocation promotion identities are invalid")
            if resource != self._cleanup_resource_identity_sha256:
                raise ValueError("allocation identity differs from durable cleanup authority")
            if _deadline_ns(cleanup_deadline_monotonic,"cleanup deadline") != self.contract.hard_deadline_monotonic_ns:
                raise ValueError("cleanup deadline must be the original hard deadline")
            billing=_finite(allocation.billing_started_monotonic,"billing start")
            billing_ns=int(billing*1_000_000_000)
            immutable_facts={
                "private_id":allocation.private_id,"unique_name":allocation.unique_name,
                "ssh_host":allocation.ssh_host,"ssh_public_port":allocation.ssh_public_port,
                "requested_image_reference":allocation.requested_image_reference,
                "provider_image_reference":allocation.provider_image_reference,
                "gpu":allocation.gpu,"gpu_count":allocation.gpu_count,
                "data_center_id":allocation.data_center_id,"cloud_type":allocation.cloud_type,
                "container_disk_gb":allocation.container_disk_gb,"volume_gb":allocation.volume_gb,
                "volume_mount_path":allocation.volume_mount_path,
                "container_ssh_port":allocation.container_ssh_port,
            }
            approved_digests={item["derived_image_digest"] for item in plan["runtime_builds"]}
            requested_ref=immutable_facts["requested_image_reference"]
            provider_ref=immutable_facts["provider_image_reference"]
            if (len(approved_digests)!=1 or not isinstance(requested_ref,str)
                    or not isinstance(provider_ref,str) or requested_ref!=provider_ref
                    or not requested_ref.endswith("@"+next(iter(approved_digests)))
                    or any(character.isspace() for character in requested_ref)
                    or requested_ref.count("@")!=1):
                raise ValueError("allocation image references do not bind the approved digest")
            for port_name in ("ssh_public_port","container_ssh_port"):
                port=immutable_facts[port_name]
                if isinstance(port,bool) or not isinstance(port,int) or not 1<=port<=65535:
                    raise ValueError("allocation SSH port is invalid")
            if sha(canonical(immutable_facts)) != immutable:
                raise ValueError("immutable allocation digest does not match allocation facts")
            token_sha=sha(authority["client_correlation_token"].encode("utf-8"))
            ownership=sha(canonical({"provider":"runpod-rest-v2","private_id":allocation.private_id,
                "unique_name":allocation.unique_name,"ownership_token_sha256":token_sha,
                "billing_started_monotonic_ns":billing_ns}))
            sanitized=_sealed_artifact({
                "schema_version":"episode1.sanitized-allocation-authority.v1",
                "run_id":self.contract.run_id,"attempt_id":self.contract.attempt_id,
                "plan_sha256":self.contract.plan_sha256,"provider":"runpod-rest-v2",
                "private_id":allocation.private_id,"unique_name":allocation.unique_name,
                "ownership_token_sha256":token_sha,
                "billing_started_monotonic":billing,
                "billing_started_monotonic_ns":billing_ns,
                "original_t0_monotonic_ns":self.contract.original_t0_monotonic_ns,
                "hard_deadline_monotonic_ns":self.contract.hard_deadline_monotonic_ns,
                "resource_identity_sha256":resource,
                "ownership_identity_sha256":ownership,
                "immutable_allocation":immutable_facts,
                "immutable_allocation_sha256":immutable,
            })
            _atomic(self.directory / "sanitized-allocation-authority.json",canonical(sanitized)+b"\n")
            self._resource_identity_sha256=resource
            self._ledger("allocation-owned", {"resource_identity_sha256":resource,
                "cleanup_deadline_monotonic_ns":self.contract.hard_deadline_monotonic_ns,
                "immutable_allocation_sha256":immutable,
                "allocation_authority_sha256":sanitized["artifact_sha256"]})

    def cleanup_attempt_observed(
        self, *, delete_attempt: int, operation: str, observation: Any | None,
        error_type: str | None,
    ) -> None:
        """Durably retain every cleanup call, including failures and false readbacks."""
        with self._lock:
            attempt=_integer(delete_attempt,"delete attempt",1)
            if operation not in {"delete","inventory","direct"}:
                raise ValueError("invalid cleanup operation")
            if (observation is None)==(error_type is None):
                raise ValueError("cleanup call must have exactly one result")
            detail: dict[str,Any]={"delete_attempt":attempt,"operation":operation}
            if error_type is not None:
                if not isinstance(error_type,str) or SAFE_ID.fullmatch(error_type) is None:
                    raise ValueError("invalid cleanup error type")
                detail.update(status="error",error_type=error_type)
            else:
                raw=observation.raw_bytes
                capture_input=observation.capture_input
                provider_artifact=observation.provider_artifact
                if not isinstance(raw,bytes) or len(raw)>16*1024*1024:
                    raise ValueError("cleanup response bytes must be bounded")
                if not isinstance(capture_input,Mapping) or not isinstance(provider_artifact,Mapping):
                    raise ValueError("cleanup observation is incomplete")
                digest=sha(raw)
                name=f"cleanup-attempt-{attempt}-{operation}-{digest}.bin"
                path=self.directory/name
                if not path.exists(): _atomic(path,raw)
                elif sha(path.read_bytes())!=digest: raise IntegrityError("cleanup artifact collision")
                detail.update(status="response",artifact=name,sha256=digest,bytes=len(raw),
                              capture_input=dict(capture_input),
                              provider_artifact=dict(provider_artifact))
            self._ledger("cleanup-attempt-observed",detail)

    def provider_failure_observed(self, observation: Any) -> None:
        """Durably retain one validated, explicitly non-promotable provider envelope."""
        with self._lock:
            raw=getattr(observation,"evidence_bytes",None)
            claimed=getattr(observation,"evidence_sha256",None)
            if not isinstance(raw,bytes) or len(raw)>16*1024*1024:
                raise ValueError("provider failure envelope must be bounded bytes")
            if not isinstance(claimed,str) or HEX64.fullmatch(claimed) is None or sha(raw)!=claimed:
                raise IntegrityError("provider failure envelope hash mismatch")
            value=_json_loads_strict(raw)
            if not isinstance(value,dict): raise IntegrityError("provider failure envelope is not an object")
            if value.get("schema_version") not in {
                "episode1.provider-cleanup-failure-call.v1",
                "episode1.provider-cleanup-failure-terminal.v1",
            }:
                raise IntegrityError("provider failure envelope schema is unsupported")
            if (value.get("run_id")!=self.contract.run_id or
                    value.get("attempt_id")!=self.contract.attempt_id or
                    value.get("plan_sha256")!=self.contract.plan_sha256 or
                    value.get("resource_identity_sha256")!=self._cleanup_resource_identity_sha256 or
                    value.get("absolute_deadline_monotonic_ns")!=self.contract.hard_deadline_monotonic_ns):
                raise IntegrityError("provider failure envelope capture binding mismatch")
            attempt=_integer(value.get("delete_attempt"),"delete attempt",1)
            operation={"delete_ack":"delete","inventory_read":"inventory",
                       "direct_read":"direct"}.get(value.get("kind"))
            if operation is None: raise IntegrityError("provider failure envelope kind is invalid")
            if value.get("artifact_sha256")!=sha(canonical({k:v for k,v in value.items()
                                                            if k!="artifact_sha256"})):
                raise IntegrityError("provider failure envelope artifact hash mismatch")
            name=f"cleanup-failure-{attempt}-{operation}-{claimed}.json"
            path=self.directory/name
            if not path.exists(): _atomic(path,raw+b"\n")
            elif _regular_file_bytes(path,name)!=raw+b"\n":
                raise IntegrityError("provider failure artifact collision")
            self._ledger("cleanup-attempt-observed",{
                "delete_attempt":attempt,"operation":operation,"status":"failed-evidence",
                "artifact":name,"sha256":claimed,"bytes":len(raw),
                "failure_schema":value["schema_version"],
                "failure_stage":value.get("failure_stage"),"promotable":False})

    def failed_telemetry_source(
        self, *, block_id: str, runtime: str, source_kind: str,
        source_bytes: bytes, reason: str,
    ) -> None:
        """Retain unfinished telemetry before fallible sampler teardown."""
        if (block_id,runtime) not in self.contract.blocks:
            raise ValueError("unknown telemetry block")
        if source_kind not in {"system_source_window","native"}:
            raise ValueError("invalid failed telemetry source kind")
        if not isinstance(source_bytes,bytes) or len(source_bytes)>16*1024*1024:
            raise ValueError("failed telemetry source bytes must be bounded")
        if not isinstance(reason,str) or SAFE_ID.fullmatch(reason) is None:
            raise ValueError("invalid failed telemetry reason")
        digest=sha(source_bytes)
        name=f"failed-telemetry-{block_id}-{source_kind}-{digest}.bin"
        with self._lock:
            path=self.directory/name
            if not path.exists(): _atomic(path,source_bytes)
            elif sha(path.read_bytes())!=digest: raise IntegrityError("failed telemetry artifact collision")
            self._ledger("failed-telemetry-source",{
                "block_id":block_id,"runtime":runtime,"source_kind":source_kind,
                "artifact":name,"sha256":digest,"bytes":len(source_bytes),"reason":reason,
            })

    def boundary(self, event: str, details: Mapping[str, Any]) -> None:
        if event not in CALLER_BOUNDARY_EVENTS:
            raise ValueError("event requires its dedicated evidence-producing method")
        with self._lock: self._ledger(event, details)

    def _provider_observation(self, role: str, raw_response: bytes,
                              evidence: Mapping[str, Any] | None = None) -> str:
        if role not in {"delete-response", "inventory-after-delete", "direct-after-delete",
                        "settlement-response"}:
            raise ValueError("provider observation role is not allowed")
        if not isinstance(raw_response, bytes) or len(raw_response) > 16 * 1024 * 1024:
            raise ValueError("provider response bytes must be bounded")
        evidence_copy=None
        if evidence is not None:
            if not isinstance(evidence, Mapping):
                raise ValueError("provider evidence must be an object")
            evidence_copy=dict(evidence)
            if len(canonical(evidence_copy)) > 20 * 1024 * 1024:
                raise ValueError("provider evidence must be bounded")
        elif role != "settlement-response":
            raise ValueError("cleanup provider evidence is required")
        digest = sha(raw_response)
        name = f"provider-{role}-{digest}.bin"
        path = self.directory / name
        if not path.exists(): _atomic(path, raw_response)
        elif sha(path.read_bytes()) != digest: raise IntegrityError("provider artifact collision")
        detail={"role":role,"artifact":name,"sha256":digest,"bytes":len(raw_response)}
        if evidence_copy is not None: detail["evidence"]=evidence_copy
        self._ledger("provider-observation", detail)
        return digest

    def deletion_verified(self, *, attempts: int, acknowledged: bool,
                          inventory_absent: bool, direct_not_found: bool,
                          attempt_evidence: Sequence[Mapping[str, Any]],
                          provider_evidence: Sequence[Mapping[str, Any]],
                          delete_response: bytes, inventory_response: bytes,
                          direct_response: bytes) -> None:
        """Bind cleanup facts to the actual retained provider response bytes."""
        with self._lock:
            attempts = _integer(attempts, "deletion attempts", 1)
            if any(x is not True for x in (acknowledged,inventory_absent,direct_not_found)):
                raise IncompleteEvidence("cleanup has not been verified")
            if len(provider_evidence)!=3:
                raise IntegrityError("cleanup needs exactly three typed provider artifacts")
            refs = {"delete":self._provider_observation("delete-response",delete_response,provider_evidence[0]),
                    "inventory":self._provider_observation("inventory-after-delete",inventory_response,provider_evidence[1]),
                    "direct":self._provider_observation("direct-after-delete",direct_response,provider_evidence[2])}
            if len(attempt_evidence)!=3: raise IntegrityError("successful cleanup attempt needs exactly three call observations")
            expected=(("delete_ack","acknowledged",None,None,refs["delete"]),
                      ("inventory_read","complete",True,True,refs["inventory"]),
                      ("direct_read","not_found",None,None,refs["direct"]))
            checked=[]; previous=self.contract.original_t0_monotonic_ns
            for raw,(kind,status,complete,absent,digest) in zip(attempt_evidence,expected,strict=True):
                if not isinstance(raw,Mapping): raise IntegrityError("provider call observation is not an object")
                item=dict(raw); _closed(item,{"schema_version","delete_attempt","kind","run_id","attempt_id",
                    "plan_sha256","resource_identity_sha256","observed_monotonic_ns",
                    "provider_response_sha256","status","complete","resource_absent"},"provider call observation")
                if (item["schema_version"]!="episode1.provider-call-observation.v1" or
                    item["delete_attempt"]!=attempts or item["kind"]!=kind or item["status"]!=status or
                    item["complete"] is not complete or item["resource_absent"] is not absent or
                    item["run_id"]!=self.contract.run_id or item["attempt_id"]!=self.contract.attempt_id or
                    item["plan_sha256"]!=self.contract.plan_sha256 or
                    item["resource_identity_sha256"]!=self._cleanup_resource_identity_sha256 or
                    item["provider_response_sha256"]!=digest):
                    raise IntegrityError("provider call observation binding or result mismatch")
                when=_integer(item["observed_monotonic_ns"],"provider observation time",1)
                if when<=previous or when>self.contract.hard_deadline_monotonic_ns:
                    raise IntegrityError("provider call observations are stale, reordered, or after deadline")
                previous=when; checked.append(item)
            if self._last_mono<=previous:
                raise IntegrityError("cleanup evidence persistence predates a provider observation")
            self._ledger("deletion-verified", {"attempts":attempts,"acknowledged":True,
                "inventory_absent":True,"direct_not_found":True,
                "attempt_evidence":checked,"artifact_sha256":refs})

    def settlement_observed(self, *, status: str, response: bytes,
                            observed_total_usd: str|None = None,
                            reason: str|None = None) -> None:
        """Record a real bounded settlement readback; provisional remains explicit."""
        if status not in {"settled", "provisional"}: raise ValueError("invalid settlement status")
        if status=="settled":
            if not isinstance(observed_total_usd,str) or reason is not None:
                raise ValueError("settled cost requires an actual decimal string and no reason")
        elif observed_total_usd is not None or reason not in {"pending_provider_settlement","provider_billing_unavailable"}:
            raise ValueError("provisional cost requires a fixed unavailable reason")
        with self._lock:
            digest=self._provider_observation("settlement-response",response)
            self._ledger("provider-settlement-observed", {"status":status,"source_sha256":digest,
                "observed_total_usd":observed_total_usd,"reason":reason})

    def block_complete(self, block_id: str, runtime: str, *, descendants_absent: bool,
                       memory_recovered: bool, startup_attempt_id_sha256: str,
                       process_identity_sha256: str) -> None:
        if (block_id, runtime) not in self.contract.blocks: raise ValueError("unknown block")
        if descendants_absent is not True or memory_recovered is not True:
            raise IncompleteEvidence("block cleanup checks did not both pass")
        for value in (startup_attempt_id_sha256,process_identity_sha256):
            if not isinstance(value,str) or HEX64.fullmatch(value) is None: raise ValueError("invalid process evidence hash")
        if self._resource_identity_sha256 is None: raise CaptureError("allocation has not started")
        with self._lock: self._ledger("block-stop", {"resource_identity_sha256":self._resource_identity_sha256,
            "block_id":block_id,"startup_attempt_id_sha256":startup_attempt_id_sha256,
            "process_identity_sha256":process_identity_sha256,"descendants_absent":True,
            "gpu_memory_recovered":True})

    def block_start(self, block_id: str, runtime: str, *, block_attempt: int,
                    startup_attempt_id_sha256: str, process_id_sha256: str,
                    process_start_identity_sha256: str, image_digest: str) -> None:
        if (block_id,runtime) not in self.contract.blocks or self._resource_identity_sha256 is None:
            raise ValueError("block start binding mismatch")
        _integer(block_attempt,"block attempt",1)
        for value in (startup_attempt_id_sha256,process_id_sha256,process_start_identity_sha256):
            if not isinstance(value,str) or HEX64.fullmatch(value) is None: raise ValueError("invalid process evidence hash")
        if not isinstance(image_digest,str) or re.fullmatch(r"sha256:[0-9a-f]{64}",image_digest) is None:
            raise ValueError("invalid image digest")
        with self._lock: self._ledger("block-start",{"resource_identity_sha256":self._resource_identity_sha256,
            "block_id":block_id,"runtime":runtime,"block_attempt":block_attempt,
            "startup_attempt_id_sha256":startup_attempt_id_sha256,"process_id_sha256":process_id_sha256,
            "process_start_identity_sha256":process_start_identity_sha256,"image_digest":image_digest})

    def startup_failed(self, block_id: str, runtime: str, *, block_attempt: int,
                       startup_attempt_id_sha256: str, process_identity_sha256: str,
                       failure_stage: str) -> None:
        if self._resource_identity_sha256 is None or (block_id,runtime) not in self.contract.blocks:
            raise ValueError("failed startup binding mismatch")
        if failure_stage not in {"runtime_start","readiness_probe"}: raise ValueError("invalid failure stage")
        with self._lock: self._ledger("startup-failed",{"resource_identity_sha256":self._resource_identity_sha256,
            "block_id":block_id,"runtime":runtime,"block_attempt":_integer(block_attempt,"block attempt",1),
            "startup_attempt_id_sha256":startup_attempt_id_sha256,
            "process_identity_sha256":process_identity_sha256,"failure_stage":failure_stage,
            "warmup_records":0,"measured_records":0})

    def failed_start_cleanup(self, block_id: str, runtime: str, *, block_attempt: int,
                             startup_attempt_id_sha256: str, process_identity_sha256: str,
                             descendants_absent: bool, memory_recovered: bool) -> None:
        if self._resource_identity_sha256 is None or (block_id,runtime) not in self.contract.blocks:
            raise ValueError("failed startup cleanup binding mismatch")
        if descendants_absent is not True or memory_recovered is not True:
            raise IncompleteEvidence("failed startup cleanup checks did not both pass")
        with self._lock: self._ledger("failed-start-cleanup",{"resource_identity_sha256":self._resource_identity_sha256,
            "block_id":block_id,"runtime":runtime,"block_attempt":_integer(block_attempt,"block attempt",1),
            "startup_attempt_id_sha256":startup_attempt_id_sha256,"process_identity_sha256":process_identity_sha256,
            "descendants_absent":True,"gpu_memory_recovered":True})

    def cell_complete(self, block_id: str, cell_id: str, *, warmup: bool,
                      startup_attempt_id_sha256: str, process_identity_sha256: str) -> None:
        if self._resource_identity_sha256 is None: raise CaptureError("allocation has not started")
        records,_=_read_stream(self.directory/"requests.jsonl","episode1.requests-stream.v2")
        group=[x for x in records if x.get("block_id")==block_id and x.get("cell_id")==cell_id and x.get("warmup") is warmup]
        key=f"{block_id}|{cell_id}|{1 if warmup else 0}"
        expected=self.contract.request_counts.get(key)
        if expected is None or len(group)!=expected: raise IncompleteEvidence("cell records are incomplete")
        group.sort(key=lambda x:x.get("scheduled_order"))
        if [x.get("scheduled_order") for x in group] != list(range(1,expected+1)):
            raise IncompleteEvidence("cell scheduled orders are incomplete or duplicated")
        failed=sum(1 for x in group if x.get("status")!="success")
        if failed: raise IncompleteEvidence("cell contains failed requests and cannot be completed")
        for value in (startup_attempt_id_sha256,process_identity_sha256):
            if not isinstance(value,str) or HEX64.fullmatch(value) is None: raise ValueError("invalid process evidence hash")
        details={"resource_identity_sha256":self._resource_identity_sha256,"block_id":block_id,
            "cell_id":cell_id,"scheduled":expected,"failed":failed,"records_sha256":sha(canonical(group)),
            "startup_attempt_id_sha256":startup_attempt_id_sha256,"process_identity_sha256":process_identity_sha256}
        with self._lock: self._ledger("warmup-complete" if warmup else "cell-complete",details)

    def request(self, value: Mapping[str, Any]) -> None:
        with self._lock:
            if self._closed: raise CaptureError("capture is closed")
            checked = dict(self.observation_validator(value))
            if checked.get("evidence_class") != "provider_candidate": raise ValueError("request is not provider_candidate")
            checked.pop("derived", None)
            self._stream_record("requests", checked)

    def request_lifecycle(self, value: Mapping[str, Any]) -> None:
        """Durably retain the pre-transport request state machine."""
        keys={"schema_version","request_id","block_id","cell_id","scheduled_order",
              "clock_domain","stage","at_ns"}
        item=dict(value); _closed(item,keys,"request lifecycle")
        if item["schema_version"]!="episode1.request-lifecycle.v1":
            raise ValueError("request lifecycle schema is unsupported")
        if item["clock_domain"]!="client_monotonic_ns" or item["stage"] not in {
            "scheduled","dispatched","finalized"}:
            raise ValueError("request lifecycle clock domain or stage is invalid")
        for name in ("request_id","block_id","cell_id"):
            if not isinstance(item[name],str) or not item[name] or len(item[name])>256 or any(
                ord(character)<32 for character in item[name]
            ): raise ValueError(f"request lifecycle {name} is invalid")
        order=_integer(item["scheduled_order"],"scheduled order",1)
        at_ns=_integer(item["at_ns"],"request lifecycle timestamp",0)
        with self._lock:
            request_id=item["request_id"]; identity=(item["block_id"],item["cell_id"],order)
            prior=self._request_lifecycle.get(request_id)
            if prior is None:
                if item["stage"]!="scheduled": raise ValueError("request lifecycle must begin scheduled")
            else:
                if identity!=prior[:3]: raise ValueError("request lifecycle identity changed")
                allowed={"scheduled":{"dispatched","finalized"},"dispatched":{"finalized"},
                         "finalized":set()}[prior[3]]
                if item["stage"] not in allowed or at_ns < prior[4]:
                    raise ValueError("request lifecycle transition or timestamp is invalid")
            self._stream_record("request-lifecycle",item)
            self._request_lifecycle[request_id]=(*identity,item["stage"],at_ns)

    def telemetry(self, value: Mapping[str, Any]) -> None:
        keys = {"plan_sha256","block_id","runtime","series"}; _closed(value, keys, "telemetry block")
        if value["plan_sha256"] != self.contract.plan_sha256 or (value["block_id"],value["runtime"]) not in self.contract.blocks:
            raise ValueError("telemetry binding mismatch")
        series = value["series"]
        if not isinstance(series, Sequence) or isinstance(series, (str,bytes)): raise ValueError("series must be a sequence")
        seen=set(); retained=[]
        for item in series:
            keys={"series_id","source_kind","metric_name","kind","status","value","unavailable_reason",
                  "expected_samples","observed_samples","missing_samples","labels","window","source_bytes"}
            _closed(item,keys,"telemetry series")
            sid=item["series_id"]
            if sid not in self.contract.telemetry_series or sid in seen: raise ValueError("unexpected/duplicate telemetry series")
            seen.add(sid)
            if not isinstance(item["metric_name"],str) or not item["metric_name"] or item["kind"] not in {"counter","gauge"}:
                raise ValueError("invalid telemetry metric identity")
            source=item["source_bytes"]
            if not isinstance(source,bytes) or not source or len(source)>16*1024*1024:
                raise ValueError("telemetry source bytes must be nonempty and bounded")
            if not isinstance(item["labels"],Mapping) or not isinstance(item["window"],Mapping):
                raise ValueError("telemetry source selector is invalid")
            if item["source_kind"]=="native":
                derived,digest=_native_source_summary(source,run_id=self.contract.run_id,
                    attempt_id=self.contract.attempt_id,block=value["block_id"],runtime=value["runtime"],
                    clock_domain=self.contract.clock_domain,metric_name=item["metric_name"],
                    kind=item["kind"],labels=item["labels"],window=item["window"])
            elif item["source_kind"]=="system_source_window":
                _closed(item["window"],{"start_receipt","end_receipt","pid","start_ticks",
                    "max_sampling_gap_ns","first_measured_a_ns","last_measured_end_ns"},"system source window")
                derived=summarize_system_source_window(source=source,
                    start_receipt=item["window"]["start_receipt"],end_receipt=item["window"]["end_receipt"],
                    plan_sha256=self.contract.plan_sha256,run_id=self.contract.run_id,
                    attempt_id=self.contract.attempt_id,block=value["block_id"],runtime=value["runtime"],
                    pid=item["window"]["pid"],start_ticks=item["window"]["start_ticks"],
                    metric_name=item["metric_name"],kind=item["kind"],labels=item["labels"],
                    max_sampling_gap_ns=item["window"]["max_sampling_gap_ns"],
                    first_measured_a_ns=item["window"]["first_measured_a_ns"],
                    last_measured_end_ns=item["window"]["last_measured_end_ns"])
                digest=derived["samples_sha256"]
            elif item["source_kind"]=="system":
                derived,digest=_system_source_summary(source,run_id=self.contract.run_id,
                    attempt_id=self.contract.attempt_id,block=value["block_id"],runtime=value["runtime"],
                    clock_domain=self.contract.clock_domain,
                    metric_name=item["metric_name"],kind=item["kind"],labels=item["labels"],window=item["window"])
            else: raise ValueError("telemetry source_kind is invalid")
            claimed={key:item[key] for key in ("metric_name","kind","status","value","unavailable_reason",
                "expected_samples","observed_samples","missing_samples")}
            recomputed={key:derived[key] for key in claimed}
            if claimed!=recomputed: raise IntegrityError("telemetry summary differs from retained native samples")
            name=f"telemetry-{value['block_id']}-{sid}-{digest}.bin"
            path=self.directory/name
            if not path.exists(): _atomic(path,source)
            elif sha(path.read_bytes())!=digest: raise IntegrityError("telemetry source collision")
            retained_item={key:item[key] for key in keys-{"source_bytes"}}|{"samples_sha256":digest}
            if item["kind"]=="counter" and item["source_kind"]!="system_source_window":
                retained_item.update({key:derived[key] for key in COUNTER_PROJECTION_KEYS})
            if item["source_kind"]=="system_source_window":
                retained_item["observation_window"]=derived["observation_window"]
            retained.append(retained_item)
        if seen != set(self.contract.telemetry_series): raise ValueError("telemetry series set incomplete")
        stored={"plan_sha256":value["plan_sha256"],"block_id":value["block_id"],
                "runtime":value["runtime"],"series":retained}
        with self._lock: self._stream_record("telemetry", stored)

    def system_source(self, value: Mapping[str, Any]) -> None:
        """Durably retain one exact remote system record before caller acceptance."""
        if not isinstance(value, Mapping):
            raise ValueError("system source evidence must be an object")
        item = dict(value)
        _closed(item, SYSTEM_SOURCE_PAYLOAD_KEYS, "system source evidence")
        if item["schema_version"] != "episode1.system-source-evidence.v1":
            raise ValueError("system source evidence schema is unsupported")
        block_runtime = (item["block_id"], item["runtime"])
        block_attempt = _integer(item["block_attempt"], "system source block attempt", 1)
        expected_startup_attempt = f"{item['block_id']}-attempt-{block_attempt}"
        if (item["plan_sha256"] != self.contract.plan_sha256
                or block_runtime not in self.contract.blocks
                or item["run_attempt_id"] != self.contract.attempt_id
                or item["startup_attempt_id"] != expected_startup_attempt):
            raise ValueError("system source evidence binding mismatch")
        if not all(isinstance(item[name], str) and SAFE_ID.fullmatch(item[name])
                   for name in ("block_id", "runtime", "run_attempt_id", "startup_attempt_id")):
            raise ValueError("system source evidence identity is invalid")
        record = item["record"]
        if not isinstance(record, Mapping):
            raise ValueError("system source record must be an object")
        item["record"] = dict(record)
        encoded = canonical(item["record"]) + b"\n"
        if not isinstance(item["source_sha256"], str) or sha(encoded) != item["source_sha256"]:
            raise IntegrityError("system source record hash mismatch")
        binding = item["record"].get("binding")
        if (not isinstance(binding, Mapping)
                or binding.get("run_id") != self.contract.run_id
                or binding.get("attempt_id") != item["run_attempt_id"]
                or binding.get("block") != item["block_id"]):
            raise ValueError("system source record binding mismatch")
        key = (item["block_id"], item["runtime"], item["run_attempt_id"],
               item["startup_attempt_id"])
        with self._lock:
            if self._closed:
                raise CaptureError("capture is closed")
            if self._stream["system-source"][0] >= MAX_SYSTEM_SOURCE_RECORDS:
                raise ValueError("system source evidence exceeds its record bound")
            total = self._system_source_bytes.get(key, 0) + len(encoded)
            if total > MAX_SYSTEM_SOURCE_BYTES_PER_BLOCK:
                raise ValueError("system source evidence exceeds its per-block retention bound")
            self._stream_record("system-source", item)
            self._system_source_bytes[key] = total

    def export_essential(self, *, deadline_monotonic: float) -> None:
        with self._lock:
            deadline_ns=_deadline_ns(deadline_monotonic,"export deadline")
            if deadline_ns>self.contract.hard_deadline_monotonic_ns: raise ValueError("export deadline exceeds original hard deadline")
            def before_deadline() -> None:
                if self._times()[0] >= deadline_ns: raise TimeoutError("export deadline reached")
            before_deadline()
            if self._resource_identity_sha256 is None: raise CaptureError("allocation has not started")
            requests,_=_read_stream(self.directory/"requests.jsonl","episode1.requests-stream.v2")
            lifecycle,_=_read_stream(self.directory/"request-lifecycle.jsonl",
                                     "episode1.request-lifecycle-stream.v2")
            _verify_request_lifecycle(lifecycle,requests)
            before_deadline()
            telemetry,_=_read_stream(self.directory/"telemetry.jsonl","episode1.telemetry-stream.v2")
            _verify_telemetry_sources(self.directory,telemetry)
            before_deadline()
            records_artifact=_sealed_artifact({"schema_version":"episode1.private-records.v1",
                "run_id":self.contract.run_id,"attempt_id":self.contract.attempt_id,
                "plan_sha256":self.contract.plan_sha256,"records":requests})
            summaries=[]
            for block in telemetry:
                for item in block["series"]:
                    summary={"block_id":block["block_id"],"runtime":block["runtime"],
                        **{k:item[k] for k in ("series_id","source_kind","metric_name","kind","labels",
                            "status","value","unavailable_reason",
                            "expected_samples","observed_samples","missing_samples","samples_sha256")}}
                    if item["kind"]=="counter" and item["source_kind"]!="system_source_window":
                        summary.update({key:item[key] for key in COUNTER_PROJECTION_KEYS})
                    if item["source_kind"]=="system_source_window":
                        summary.update(observation_window=item["observation_window"])
                    summaries.append(summary)
            telemetry_artifact=_sealed_artifact({"schema_version":"episode1.private-telemetry.v1",
                "run_id":self.contract.run_id,"attempt_id":self.contract.attempt_id,
                "plan_sha256":self.contract.plan_sha256,"summaries":summaries})
            _atomic(self.directory/"promotion-records.json",canonical(records_artifact)+b"\n")
            before_deadline()
            _atomic(self.directory/"promotion-telemetry.json",canonical(telemetry_artifact)+b"\n")
            before_deadline()
            export_dir=self.directory/"essential-export-files"
            _safe_new_directory(export_dir)
            files={}
            for path in sorted(self.directory.iterdir(),key=lambda p:p.name):
                before_deadline()
                if not path.is_file() or path.name=="essential-export.json" or path.name.startswith("."):
                    continue
                data=_regular_file_bytes(path,path.name); before_deadline(); _atomic(export_dir/path.name,data); before_deadline()
                files[path.name]={"bytes":len(data),"sha256":sha(data)}
            manifest={"schema_version":"episode1.essential-export.v2","plan_sha256":self.contract.plan_sha256,
                "files":files,"ledger_head_before_export":self._ledger_prev}
            _atomic(self.directory/"essential-export.json",canonical(manifest)+b"\n")
            before_deadline()
            verify_essential_export(self.directory,expected_plan_sha256=self.contract.plan_sha256,
                                    require_ledger_binding=False)
            before_deadline()
            self._ledger("essential-export-complete", {"resource_identity_sha256":self._resource_identity_sha256,
                "records_sha256":records_artifact["artifact_sha256"],
                "telemetry_sha256":telemetry_artifact["artifact_sha256"],
                "manifest_sha256":sha(canonical(manifest))})

    def close(self) -> None:
        with self._lock:
            if self._closed: return
            identity=self._resource_identity_sha256 or self._cleanup_resource_identity_sha256
            if identity is None: raise CaptureError("cleanup authority has not been established")
            if not self._seal_pending:
                self._ledger("capture-closed", {"resource_identity_sha256":identity})
                self._seal_pending=True
            seal={"schema_version":"episode1.capture-seal.v2","plan_sha256":self.contract.plan_sha256,
                "ledger_records":self._ledger_seq,"ledger_head_sha256":self._ledger_prev,
                "request_records":self._stream["requests"][0],"request_head_sha256":self._stream["requests"][1],
                "request_lifecycle_records":self._stream["request-lifecycle"][0],
                "request_lifecycle_head_sha256":self._stream["request-lifecycle"][1],
                "telemetry_records":self._stream["telemetry"][0],"telemetry_head_sha256":self._stream["telemetry"][1],
                "system_source_records":self._stream["system-source"][0],
                "system_source_head_sha256":self._stream["system-source"][1]}
            _atomic(self.directory/"capture-seal.json",canonical(seal)+b"\n")
            self._closed=True

    def assemble_promotion_bundle(self, *, plan: Mapping[str,Any],
                                  sources: Mapping[str,Any], approval: Mapping[str,Any],
                                  image_digest: str) -> dict[str,Any]:
        if not self._closed: raise IncompleteEvidence("capture is not closed")
        if self._resource_identity_sha256 is None:
            raise IncompleteEvidence("allocation never reached the promotion-owned state")
        return assemble_promotion_bundle(self.directory,self.contract,plan=plan,
            sources=sources,approval=approval,image_digest=image_digest,
            validator=self.observation_validator)


def _load_json(path: Path) -> dict[str, Any]:
    try: value=_json_loads_strict(path.read_bytes())
    except (OSError,IntegrityError) as exc: raise IntegrityError(f"invalid {path.name}") from exc
    if not isinstance(value,dict): raise IntegrityError(f"{path.name} is not an object")
    return value


def _parse_stream(content: bytes, name: str, schema: str) -> tuple[list[dict[str,Any]],str]:
    values=[]; previous=ZERO
    if content and not content.endswith(b"\n"): raise IntegrityError(f"torn {name}")
    lines=content.splitlines()
    for seq,line in enumerate(lines,1):
        try: entry=_json_loads_strict(line)
        except IntegrityError as exc: raise IntegrityError(f"corrupt {name}") from exc
        _closed(entry,STREAM_KEYS,name)
        if entry["schema_version"] != schema or entry["sequence"] != seq or entry["previous_sha256"] != previous:
            raise IntegrityError(f"broken {name} chain")
        if sha(canonical(entry["payload"])) != entry["payload_sha256"]: raise IntegrityError("payload hash mismatch")
        bare={k:v for k,v in entry.items() if k!="record_sha256"}
        if sha(canonical(bare)) != entry["record_sha256"]: raise IntegrityError("stream hash mismatch")
        previous=entry["record_sha256"]; values.append(entry["payload"])
    return values,previous


def _read_stream(path: Path, schema: str) -> tuple[list[dict[str,Any]],str]:
    try: content=path.read_bytes()
    except OSError as exc: raise IntegrityError(f"cannot read {path.name}") from exc
    return _parse_stream(content,path.name,schema)


def _read_bounded_system_source_stream(
    directory: Path, contract: RunContract,
) -> tuple[list[dict[str, Any]], str]:
    """Read, chain-check and bind the raw stream once through its opened file."""
    path = directory / "system-source.jsonl"
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try: descriptor = os.open(path, flags)
    except OSError as exc: raise IntegrityError("cannot open system source stream") from exc
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_size > MAX_SYSTEM_SOURCE_STREAM_BYTES):
            raise IntegrityError("system source stream file is invalid or exceeds its bound")
        chunks=[]; total=0
        while True:
            chunk=os.read(descriptor,min(64*1024,MAX_SYSTEM_SOURCE_STREAM_BYTES+1-total))
            if not chunk: break
            chunks.append(chunk); total+=len(chunk)
            if total>MAX_SYSTEM_SOURCE_STREAM_BYTES:
                raise IntegrityError("system source stream exceeds its byte bound")
        after=os.fstat(descriptor)
        stable_before=(before.st_dev,before.st_ino,before.st_mode,before.st_nlink,before.st_size,
                       before.st_mtime_ns,before.st_ctime_ns)
        stable_after=(after.st_dev,after.st_ino,after.st_mode,after.st_nlink,after.st_size,
                      after.st_mtime_ns,after.st_ctime_ns)
        if (not stat.S_ISREG(after.st_mode) or after.st_nlink != 1
                or stable_before != stable_after or total != after.st_size):
            raise IntegrityError("system source stream changed while being read")
    except OSError as exc:
        raise IntegrityError("cannot read system source stream") from exc
    finally:
        os.close(descriptor)
    values,head=_parse_stream(b"".join(chunks),path.name,"episode1.system-source-stream.v2")
    if len(values) > MAX_SYSTEM_SOURCE_RECORDS:
        raise IntegrityError("system source stream exceeds its record bound")
    totals: dict[tuple[str, str, str, str], int] = {}
    checked: list[dict[str, Any]] = []
    for raw in values:
        if not isinstance(raw, dict): raise IntegrityError("system source stream payload is not an object")
        if set(raw) != SYSTEM_SOURCE_PAYLOAD_KEYS:
            raise IntegrityError("system source evidence fields are not closed")
        if not all(isinstance(raw.get(name), str) and SAFE_ID.fullmatch(raw[name])
                   for name in ("block_id", "runtime", "run_attempt_id", "startup_attempt_id")):
            raise IntegrityError("system source stream identity is invalid")
        if (isinstance(raw["block_attempt"], bool)
                or not isinstance(raw["block_attempt"], int)
                or raw["block_attempt"] <= 0):
            raise IntegrityError("system source block attempt is invalid")
        block_attempt = raw["block_attempt"]
        expected_startup_attempt = f"{raw['block_id']}-attempt-{block_attempt}"
        if (raw["schema_version"] != "episode1.system-source-evidence.v1"
                or raw["plan_sha256"] != contract.plan_sha256
                or (raw["block_id"], raw["runtime"]) not in contract.blocks
                or raw["run_attempt_id"] != contract.attempt_id
                or raw["startup_attempt_id"] != expected_startup_attempt):
            raise IntegrityError("system source stream binding mismatch")
        record = raw["record"]
        if not isinstance(record, dict): raise IntegrityError("system source stream record is not an object")
        binding = record.get("binding")
        if (not isinstance(binding, Mapping)
                or binding.get("run_id") != contract.run_id
                or binding.get("attempt_id") != raw["run_attempt_id"]
                or binding.get("block") != raw["block_id"]):
            raise IntegrityError("system source record binding mismatch")
        encoded = canonical(record) + b"\n"
        if not isinstance(raw["source_sha256"], str) or sha(encoded) != raw["source_sha256"]:
            raise IntegrityError("system source stream record hash mismatch")
        key = (raw["block_id"], raw["runtime"], raw["run_attempt_id"],
               raw["startup_attempt_id"])
        totals[key] = totals.get(key, 0) + len(encoded)
        if totals[key] > MAX_SYSTEM_SOURCE_BYTES_PER_BLOCK:
            raise IntegrityError("system source stream exceeds its per-block retention bound")
        checked.append(raw)
    return checked,head


def load_retained_system_sources(directory: Path, contract: RunContract) -> list[dict[str, Any]]:
    """Reopen and verify raw system records, including failed-attempt evidence."""
    values,_=_read_bounded_system_source_stream(directory,contract)
    return values


def _verify_system_source_startup_attempts(
    values: Sequence[Mapping[str, Any]],
    ledger: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]],
) -> None:
    """Bind every retained startup stream to its terminal startup ledger fact."""
    retained_attempts = {
        (str(value["block_id"]), str(value["runtime"]), int(value["block_attempt"]),
         str(value["startup_attempt_id"]))
        for value in values
    }
    if not retained_attempts:
        return
    ledger_attempts: set[tuple[str, str, int, str]] = set()
    for entry, details in ledger:
        if entry.get("event") not in {"block-start", "startup-failed"}:
            continue
        block_id, runtime = details.get("block_id"), details.get("runtime")
        block_attempt = details.get("block_attempt")
        if (not isinstance(block_id, str) or not isinstance(runtime, str)
                or isinstance(block_attempt, bool) or not isinstance(block_attempt, int)
                or block_attempt <= 0):
            raise IntegrityError("startup ledger attempt identity is invalid")
        startup_attempt_id = f"{block_id}-attempt-{block_attempt}"
        identity = (block_id, runtime, block_attempt, startup_attempt_id)
        if identity not in retained_attempts:
            continue
        if details.get("startup_attempt_id_sha256") != sha(startup_attempt_id.encode()):
            raise IntegrityError("startup ledger attempt hash mismatch")
        ledger_attempts.add(identity)
    if not retained_attempts <= ledger_attempts:
        raise IntegrityError("retained system source lacks its startup ledger binding")


def _verify_request_lifecycle(lifecycle: Sequence[Mapping[str,Any]],
                              requests: Sequence[Mapping[str,Any]]) -> None:
    states: dict[str, tuple[str,str,int,str,int]]={}
    stage_times: dict[str, dict[str,int]]={}
    for raw in lifecycle:
        item=dict(raw); _closed(item,{"schema_version","request_id","block_id","cell_id",
            "scheduled_order","clock_domain","stage","at_ns"},"request lifecycle")
        if item["schema_version"]!="episode1.request-lifecycle.v1" or item["clock_domain"]!="client_monotonic_ns":
            raise IntegrityError("request lifecycle binding is invalid")
        request_id=item["request_id"]; identity=(item["block_id"],item["cell_id"],item["scheduled_order"])
        if not isinstance(request_id,str) or not request_id or any(not isinstance(x,str) for x in identity[:2]):
            raise IntegrityError("request lifecycle identity is invalid")
        try:
            _integer(identity[2],"scheduled order",1); at_ns=_integer(item["at_ns"],"request lifecycle timestamp",0)
        except ValueError as exc: raise IntegrityError("request lifecycle numeric field is invalid") from exc
        prior=states.get(request_id)
        if prior is None:
            if item["stage"]!="scheduled": raise IntegrityError("request lifecycle did not begin scheduled")
        else:
            if identity!=prior[:3]: raise IntegrityError("request lifecycle identity changed")
            allowed={"scheduled":{"dispatched","finalized"},"dispatched":{"finalized"},
                     "finalized":set()}.get(prior[3],set())
            if item["stage"] not in allowed or at_ns < prior[4]:
                raise IntegrityError("request lifecycle transition or timestamp is invalid")
        states[request_id]=(*identity,item["stage"],at_ns)
        stage_times.setdefault(request_id,{})[item["stage"]]=at_ns
    request_by_id={item.get("request_id"):item for item in requests}
    if len(request_by_id)!=len(requests) or set(states)!=set(request_by_id):
        raise IncompleteEvidence("request lifecycle and terminal records differ")
    for request_id,state in states.items():
        record=request_by_id[request_id]
        if state[3]!="finalized" or state[:3]!=(record.get("block_id"),record.get("cell_id"),record.get("scheduled_order")):
            raise IncompleteEvidence("request lifecycle is pending or differs from terminal record")
        stages=stage_times[request_id]
        if stages.get("scheduled") != record.get("a_ns") or stages.get("finalized") != record.get("end_ns"):
            raise IntegrityError("request lifecycle timestamps differ from the terminal record")
        dispatched=record.get("b_ns")
        if dispatched is None:
            if record.get("status") != "unsent" or "dispatched" in stages:
                raise IntegrityError("only an unsent request may omit dispatch lifecycle evidence")
        elif stages.get("dispatched") != dispatched:
            raise IntegrityError("request dispatch lifecycle evidence is missing or mismatched")


def _read_ledger(directory: Path, *, tolerate_tail: bool=False) -> tuple[list[tuple[dict[str,Any],dict[str,Any]]],str,str]:
    result=[]; previous=ZERO; integrity="complete"
    try: content=(directory/"lifecycle.jsonl").read_bytes()
    except OSError as exc: raise IntegrityError("missing lifecycle ledger") from exc
    torn=bool(content and not content.endswith(b"\n"))
    lines=content.splitlines()
    if torn:
        if not tolerate_tail: raise IntegrityError("ledger has a torn final record")
        lines=lines[:-1]; integrity="corrupt_tail"
    for seq,line in enumerate(lines,1):
        try:
            entry=_json_loads_strict(line); _closed(entry,LEDGER_KEYS,"ledger")
            if entry["schema_version"]!="episode1.private-ledger.v2" or entry["sequence"]!=seq or entry["previous_sha256"]!=previous: raise IntegrityError("broken ledger chain")
            if entry["event"] not in ALLOWED_EVENTS: raise IntegrityError("unknown ledger event")
            bare={k:v for k,v in entry.items() if k!="record_sha256"}
            if sha(canonical(bare))!=entry["record_sha256"]: raise IntegrityError("ledger hash mismatch")
            detail_path=directory/f"event-{seq:06d}-{entry['details_sha256']}.json"
            detail=_load_json(detail_path)
            if sha(canonical(detail))!=entry["details_sha256"]: raise IntegrityError("detail hash mismatch")
        except (ValueError,IntegrityError,TypeError,KeyError):
            if tolerate_tail: integrity="corrupt_tail"; break
            raise IntegrityError(f"ledger corrupt at sequence {seq}")
        result.append((entry,detail)); previous=entry["record_sha256"]
    return result,previous,integrity


def _regular_file_bytes(path: Path, name: str) -> bytes:
    try:
        info=os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise IntegrityError(f"{name} is not a singly linked regular file")
        return path.read_bytes()
    except OSError as exc:
        raise IntegrityError(f"cannot read {name}") from exc


def _telemetry_process_start(source: bytes, item: Mapping[str,Any]) -> tuple[int,int]:
    """Return the exact Linux PID/start-ticks selected by one source."""
    if item["source_kind"]=="native":
        try:
            first=_json_loads_strict(source.splitlines(keepends=True)[0])
            binding=first["binding"]
            process=binding["process_identity"]
            started=binding["process_start_identity"]
        except (IndexError,KeyError,TypeError) as exc:
            raise IntegrityError("native telemetry process binding is missing") from exc
        process_match=re.fullmatch(r"pid:([1-9][0-9]*)",process) if isinstance(process,str) else None
        started_match=re.fullmatch(r"ticks:([1-9][0-9]*)",started) if isinstance(started,str) else None
        if process_match is None or started_match is None:
            raise IntegrityError("native telemetry process binding is not a PID/start identity")
        return int(process_match.group(1)),int(started_match.group(1))
    selector=item["window"]
    try:
        pid=_integer(selector["pid"],"telemetry process PID",1)
        ticks=_integer(selector["start_ticks"],"telemetry process start ticks",1)
    except (KeyError,ValueError,TypeError) as exc:
        raise IntegrityError("system telemetry process binding is invalid") from exc
    return pid,ticks


def _verify_telemetry_ledger_processes(
    bindings: Mapping[tuple[str,str],tuple[int,int]],
    ledger: Sequence[tuple[Mapping[str,Any],Mapping[str,Any]]],
) -> None:
    """Bind each successful source to the successful block-start process."""
    active: dict[str,tuple[str,str]]={}
    successful: dict[tuple[str,str],str]={}
    for entry,detail in ledger:
        event=entry.get("event")
        block=detail.get("block_id") if isinstance(detail,Mapping) else None
        if event=="block-start":
            runtime=detail.get("runtime")
            process_start=detail.get("process_start_identity_sha256")
            if (not isinstance(block,str) or not isinstance(runtime,str)
                    or not isinstance(process_start,str) or HEX64.fullmatch(process_start) is None
                    or block in active):
                raise IntegrityError("block-start process identity is invalid")
            active[block]=(runtime,process_start)
        elif event=="failed-start-cleanup":
            if not isinstance(block,str):
                raise IntegrityError("failed startup block identity is invalid")
            # The orchestrator records block-start only after readiness succeeds.
            # A failed pre-readiness attempt therefore has no active block-start
            # identity to remove.  Tolerate that exact case; if an older stream
            # did record the failed start, discard it before the retry.
            active.pop(block,None)
        elif event=="block-stop":
            current=active.pop(block,None) if isinstance(block,str) else None
            if current is None:
                raise IntegrityError("successful block has no active process identity")
            runtime,process_start=current
            key=(block,runtime)
            if key in successful:
                raise IntegrityError("successful block process identity is duplicated")
            successful[key]=process_start
    if active:
        raise IntegrityError("ledger has an unterminated block process identity")
    if set(bindings)!=set(successful):
        raise IntegrityError("telemetry and successful ledger blocks differ")
    for key,(pid,ticks) in bindings.items():
        expected=sha(canonical({"pid":pid,"start_ticks":ticks}))
        if successful[key]!=expected:
            raise IntegrityError("telemetry process start identity differs from successful block ledger")


def _verify_telemetry_sources(
    directory: Path, records: Sequence[Mapping[str,Any]],
) -> dict[tuple[str,str],tuple[int,int]]:
    contract=_load_json(directory/"contract.json")
    bindings: dict[tuple[str,str],tuple[int,int]]={}
    for value in records:
        block=value.get("block_id")
        if not isinstance(block,str) or SAFE_ID.fullmatch(block) is None:
            raise IntegrityError("invalid telemetry block identity")
        series=value.get("series")
        if not isinstance(series,list): raise IntegrityError("telemetry series is not an array")
        for item in series:
            if not isinstance(item,dict): raise IntegrityError("telemetry series is not an object")
            base={"series_id","source_kind","metric_name","kind","status","value","unavailable_reason",
                  "expected_samples","observed_samples","missing_samples","labels","window","samples_sha256"}
            extras=({"observation_window"} if item.get("source_kind")=="system_source_window" else set())
            if item.get("kind")=="counter" and item.get("source_kind")!="system_source_window":
                extras|=COUNTER_PROJECTION_KEYS
            expected_keys=base|extras
            _closed(item,expected_keys,"telemetry series")
            digest=item["samples_sha256"]; sid=item["series_id"]
            if (not isinstance(sid,str) or SAFE_ID.fullmatch(sid) is None or
                not isinstance(digest,str) or HEX64.fullmatch(digest) is None):
                raise IntegrityError("invalid telemetry source identity")
            source_path=directory/f"telemetry-{block}-{sid}-{digest}.bin"
            source=_regular_file_bytes(source_path,source_path.name)
            if sha(source) != digest:
                raise IntegrityError("telemetry source artifact is missing or changed")
            if item["source_kind"]=="native":
                derived,derived_digest=_native_source_summary(source,run_id=contract["run_id"],
                    attempt_id=contract["attempt_id"],block=block,runtime=value["runtime"],
                    clock_domain=contract["clock_domain"],metric_name=item["metric_name"],
                    kind=item["kind"],labels=item["labels"],window=item["window"])
            elif item["source_kind"]=="system_source_window":
                selector=item["window"]
                _closed(selector,{"start_receipt","end_receipt","pid","start_ticks","max_sampling_gap_ns",
                    "first_measured_a_ns","last_measured_end_ns"},"system source window")
                derived=summarize_system_source_window(source=source,
                    start_receipt=selector["start_receipt"],end_receipt=selector["end_receipt"],
                    plan_sha256=contract["plan_sha256"],run_id=contract["run_id"],attempt_id=contract["attempt_id"],
                    block=block,runtime=value["runtime"],pid=selector["pid"],start_ticks=selector["start_ticks"],
                    metric_name=item["metric_name"],kind=item["kind"],labels=item["labels"],
                    max_sampling_gap_ns=selector["max_sampling_gap_ns"],
                    first_measured_a_ns=selector["first_measured_a_ns"],last_measured_end_ns=selector["last_measured_end_ns"])
                derived_digest=derived["samples_sha256"]
                if item["observation_window"]!=derived["observation_window"]:
                    raise IntegrityError("system source observation window changed")
            elif item["source_kind"]=="system":
                derived,derived_digest=_system_source_summary(source,run_id=contract["run_id"],
                    attempt_id=contract["attempt_id"],block=block,runtime=value["runtime"],
                    clock_domain=contract["clock_domain"],
                    metric_name=item["metric_name"],kind=item["kind"],labels=item["labels"],window=item["window"])
            else: raise IntegrityError("telemetry source_kind is invalid")
            claimed={key:item[key] for key in ("metric_name","kind","status","value","unavailable_reason",
                "expected_samples","observed_samples","missing_samples")}
            if item["kind"]=="counter" and item["source_kind"]!="system_source_window":
                claimed.update({key:item[key] for key in COUNTER_PROJECTION_KEYS})
            recomputed={key:derived[key] for key in claimed}
            if derived_digest!=digest or claimed!=recomputed:
                raise IntegrityError("telemetry summary is not derived from retained native samples")
            key=(block,value["runtime"])
            process_start=_telemetry_process_start(source,item)
            prior=bindings.setdefault(key,process_start)
            if prior!=process_start:
                raise IntegrityError("telemetry series disagree on process start identity")
    return bindings


def verify_essential_export(directory: Path, *, expected_plan_sha256: str,
                            require_ledger_binding: bool=True) -> dict[str,Any]:
    """Verify the immutable local export snapshot and every replay dependency."""
    manifest=_load_json(directory/"essential-export.json")
    _closed(manifest,{"schema_version","plan_sha256","files","ledger_head_before_export"},"essential export")
    if manifest["schema_version"]!="episode1.essential-export.v2" or manifest["plan_sha256"]!=expected_plan_sha256:
        raise IntegrityError("essential export binding mismatch")
    head=manifest["ledger_head_before_export"]
    if not isinstance(head,str) or HEX64.fullmatch(head) is None:
        raise IntegrityError("essential export ledger head invalid")
    files=manifest["files"]
    if not isinstance(files,dict) or not files: raise IntegrityError("essential export inventory is empty")
    export_dir=directory/"essential-export-files"
    try: info=os.lstat(export_dir)
    except OSError as exc: raise IntegrityError("essential export directory missing") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise IntegrityError("essential export is not a real directory")
    actual={p.name for p in export_dir.iterdir()}
    if actual!=set(files): raise IntegrityError("essential export file inventory mismatch")
    required={"contract.json","create-intent.json","cleanup-authority.json",
              "lifecycle.jsonl","requests.jsonl","request-lifecycle.jsonl","telemetry.jsonl",
              "system-source.jsonl"}
    if not required <= actual: raise IntegrityError("essential export omits a replay dependency")
    for name,metadata in files.items():
        if (not isinstance(name,str) or not name or name in {".",".."} or
            Path(name).name!=name or "/" in name or "\\" in name):
            raise IntegrityError("unsafe essential export filename")
        if not isinstance(metadata,dict): raise IntegrityError("invalid essential export metadata")
        _closed(metadata,{"bytes","sha256"},"essential export file")
        size=_integer(metadata["bytes"],"essential export bytes")
        digest=metadata["sha256"]
        if not isinstance(digest,str) or HEX64.fullmatch(digest) is None:
            raise IntegrityError("invalid essential export digest")
        data=_regular_file_bytes(export_dir/name,name)
        if len(data)!=size or sha(data)!=digest: raise IntegrityError("essential export file changed")
    snapshot_ledger,snapshot_head,snapshot_integrity=_read_ledger(export_dir)
    if snapshot_integrity!="complete" or snapshot_head!=head:
        raise IntegrityError("essential export ledger snapshot mismatch")
    requests,_=_read_stream(export_dir/"requests.jsonl","episode1.requests-stream.v2")
    lifecycle,_=_read_stream(export_dir/"request-lifecycle.jsonl",
                             "episode1.request-lifecycle-stream.v2")
    _verify_request_lifecycle(lifecycle,requests)
    telemetry,_=_read_stream(export_dir/"telemetry.jsonl","episode1.telemetry-stream.v2")
    bindings=_verify_telemetry_sources(export_dir,telemetry)
    _verify_telemetry_ledger_processes(bindings,snapshot_ledger)
    if require_ledger_binding:
        current,_,_=_read_ledger(directory)
        exports=[d for e,d in current if e["event"]=="essential-export-complete"]
        if len(exports)!=1 or exports[0].get("manifest_sha256")!=sha(canonical(manifest)):
            raise IntegrityError("essential export manifest is not ledger-bound")
    return manifest


def recover_cleanup_only(directory: Path, *, expected_plan_sha256: str,
                         expected_unique_name: str, current_clock_domain: str,
                         current_boot_id: str) -> CleanupOnlyAuthority|AmbiguousCreateIntent:
    contract=_load_json(directory/"contract.json"); intent=_load_json(directory/"create-intent.json")
    _closed(contract,{"schema_version","run_id","attempt_id","plan_sha256","source_sha256",
        "material_sha256","blocks","request_counts","telemetry_series","original_t0_monotonic_ns",
        "original_t0_utc_ns","hard_deadline_monotonic_ns","teardown_deadline_monotonic_ns",
        "clock_domain","boot_id"},"restart contract")
    _closed(intent,{"schema_version","run_id","plan_sha256","source_sha256","material_sha256",
        "unique_name","client_correlation_token","original_t0_monotonic_ns","original_t0_utc_ns",
        "hard_deadline_monotonic_ns","teardown_deadline_monotonic_ns","clock_domain","boot_id"},
        "create intent")
    if contract["schema_version"]!="episode1.capture-contract.v2" or intent["schema_version"]!="episode1.create-intent.v2":
        raise IntegrityError("restart schema unsupported")
    if contract.get("plan_sha256")!=expected_plan_sha256 or intent.get("plan_sha256")!=expected_plan_sha256 or intent.get("unique_name")!=expected_unique_name:
        raise IntegrityError("restart binding mismatch")
    ledger,_,integrity=_read_ledger(directory,tolerate_tail=True)
    if not ledger or ledger[0][0]["event"]!="allocation-create-intent" or ledger[0][1].get("intent_sha256")!=sha(canonical(intent)):
        raise IntegrityError("durable create intent is not ledger-bound")
    authority_path=directory/"cleanup-authority.json"
    if not authority_path.exists():
        return AmbiguousCreateIntent(intent["unique_name"],intent["client_correlation_token"],expected_plan_sha256)
    authority=_load_json(authority_path)
    _closed(authority,{"schema_version","plan_sha256","private_id","unique_name",
        "client_correlation_token","billing_started_monotonic_ns","original_t0_monotonic_ns",
        "hard_deadline_monotonic_ns","teardown_deadline_monotonic_ns","clock_domain","boot_id"},
        "cleanup authority")
    if authority["schema_version"]!="episode1.cleanup-authority.v2": raise IntegrityError("cleanup authority schema unsupported")
    digest=sha(canonical(authority))
    owned=[detail for entry,detail in ledger if entry["event"]=="deletion-authority-owned" and detail.get("authority_sha256")==digest]
    if not owned:
        # The callback did not durably commit.  Ignore the orphan file and force
        # exact-name fresh-inventory reconciliation from the pre-create intent.
        return AmbiguousCreateIntent(intent["unique_name"],intent["client_correlation_token"],expected_plan_sha256)
    if len(owned)!=1: raise IntegrityError("durable authority is not uniquely ledger-bound before corruption")
    if authority.get("unique_name")!=expected_unique_name or authority.get("plan_sha256")!=expected_plan_sha256:
        raise IntegrityError("cleanup authority binding mismatch")
    for field in ("private_id","client_correlation_token","clock_domain","boot_id"):
        if not isinstance(authority.get(field),str) or not authority[field]: raise IntegrityError("invalid cleanup authority")
    if SAFE_ID.fullmatch(authority["private_id"]) is None: raise IntegrityError("invalid private resource id")
    for field in ("billing_started_monotonic_ns","original_t0_monotonic_ns","hard_deadline_monotonic_ns","teardown_deadline_monotonic_ns"):
        try: _integer(authority[field],field,1)
        except ValueError as exc: raise IntegrityError("invalid cleanup authority clock") from exc
    for field in ("original_t0_monotonic_ns","hard_deadline_monotonic_ns","teardown_deadline_monotonic_ns","clock_domain","boot_id"):
        if authority[field]!=intent[field] or authority[field]!=contract[field]: raise IntegrityError("restart clock/deadline binding mismatch")
    for field in ("run_id","plan_sha256","source_sha256","material_sha256","original_t0_utc_ns","clock_domain","boot_id"):
        if intent[field]!=contract[field]: raise IntegrityError("restart intent/contract binding mismatch")
    if authority["client_correlation_token"]!=intent["client_correlation_token"]:
        raise IntegrityError("restart ownership-token binding mismatch")
    comparable=(current_clock_domain==authority["clock_domain"] and current_boot_id==authority["boot_id"])
    return CleanupOnlyAuthority(private_id=authority["private_id"], unique_name=authority["unique_name"],
        client_correlation_token=authority["client_correlation_token"],
        billing_started_monotonic_ns=authority["billing_started_monotonic_ns"],
        original_t0_monotonic_ns=authority["original_t0_monotonic_ns"],
        hard_deadline_monotonic_ns=authority["hard_deadline_monotonic_ns"],
        teardown_deadline_monotonic_ns=authority["teardown_deadline_monotonic_ns"],
        clock_domain=authority["clock_domain"],boot_id=authority["boot_id"],
        deadline_comparable=comparable,ledger_integrity=integrity)


def assemble_promotion_bundle(directory: Path, contract: RunContract, *,
                              plan: Mapping[str,Any], sources: Mapping[str,Any],
                              approval: Mapping[str,Any], image_digest: str,
                              validator: Callable[[Mapping[str,Any]],Mapping[str,Any]]) -> dict[str,Any]:
    """Derive the reviewed promoter's eight sealed objects from retained facts.

    ``sources`` and ``approval`` are explicit operator artifacts; the reviewed
    promoter remains the authority that validates their exact closed schemas.
    Everything produced by capture (records, telemetry, lifecycle and provider
    observations) is reconstructed and cross-bound here.
    """
    if plan.get("plan_sha256")!=contract.plan_sha256: raise IntegrityError("promotion plan mismatch")
    verify_essential_export(directory,expected_plan_sha256=contract.plan_sha256)
    raw_ledger,head,integrity=_read_ledger(directory)
    if integrity!="complete": raise IntegrityError("capture ledger incomplete")
    seal=_load_json(directory/"capture-seal.json")
    if seal.get("ledger_head_sha256")!=head or seal.get("ledger_records")!=len(raw_ledger):
        raise IntegrityError("capture seal ledger mismatch")
    system_sources,system_source_head=_read_bounded_system_source_stream(directory,contract)
    if (seal.get("system_source_records")!=len(system_sources)
            or seal.get("system_source_head_sha256")!=system_source_head):
        raise IntegrityError("capture seal system source mismatch")
    _verify_system_source_startup_attempts(system_sources,raw_ledger)
    if not raw_ledger or raw_ledger[-1][0]["event"]!="capture-closed":
        raise IncompleteEvidence("capture is not closed")
    authority=_load_json(directory/"cleanup-authority.json")
    _closed(authority,{"schema_version","plan_sha256","private_id","unique_name",
        "client_correlation_token","billing_started_monotonic_ns","original_t0_monotonic_ns",
        "hard_deadline_monotonic_ns","teardown_deadline_monotonic_ns","clock_domain","boot_id"},
        "cleanup authority")
    if (authority["schema_version"]!="episode1.cleanup-authority.v2"
            or authority["plan_sha256"]!=contract.plan_sha256
            or not isinstance(authority["private_id"],str)
            or SAFE_ID.fullmatch(authority["private_id"]) is None
            or authority["hard_deadline_monotonic_ns"]!=contract.hard_deadline_monotonic_ns):
        raise IntegrityError("cleanup authority does not bind the promotion contract")
    authority_digest=sha(canonical(authority))
    authority_events=[d for e,d in raw_ledger if e["event"]=="deletion-authority-owned"
        and d.get("authority_sha256")==authority_digest]
    if len(authority_events)!=1:
        raise IntegrityError("cleanup authority is not uniquely ledger-bound")
    token=authority["client_correlation_token"]
    if (not isinstance(token,str) or len(token)<32
            or not isinstance(authority["unique_name"],str)
            or SAFE_ID.fullmatch(authority["unique_name"]) is None):
        raise IntegrityError("cleanup authority ownership token invalid")
    try: billing_ns=_integer(authority["billing_started_monotonic_ns"],"billing start",1)
    except ValueError as exc: raise IntegrityError("cleanup authority billing start invalid") from exc
    ownership_identity=sha(canonical({"provider":"runpod-rest-v2",
        "private_id":authority["private_id"],"unique_name":authority["unique_name"],
        "ownership_token_sha256":sha(token.encode("utf-8")),
        "billing_started_monotonic_ns":billing_ns}))
    allocation_authority=_load_json(directory/"sanitized-allocation-authority.json")
    allocation_authority_keys={"schema_version","run_id","attempt_id","plan_sha256","provider",
        "private_id","unique_name","ownership_token_sha256","billing_started_monotonic",
        "billing_started_monotonic_ns","original_t0_monotonic_ns","hard_deadline_monotonic_ns",
        "resource_identity_sha256","ownership_identity_sha256","immutable_allocation",
        "immutable_allocation_sha256","artifact_sha256"}
    _closed(allocation_authority,allocation_authority_keys,"sanitized allocation authority")
    authority_body={k:v for k,v in allocation_authority.items() if k!="artifact_sha256"}
    if (allocation_authority["schema_version"]!="episode1.sanitized-allocation-authority.v1"
            or allocation_authority["artifact_sha256"]!=sha(canonical(authority_body))
            or allocation_authority["run_id"]!=contract.run_id
            or allocation_authority["attempt_id"]!=contract.attempt_id
            or allocation_authority["plan_sha256"]!=contract.plan_sha256
            or allocation_authority["provider"]!="runpod-rest-v2"
            or allocation_authority["private_id"]!=authority["private_id"]
            or allocation_authority["unique_name"]!=authority["unique_name"]
            or allocation_authority["ownership_token_sha256"]!=sha(token.encode("utf-8"))
            or allocation_authority["billing_started_monotonic_ns"]!=billing_ns
            or allocation_authority["original_t0_monotonic_ns"]!=contract.original_t0_monotonic_ns
            or allocation_authority["hard_deadline_monotonic_ns"]!=contract.hard_deadline_monotonic_ns
            or allocation_authority["ownership_identity_sha256"]!=ownership_identity):
        raise IntegrityError("sanitized allocation authority binding mismatch")
    billing_exact=_finite(allocation_authority["billing_started_monotonic"],"billing start")
    if int(billing_exact*1_000_000_000)!=billing_ns:
        raise IntegrityError("sanitized allocation billing representations disagree")
    recomputed_resource=sha(canonical({"provider":"runpod-rest-v2",
        "private_id":authority["private_id"],"unique_name":authority["unique_name"],
        "ownership_token_sha256":sha(token.encode("utf-8")),
        "billing_started_monotonic":billing_exact}))
    immutable_facts=allocation_authority["immutable_allocation"]
    if (not isinstance(immutable_facts,Mapping)
            or allocation_authority["immutable_allocation_sha256"]!=sha(canonical(immutable_facts))
            or allocation_authority["resource_identity_sha256"]!=recomputed_resource):
        raise IntegrityError("sanitized allocation authority identity mismatch")
    records=_load_json(directory/"promotion-records.json")
    telemetry=_load_json(directory/"promotion-telemetry.json")
    if records.get("artifact_sha256")!=sha(canonical({k:v for k,v in records.items() if k!="artifact_sha256"})):
        raise IntegrityError("promotion records seal mismatch")
    if telemetry.get("artifact_sha256")!=sha(canonical({k:v for k,v in telemetry.items() if k!="artifact_sha256"})):
        raise IntegrityError("promotion telemetry seal mismatch")
    replayed=load_sealed_requests(directory,validator)
    if records.get("records")!=replayed: raise IntegrityError("promotion records differ from sealed request stream")
    telemetry_stream,_=_read_stream(directory/"telemetry.jsonl","episode1.telemetry-stream.v2")
    _verify_telemetry_sources(directory,telemetry_stream)
    derived_summaries=[]
    for block in telemetry_stream:
        for item in block["series"]:
            summary={"block_id":block["block_id"],"runtime":block["runtime"],
                **{k:item[k] for k in ("series_id","source_kind","metric_name","kind","labels",
                    "status","value","unavailable_reason",
                    "expected_samples","observed_samples","missing_samples","samples_sha256")}}
            if item["kind"]=="counter" and item["source_kind"]!="system_source_window":
                summary.update({key:item[key] for key in COUNTER_PROJECTION_KEYS})
            if item["source_kind"]=="system_source_window":
                summary.update(observation_window=item["observation_window"])
            derived_summaries.append(summary)
    if telemetry.get("summaries")!=derived_summaries:
        raise IntegrityError("promotion telemetry differs from retained native sources")
    deletion=[d for e,d in raw_ledger if e["event"]=="deletion-verified"]
    settlement=[d for e,d in raw_ledger if e["event"]=="provider-settlement-observed"]
    if len(deletion)!=1 or len(settlement)!=1: raise IncompleteEvidence("cleanup and settlement evidence required exactly once")
    if not all(deletion[0].get(x) is True for x in ("acknowledged","inventory_absent","direct_not_found")):
        raise IncompleteEvidence("cleanup facts are incomplete")
    provider: dict[str,list[tuple[int,str]]]={}
    for entry,detail in raw_ledger:
        if entry["event"]=="provider-observation":
            role=detail.get("role")
            artifact=detail.get("artifact"); digest=detail.get("sha256")
            if not isinstance(artifact,str) or not isinstance(digest,str) or sha(_regular_file_bytes(directory/artifact,artifact))!=digest:
                raise IntegrityError("provider observation artifact changed")
            provider.setdefault(role,[]).append((entry["monotonic_ns"],digest))
    needed=("delete-response","inventory-after-delete","direct-after-delete","settlement-response")
    if any(role not in provider for role in needed): raise IncompleteEvidence("provider observations incomplete")
    resource_events=[d for e,d in raw_ledger if e["event"]=="allocation-owned"]
    if len(resource_events)!=1: raise IncompleteEvidence("allocation ownership event required exactly once")
    resource=resource_events[0].get("resource_identity_sha256")
    if not isinstance(resource,str) or HEX64.fullmatch(resource) is None: raise IntegrityError("invalid resource identity")
    if (resource!=allocation_authority["resource_identity_sha256"]
            or resource_events[0].get("immutable_allocation_sha256")!=allocation_authority["immutable_allocation_sha256"]
            or resource_events[0].get("allocation_authority_sha256")!=allocation_authority["artifact_sha256"]):
        raise IntegrityError("allocation ledger does not bind sanitized authority")
    observations=deletion[0].get("attempt_evidence")
    if not isinstance(observations,list) or len(observations)!=3:
        raise IntegrityError("cleanup call observations are incomplete")
    cleanup_receipts=[]
    cleanup_specs=(
        ("delete_ack","delete-response","acknowledged",None,None),
        ("inventory_read","inventory-after-delete","complete",True,True),
        ("direct_read","direct-after-delete","not_found",None,None),
    )
    previous=contract.original_t0_monotonic_ns
    for observation,(kind,role,status,complete,absent) in zip(observations,cleanup_specs,strict=True):
        if not isinstance(observation,dict): raise IntegrityError("cleanup call observation is not an object")
        _closed(observation,{"schema_version","delete_attempt","kind","run_id","attempt_id",
            "plan_sha256","resource_identity_sha256","observed_monotonic_ns",
            "provider_response_sha256","status","complete","resource_absent"},"cleanup call observation")
        when=_integer(observation["observed_monotonic_ns"],"cleanup call observation time",1)
        response_hash=observation.get("provider_response_sha256")
        matching=[item for item in provider[role] if item[1]==response_hash]
        if len(matching)!=1: raise IntegrityError("cleanup response does not select one retained provider observation")
        if (observation["schema_version"]!="episode1.provider-call-observation.v1" or
            observation["delete_attempt"]!=deletion[0].get("attempts") or observation["kind"]!=kind or
            observation["run_id"]!=contract.run_id or observation["attempt_id"]!=contract.attempt_id or
            observation["plan_sha256"]!=contract.plan_sha256 or
            observation["resource_identity_sha256"]!=resource or
            observation["provider_response_sha256"]!=response_hash or observation["status"]!=status or
            observation["complete"] is not complete or observation["resource_absent"] is not absent or
            when<=previous or when>contract.hard_deadline_monotonic_ns):
            raise IntegrityError("cleanup call observation binding, order, or result mismatch")
        previous=when
        body={"schema_version":"episode1.provider-receipt.v1","kind":kind,
            "delete_attempt":observation["delete_attempt"],
            "run_id":contract.run_id,"attempt_id":contract.attempt_id,"plan_sha256":contract.plan_sha256,
            "resource_identity_sha256":resource,"observed_monotonic_ns":when,
            "provider_response_sha256":response_hash,"status":status,"complete":complete,
            "resource_absent":absent}
        body["receipt_sha256"]=sha(canonical(body)); cleanup_receipts.append(body)
    cleanup=_sealed_artifact({"schema_version":"episode1.provider-cleanup.v1",
        "run_id":contract.run_id,"attempt_id":contract.attempt_id,"plan_sha256":contract.plan_sha256,
        "receipts":cleanup_receipts})
    provider_artifact_items=[]
    for role,receipt in zip(
        ("delete-response","inventory-after-delete","direct-after-delete"),
        cleanup_receipts, strict=True,
    ):
        matching=[]
        for entry,detail in raw_ledger:
            if (entry["event"]=="provider-observation" and detail.get("role")==role and
                detail.get("sha256")==receipt["provider_response_sha256"]):
                raw=_regular_file_bytes(directory/detail["artifact"],detail["artifact"])
                if sha(raw)!=receipt["provider_response_sha256"]:
                    raise IntegrityError("cleanup provider artifact changed")
                matching.append((raw,detail["evidence"]))
        if len(matching)!=1:
            raise IntegrityError("cleanup receipt does not select one exact provider artifact")
        raw,evidence=matching[0]
        provider_artifact_items.append({"role":role,"encoding":"base64",
            "raw_base64":base64.b64encode(raw).decode("ascii"),
            "raw_sha256":sha(raw),"bytes":len(raw),"evidence":evidence})
    provider_artifacts=_sealed_artifact({"schema_version":"episode1.provider-artifacts.v1",
        "run_id":contract.run_id,"attempt_id":contract.attempt_id,
        "plan_sha256":contract.plan_sha256,"artifacts":provider_artifact_items})
    cleanup_by_role=dict(zip(("delete-response","inventory-after-delete","direct-after-delete"),cleanup_receipts,strict=True))
    selected_response_by_role={role:observation["provider_response_sha256"]
        for observation,(_,role,_,_,_) in zip(observations,cleanup_specs,strict=True)}
    selected=[]
    for entry,detail in raw_ledger:
        event=entry["event"]; out_event=None; out_detail=None
        if event in {"allocation-owned","block-start","startup-failed","failed-start-cleanup",
                     "warmup-complete","cell-complete","block-stop","capture-closed"}:
            out_event,event_detail=event,dict(detail); out_detail=event_detail
        elif event=="essential-export-complete":
            out_event="essential-export-complete"; out_detail={k:detail[k] for k in
                ("resource_identity_sha256","records_sha256","telemetry_sha256")}
        elif (event=="provider-observation" and detail.get("role") in cleanup_by_role and
              detail.get("sha256")==selected_response_by_role[detail["role"]]):
            role=detail["role"]; receipt=cleanup_by_role[role]
            if role=="delete-response":
                out_event="delete-ack"; out_detail={"resource_identity_sha256":resource,
                    "provider_receipt_sha256":receipt["receipt_sha256"],
                    "delete_attempt":receipt["delete_attempt"]}
            elif role=="inventory-after-delete":
                out_event="inventory-read"; out_detail={"resource_identity_sha256":resource,
                    "provider_receipt_sha256":receipt["receipt_sha256"],"complete":True,"resource_absent":True,
                    "delete_attempt":receipt["delete_attempt"]}
            else:
                out_event="direct-read"; out_detail={"resource_identity_sha256":resource,
                    "provider_receipt_sha256":receipt["receipt_sha256"],"status":"not_found",
                    "delete_attempt":receipt["delete_attempt"]}
        if out_event is not None:
            when = cleanup_by_role[detail["role"]]["observed_monotonic_ns"] if event=="provider-observation" and detail.get("role") in cleanup_by_role else entry["monotonic_ns"]
            selected.append((when,out_event,out_detail))
    selected.sort(key=lambda item:item[0])
    entries=[]; previous=ZERO
    for sequence,(when,event,details) in enumerate(selected,1):
        body={"schema_version":"episode1.private-ledger.v2","sequence":sequence,
            "run_id":contract.run_id,"attempt_id":contract.attempt_id,"plan_sha256":contract.plan_sha256,
            "event":event,"monotonic_ns":when,"previous_sha256":previous,"details":details}
        body["record_sha256"]=sha(canonical(body)); previous=body["record_sha256"]; entries.append(body)
    ledger=_sealed_artifact({"schema_version":"episode1.private-ledger-artifact.v1",
        "run_id":contract.run_id,"attempt_id":contract.attempt_id,"plan_sha256":contract.plan_sha256,
        "entries":entries})
    settlement_detail=settlement[0]
    settlement_artifact=_sealed_artifact({"schema_version":"episode1.cost-settlement.v1",
        "run_id":contract.run_id,"attempt_id":contract.attempt_id,"plan_sha256":contract.plan_sha256,
        "status":settlement_detail["status"],"observed_total_usd":settlement_detail["observed_total_usd"],
        "reason":settlement_detail["reason"],
        "billing_source_sha256":settlement_detail["source_sha256"] if settlement_detail["status"]=="settled" else None})
    settlement_matches=[item for item in provider["settlement-response"]
        if item[1]==settlement_detail["source_sha256"]]
    if len(settlement_matches)!=1:
        raise IntegrityError("settlement source binding mismatch")
    for name,value in (("sources",sources),("approval",approval)):
        if not isinstance(value,Mapping) or value.get("artifact_sha256")!=sha(canonical({k:v for k,v in value.items() if k!="artifact_sha256"})):
            raise IntegrityError(f"{name} is not a sealed actual input")
    if not isinstance(image_digest,str) or re.fullmatch(r"sha256:[0-9a-f]{64}",image_digest) is None:
        raise ValueError("invalid observed image digest")
    manifest=_sealed_artifact({"schema_version":"episode1.evidence-manifest.v1",
        "run_id":contract.run_id,"attempt_id":contract.attempt_id,"plan_sha256":contract.plan_sha256,
        "protocol_sha256":plan["protocol_sha256"],"material_sha256":plan["material_sha256"],
        "source_commit":plan["source_commit"],"image_digest":image_digest,
        "collector_sha256":plan["capture"]["collector_sha256"],
        "private_schema_sha256":plan["capture"]["private_schema_sha256"],
        "records_sha256":records["artifact_sha256"],"telemetry_sha256":telemetry["artifact_sha256"],
        "sources_sha256":sources["artifact_sha256"],"approval_sha256":approval["artifact_sha256"],
        "cleanup_sha256":cleanup["artifact_sha256"],"ledger_sha256":ledger["artifact_sha256"],
        "settlement_sha256":settlement_artifact["artifact_sha256"],"resource_identity_sha256":resource,
        "allocation_authority_sha256":allocation_authority["artifact_sha256"],
        "provider_private_id":authority["private_id"],
        "provider_ownership_identity_sha256":ownership_identity,
        "start_monotonic_ns":contract.original_t0_monotonic_ns,
        "hard_deadline_monotonic_ns":contract.hard_deadline_monotonic_ns})
    bundle={"manifest":manifest,"allocation_authority":allocation_authority,
        "sources":dict(sources),"approval":dict(approval),"records":records,
        "telemetry":telemetry,"cleanup":cleanup,"provider_artifacts":provider_artifacts,
        "ledger":ledger,"settlement":settlement_artifact}
    _atomic(directory/"promotion-bundle.json",canonical(bundle)+b"\n")
    return bundle


def load_sealed_requests(directory: Path,
                         validator: Callable[[Mapping[str,Any]],Mapping[str,Any]]) -> list[dict[str,Any]]:
    """Load promotion inputs only when their final stream head matches the seal."""
    seal=_load_json(directory/"capture-seal.json")
    records,head=_read_stream(directory/"requests.jsonl","episode1.requests-stream.v2")
    if seal.get("request_head_sha256")!=head or seal.get("request_records")!=len(records):
        raise IntegrityError("request stream does not match the final capture seal")
    lifecycle,lifecycle_head=_read_stream(directory/"request-lifecycle.jsonl",
        "episode1.request-lifecycle-stream.v2")
    if (seal.get("request_lifecycle_head_sha256")!=lifecycle_head or
        seal.get("request_lifecycle_records")!=len(lifecycle)):
        raise IntegrityError("request lifecycle stream does not match the final capture seal")
    _verify_request_lifecycle(lifecycle,records)
    result=[]
    for record in records:
        checked=dict(validator(record)); checked.pop("derived",None); result.append(checked)
    return result
