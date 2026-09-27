"""Bounded, runtime-native Prometheus sampling for Episode 1.

This module deliberately knows no cross-runtime metric aliases.  Callers bind
the exact native series they want and pass the resulting native samples to the
existing pure ``telemetry_summary`` implementation.
"""

from __future__ import annotations

import base64
import errno
import hashlib
import ipaddress
import json
import math
import os
import re
import selectors
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

from .telemetry_summary import Series, Window, summarize


_NAME = re.compile(r"[A-Za-z_:][A-Za-z0-9_:]*\Z")
_LABEL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_LABEL_PREFIX = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)="')
_NUMBER = re.compile(r"[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?\Z")
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}\Z")
_PROM_TYPES = frozenset({"counter", "gauge", "histogram", "summary", "untyped"})
_MAX_PROM_BYTES = 8 * 1024 * 1024
_MAX_PROM_LINES = 100_000
_MAX_PROM_LINE_CHARS = 65_536
_MAX_PROM_LABELS = 256
_MAX_PROM_POINTS = 100_000


class SamplerError(RuntimeError):
    pass


class ScrapeFailure(SamplerError):
    def __init__(self, message: str, *, raw: bytes = b"", raw_kind: str = "body") -> None:
        super().__init__(message)
        self.raw = raw
        self.raw_kind = raw_kind


class ScrapeTimeout(TimeoutError):
    def __init__(self, message: str, *, raw: bytes = b"", raw_kind: str = "body") -> None:
        super().__init__(message)
        self.raw = raw
        self.raw_kind = raw_kind


@dataclass(frozen=True)
class Binding:
    run_id: str
    attempt_id: str
    process_identity: str
    process_start_identity: str
    runtime: str
    block: str
    clock_domain: str

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if not isinstance(value, str) or not _IDENTITY.fullmatch(value):
                raise ValueError(f"invalid {name}")
        if not (self.runtime == "vllm" or self.runtime.startswith("vllm-")
                or self.runtime == "sglang" or self.runtime.startswith("sglang-")):
            raise ValueError("runtime must be a vllm or sglang identity")


@dataclass(frozen=True)
class MetricSpec:
    """One exact runtime-native series and its native unit."""

    kind: str
    metric_name: str
    labels: Mapping[str, str] = field(default_factory=dict)
    unit: str = "1"

    def __post_init__(self) -> None:
        if self.kind not in {"counter", "gauge"}:
            raise ValueError("kind must be counter or gauge")
        if not _NAME.fullmatch(self.metric_name):
            raise ValueError("invalid native metric name")
        if not isinstance(self.unit, str) or not self.unit or len(self.unit) > 64:
            raise ValueError("unit must be a short non-empty native unit")
        checked: dict[str, str] = {}
        label_text_chars = 0
        for key, value in self.labels.items():
            if not isinstance(key, str) or not _LABEL.fullmatch(key):
                raise ValueError("invalid label name")
            if not isinstance(value, str) or len(value) > 1_024:
                raise ValueError("label values must be strings of at most 1024 characters")
            label_text_chars += len(key) + len(value)
            if label_text_chars > 8_192:
                raise ValueError("metric label selection is too large")
            checked[key] = value
        object.__setattr__(self, "labels", MappingProxyType(checked))

    def series(self, runtime: str) -> Series:
        if runtime.split("-", 1)[0] not in {"vllm", "sglang"}:
            raise ValueError("unsupported runtime")
        return Series.create(kind=self.kind, metric_name=self.metric_name, labels=self.labels)


@dataclass(frozen=True)
class ParsedPoint:
    metric_name: str
    labels: Mapping[str, str]
    value: float
    help: str | None
    declared_type: str | None
    declared_unit: str | None


@dataclass(frozen=True)
class ParsedPrometheus:
    points: tuple[ParsedPoint, ...]
    help: Mapping[str, str]
    types: Mapping[str, str]
    units: Mapping[str, str]


def _metadata_family(sample_name: str, metadata: Mapping[str, str]) -> str:
    if sample_name in metadata:
        return sample_name
    if sample_name.endswith("_total") and sample_name[:-6] in metadata:
        return sample_name[:-6]
    # Prometheus attaches HELP/TYPE/UNIT to the histogram or summary family,
    # not to each exported ``_bucket``, ``_sum``, and ``_count`` sample.
    for suffix in ("_bucket", "_sum", "_count"):
        if sample_name.endswith(suffix) and sample_name[:-len(suffix)] in metadata:
            return sample_name[:-len(suffix)]
    return sample_name


def _parse_labels(text: str, deadline_check: Callable[[], None] | None = None) -> dict[str, str]:
    labels: dict[str, str] = {}
    pos = 0
    while pos < len(text):
        if deadline_check is not None:
            deadline_check()
        if len(labels) >= _MAX_PROM_LABELS:
            raise SamplerError("too many Prometheus labels")
        match = _LABEL_PREFIX.match(text, pos)
        if match is None:
            raise SamplerError("invalid Prometheus label syntax")
        key = match.group(1)
        if key in labels:
            raise SamplerError("duplicate Prometheus label")
        pos = match.end()
        chars: list[str] = []
        while pos < len(text):
            if deadline_check is not None and (pos & 255) == 0:
                deadline_check()
            char = text[pos]
            pos += 1
            if char == '"':
                break
            if char == "\\":
                if pos >= len(text) or text[pos] not in {'\\', '"', 'n'}:
                    raise SamplerError("invalid Prometheus label escape")
                escaped = text[pos]
                pos += 1
                chars.append("\n" if escaped == "n" else escaped)
            else:
                chars.append(char)
        else:
            raise SamplerError("unterminated Prometheus label")
        labels[key] = "".join(chars)
        if pos == len(text):
            break
        if text[pos] != ",":
            raise SamplerError("invalid Prometheus label separator")
        pos += 1
    return labels


def parse_prometheus(
    raw: bytes, *, deadline_check: Callable[[], None] | None = None
) -> ParsedPrometheus:
    if not isinstance(raw, bytes):
        raise SamplerError("metrics body must be bytes")
    if len(raw) > _MAX_PROM_BYTES:
        raise SamplerError("metrics body exceeded parser byte limit")
    if deadline_check is not None:
        deadline_check()
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SamplerError("metrics body is not UTF-8") from exc
    helps: dict[str, str] = {}
    types: dict[str, str] = {}
    units: dict[str, str] = {}
    points: list[tuple[str, dict[str, str], float]] = []
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    lines = text.splitlines()
    if deadline_check is not None:
        deadline_check()
    if len(lines) > _MAX_PROM_LINES:
        raise SamplerError("too many Prometheus lines")
    for line_number, raw_line in enumerate(lines, start=1):
        if deadline_check is not None:
            deadline_check()
        if len(raw_line) > _MAX_PROM_LINE_CHARS:
            raise SamplerError(f"Prometheus line too long at line {line_number}")
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("# HELP "):
            rest = line[7:]
            name, separator, description = rest.partition(" ")
            if not separator or not _NAME.fullmatch(name) or name in helps:
                raise SamplerError(f"invalid or duplicate HELP at line {line_number}")
            helps[name] = description
            continue
        if line.startswith("# TYPE "):
            fields = line[7:].split()
            if len(fields) != 2 or not _NAME.fullmatch(fields[0]) or fields[1] not in _PROM_TYPES:
                raise SamplerError(f"invalid TYPE at line {line_number}")
            if fields[0] in types:
                raise SamplerError(f"duplicate TYPE at line {line_number}")
            types[fields[0]] = fields[1]
            continue
        if line.startswith("# UNIT "):
            fields = line[7:].split()
            if len(fields) != 2 or not _NAME.fullmatch(fields[0]) or not _NAME.fullmatch(fields[1]):
                raise SamplerError(f"invalid UNIT at line {line_number}")
            if fields[0] in units:
                raise SamplerError(f"duplicate UNIT at line {line_number}")
            units[fields[0]] = fields[1]
            continue
        if line.startswith("#"):
            continue
        metric_part, separator, number = line.rpartition(" ")
        if not separator or not _NUMBER.fullmatch(number):
            raise SamplerError(f"invalid sample at line {line_number}")
        if "{" in metric_part:
            name, separator, tail = metric_part.partition("{")
            if not separator or not tail.endswith("}"):
                raise SamplerError(f"invalid sample labels at line {line_number}")
            labels = _parse_labels(tail[:-1], deadline_check)
        else:
            name, labels = metric_part, {}
        if not _NAME.fullmatch(name):
            raise SamplerError(f"invalid metric name at line {line_number}")
        value = float(number)
        if not math.isfinite(value):
            raise SamplerError(f"non-finite sample at line {line_number}")
        identity = (name, tuple(sorted(labels.items())))
        if identity in seen:
            raise SamplerError(f"duplicate series at line {line_number}")
        seen.add(identity)
        points.append((name, labels, value))
        if len(points) > _MAX_PROM_POINTS:
            raise SamplerError("too many Prometheus samples")
    materialized: list[ParsedPoint] = []
    for name, labels, value in points:
        if deadline_check is not None:
            deadline_check()
        family = _metadata_family(name, types)
        materialized.append(
            ParsedPoint(
                metric_name=name,
                labels=labels,
                value=value,
                help=helps.get(_metadata_family(name, helps)),
                declared_type=types.get(family),
                declared_unit=units.get(_metadata_family(name, units)),
            )
        )
    return ParsedPrometheus(tuple(materialized), helps, types, units)


def localhost_http_scraper(
    url: str,
    *,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
    max_body_bytes: int = 8 * 1024 * 1024,
) -> Callable[[int], bytes]:
    """Return a direct loopback-only GET callable accepting an absolute deadline."""

    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("metrics URL must be plain HTTP without credentials or fragment")
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
    except ValueError as exc:
        raise ValueError("metrics host must be a literal loopback address") from exc
    if not address.is_loopback or parsed.port is None or not (1 <= parsed.port <= 65535):
        raise ValueError("metrics endpoint must have a loopback address and explicit port")
    if isinstance(max_body_bytes, bool) or not isinstance(max_body_bytes, int) or max_body_bytes <= 0:
        raise ValueError("max_body_bytes must be positive")
    target = parsed.path or "/"
    if parsed.query:
        target += "?" + parsed.query

    last_clock: int | None = None
    clock_lock = threading.Lock()

    def now_ns() -> int:
        nonlocal last_clock
        with clock_lock:
            value = monotonic_ns()
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise SamplerError("invalid monotonic clock value")
            if last_clock is not None and value < last_clock:
                raise SamplerError("monotonic clock moved backward")
            last_clock = value
            return value

    def wait(selector: selectors.BaseSelector, event: int, deadline: int, partial: bytes) -> None:
        remaining = deadline - now_ns()
        if remaining <= 0:
            raise ScrapeTimeout("metrics request absolute deadline reached", raw=partial, raw_kind="partial_http_wire")
        events = selector.select(remaining / 1_000_000_000)
        if not events or not any(mask & event for _key, mask in events):
            raise ScrapeTimeout("metrics request absolute deadline reached", raw=partial, raw_kind="partial_http_wire")
        if now_ns() > deadline:
            raise ScrapeTimeout("metrics request absolute deadline reached", raw=partial, raw_kind="partial_http_wire")

    def decode_chunked(wire: bytes, deadline: int) -> tuple[bool, bytes]:
        decoded = bytearray()
        position = 0
        while True:
            if now_ns() > deadline:
                raise ScrapeTimeout("metrics request absolute deadline reached", raw=wire, raw_kind="partial_http_wire")
            line_end = wire.find(b"\r\n", position)
            if line_end < 0:
                return False, bytes(decoded)
            size_text = wire[position:line_end].split(b";", 1)[0]
            if not size_text or len(size_text) > 16 or not re.fullmatch(rb"[0-9A-Fa-f]+", size_text):
                raise ScrapeFailure("invalid chunk framing", raw=wire, raw_kind="partial_http_wire")
            size = int(size_text, 16)
            position = line_end + 2
            if size == 0:
                trailer_end = wire.find(b"\r\n\r\n", position)
                if wire[position:position + 2] == b"\r\n":
                    return True, bytes(decoded)
                if trailer_end < 0:
                    return False, bytes(decoded)
                return True, bytes(decoded)
            if size > max_body_bytes or len(decoded) + size > max_body_bytes:
                raise ScrapeFailure("metrics response exceeded byte limit", raw=wire, raw_kind="partial_http_wire")
            if len(wire) < position + size + 2:
                return False, bytes(decoded)
            if wire[position + size:position + size + 2] != b"\r\n":
                raise ScrapeFailure("invalid chunk framing", raw=wire, raw_kind="partial_http_wire")
            decoded.extend(wire[position:position + size])
            position += size + 2

    def scrape(deadline_monotonic_ns: int) -> bytes:
        if isinstance(deadline_monotonic_ns, bool) or not isinstance(deadline_monotonic_ns, int):
            raise ValueError("deadline must be an integer monotonic timestamp")
        if deadline_monotonic_ns <= now_ns():
            raise ScrapeTimeout("metrics request deadline reached before connect")
        family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        endpoint = (str(address), parsed.port, 0, 0) if family == socket.AF_INET6 else (str(address), parsed.port)
        request = (
            f"GET {target} HTTP/1.1\r\nHost: {address.compressed}:{parsed.port}\r\n"
            "Accept: text/plain\r\nConnection: close\r\n\r\n"
        ).encode("ascii")
        sock = socket.socket(family, socket.SOCK_STREAM)
        selector = selectors.DefaultSelector()
        received = bytearray()
        try:
            sock.setblocking(False)
            result = sock.connect_ex(endpoint)
            if result not in (0, errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY):
                raise ScrapeFailure("metrics connect failed")
            selector.register(sock, selectors.EVENT_WRITE)
            if result != 0:
                wait(selector, selectors.EVENT_WRITE, deadline_monotonic_ns, bytes(received))
                socket_error = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if socket_error:
                    raise ScrapeFailure("metrics connect failed")
            sent = 0
            while sent < len(request):
                wait(selector, selectors.EVENT_WRITE, deadline_monotonic_ns, bytes(received))
                try:
                    count = sock.send(request[sent:])
                except BlockingIOError:
                    continue
                if count <= 0:
                    raise ScrapeFailure("metrics request send failed")
                sent += count
            selector.modify(sock, selectors.EVENT_READ)
            header_end = -1
            status = 0
            content_length: int | None = None
            chunked = False
            body_offset = 0
            while True:
                wait(selector, selectors.EVENT_READ, deadline_monotonic_ns, bytes(received))
                try:
                    chunk = sock.recv(65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    if header_end < 0:
                        raise ScrapeFailure("metrics connection closed before headers", raw=bytes(received), raw_kind="partial_http_wire")
                    body = bytes(received[body_offset:])
                    if chunked:
                        done, decoded = decode_chunked(body, deadline_monotonic_ns)
                        if not done:
                            raise ScrapeFailure("truncated chunked metrics body", raw=body, raw_kind="partial_http_wire")
                        body = decoded
                    elif content_length is not None and len(body) != content_length:
                        raise ScrapeFailure("truncated metrics body", raw=body)
                    elif content_length is None and len(body) > max_body_bytes:
                        raise ScrapeFailure("metrics response exceeded byte limit", raw=body)
                    break
                received.extend(chunk)
                if header_end < 0:
                    header_end = received.find(b"\r\n\r\n")
                    if header_end < 0:
                        if len(received) > 65536:
                            raise ScrapeFailure("metrics headers exceeded byte limit", raw=bytes(received), raw_kind="partial_http_wire")
                        continue
                    if header_end > 65536:
                        raise ScrapeFailure("metrics headers exceeded byte limit", raw=bytes(received), raw_kind="partial_http_wire")
                    header_lines = bytes(received[:header_end]).split(b"\r\n")
                    try:
                        version, status_text, _reason = header_lines[0].decode("ascii").split(" ", 2)
                        status = int(status_text)
                    except (UnicodeDecodeError, ValueError) as exc:
                        raise ScrapeFailure("malformed HTTP status", raw=bytes(received), raw_kind="partial_http_wire") from exc
                    if version not in {"HTTP/1.0", "HTTP/1.1"}:
                        raise ScrapeFailure("unsupported HTTP version", raw=bytes(received), raw_kind="partial_http_wire")
                    headers: dict[str, str] = {}
                    for line in header_lines[1:]:
                        name, separator, value = line.partition(b":")
                        if not separator:
                            raise ScrapeFailure("malformed HTTP header", raw=bytes(received), raw_kind="partial_http_wire")
                        try:
                            key = name.decode("ascii").lower()
                            decoded_value = value.decode("ascii").strip()
                        except UnicodeDecodeError as exc:
                            raise ScrapeFailure("non-ASCII HTTP header", raw=bytes(received), raw_kind="partial_http_wire") from exc
                        if key in headers:
                            raise ScrapeFailure("duplicate HTTP header", raw=bytes(received), raw_kind="partial_http_wire")
                        headers[key] = decoded_value
                    transfer_encoding = headers.get("transfer-encoding", "").lower()
                    chunked = transfer_encoding == "chunked"
                    if transfer_encoding and not chunked:
                        raise ScrapeFailure("unsupported HTTP transfer encoding", raw=bytes(received), raw_kind="partial_http_wire")
                    if "content-length" in headers:
                        if chunked or not headers["content-length"].isdigit():
                            raise ScrapeFailure("invalid HTTP body framing", raw=bytes(received), raw_kind="partial_http_wire")
                        content_length = int(headers["content-length"])
                        if content_length > max_body_bytes:
                            raise ScrapeFailure("metrics response exceeded byte limit", raw=bytes(received), raw_kind="partial_http_wire")
                    body_offset = header_end + 4
                body_wire = bytes(received[body_offset:])
                if not chunked and content_length is None and len(body_wire) > max_body_bytes:
                    raise ScrapeFailure("metrics response exceeded byte limit", raw=body_wire, raw_kind="partial_http_wire")
                if chunked and len(body_wire) > max_body_bytes + 65536:
                    raise ScrapeFailure("metrics response exceeded byte limit", raw=body_wire, raw_kind="partial_http_wire")
                if chunked:
                    done, body = decode_chunked(body_wire, deadline_monotonic_ns)
                    if done:
                        break
                elif content_length is not None and len(body_wire) >= content_length:
                    if len(body_wire) != content_length:
                        raise ScrapeFailure("metrics response exceeded declared length", raw=body_wire)
                    body = body_wire
                    break
            if now_ns() > deadline_monotonic_ns:
                raise ScrapeTimeout("metrics request absolute deadline reached", raw=body)
            if status != 200:
                raise ScrapeFailure(f"metrics endpoint returned HTTP {status}", raw=body)
            return body
        except ScrapeTimeout:
            raise
        except ScrapeFailure:
            raise
        except OSError as exc:
            if now_ns() >= deadline_monotonic_ns:
                raise ScrapeTimeout("metrics request absolute deadline reached", raw=bytes(received), raw_kind="partial_http_wire") from exc
            raise ScrapeFailure("metrics request failed", raw=bytes(received), raw_kind="partial_http_wire") from exc
        finally:
            selector.close()
            sock.close()

    return scrape


class PrivateEvidenceStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory.absolute()
        for ancestor in (self.directory.parent, *self.directory.parents):
            if ancestor.is_symlink():
                raise ValueError("evidence directory cannot have a symlink ancestor")
        if self.directory.exists() or self.directory.is_symlink():
            raise ValueError("evidence directory must be newly created")
        if not self.directory.parent.is_dir():
            raise ValueError("evidence parent must already exist")
        self.directory.mkdir(mode=0o700, parents=False, exist_ok=False)
        os.chmod(self.directory, 0o700)
        self._lock = threading.Lock()

    def persist(self, sequence: int, envelope: Mapping[str, object]) -> tuple[Path, str]:
        encoded = (json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n").encode()
        digest = hashlib.sha256(encoded).hexdigest()
        target = self.directory / f"slot-{sequence:08d}.json"
        temporary = self.directory / f".slot-{sequence:08d}.{os.getpid()}.{threading.get_ident()}.tmp"
        with self._lock:
            if target.exists():
                raise FileExistsError(target)
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                remaining = memoryview(encoded)
                while remaining:
                    written = os.write(descriptor, remaining)
                    if written <= 0:
                        raise OSError("short evidence write")
                    remaining = remaining[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(temporary, target)
            os.chmod(target, 0o600)
            directory_fd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return target, digest


class NativeSampler:
    def __init__(
        self,
        *,
        binding: Binding,
        metrics: Sequence[MetricSpec],
        scrape: Callable[[int], bytes],
        identity_probe: Callable[[int], tuple[str, str]],
        store: PrivateEvidenceStore,
        interval_ns: int,
        scrape_timeout_ns: int,
        reap_reserve_ns: int = 5_000_000_000,
        finalize_reserve_ns: int = 1_000_000_000,
        max_slots: int = 8_000,
        max_metrics: int = 32,
        max_total_raw_bytes: int = 256 * 1024 * 1024,
        max_total_artifact_bytes: int = 384 * 1024 * 1024,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        utc_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        if not metrics or len(metrics) > max_metrics or len({(m.metric_name, tuple(sorted(m.labels.items()))) for m in metrics}) != len(metrics):
            raise ValueError("metrics must be non-empty and unique")
        integer_bounds = (interval_ns, scrape_timeout_ns, reap_reserve_ns, finalize_reserve_ns,
                          max_slots, max_metrics,
                          max_total_raw_bytes, max_total_artifact_bytes)
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in integer_bounds):
            raise ValueError("interval, timeouts, reserves, and retention bounds must be positive integers")
        self.binding, self.metrics, self.scrape, self.identity_probe, self.store = (
            binding, tuple(metrics), scrape, identity_probe, store
        )
        self.interval_ns, self.scrape_timeout_ns = interval_ns, scrape_timeout_ns
        self.reap_reserve_ns = reap_reserve_ns
        self.finalize_reserve_ns = finalize_reserve_ns
        self.max_slots = max_slots
        self.max_total_raw_bytes = max_total_raw_bytes
        self.max_total_artifact_bytes = max_total_artifact_bytes
        self.monotonic_ns, self.utc_ns = monotonic_ns, utc_ns
        self.samples: list[dict[str, object]] = []
        self.records: list[dict[str, object]] = []
        self.total_raw_bytes = 0
        self.total_artifact_bytes = 0
        self._sequence = 0
        self._last_scheduled_ns: int | None = None
        self._last_monotonic_ns: int | None = None
        self._last_utc_ns: int | None = None
        self._clock_lock = threading.Lock()
        self._last_counter: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._thread: threading.Thread | None = None
        self._wake = threading.Event()
        self._stop_lock = threading.Lock()
        self._drain_ns: int | None = None
        self._hard_deadline_ns: int | None = None
        self._work_deadline_ns: int | None = None
        self._start_ns: int | None = None
        self._worker_error: BaseException | None = None

    def _monotonic(self) -> int:
        with self._clock_lock:
            value = self.monotonic_ns()
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise SamplerError("invalid monotonic clock value")
            if self._last_monotonic_ns is not None and value < self._last_monotonic_ns:
                raise SamplerError("monotonic clock moved backward")
            self._last_monotonic_ns = value
            return value

    def _utc(self) -> int:
        with self._clock_lock:
            value = self.utc_ns()
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise SamplerError("invalid UTC clock value")
            if self._last_utc_ns is not None and value < self._last_utc_ns:
                raise SamplerError("UTC clock moved backward")
            self._last_utc_ns = value
            return value

    def _observation(self) -> tuple[int, int, int]:
        before = self._monotonic()
        utc = self._utc()
        after = self._monotonic()
        return before + (after - before) // 2, utc, after - before

    def sample_slot(
        self, scheduled_ns: int, absolute_deadline_ns: int, *, _skip_reason: str | None = None
    ) -> Mapping[str, object]:
        if (isinstance(scheduled_ns, bool) or not isinstance(scheduled_ns, int) or scheduled_ns < 0
                or isinstance(absolute_deadline_ns, bool) or not isinstance(absolute_deadline_ns, int)
                or absolute_deadline_ns <= 0):
            raise ValueError("invalid slot or deadline")
        if self._last_scheduled_ns is not None and scheduled_ns <= self._last_scheduled_ns:
            raise ValueError("scheduled slots must be strictly increasing")
        if self._sequence >= self.max_slots:
            raise SamplerError("telemetry slot retention bound reached")
        self._last_scheduled_ns = scheduled_ns
        self._sequence += 1
        scrape_start = self._monotonic()
        # Keep final clock reads, envelope construction, and atomic persistence
        # out of the transport/parser budget.
        request_deadline = min(
            absolute_deadline_ns - self.finalize_reserve_ns,
            scrape_start + self.scrape_timeout_ns,
        )
        raw = b""
        raw_kind = "body"
        parsed: ParsedPrometheus | None = None
        scrape_status, scrape_reason = "ok", None
        observed_identity_before: tuple[str, str] | None = None
        observed_identity_after: tuple[str, str] | None = None
        try:
            if _skip_reason is not None:
                raise ScrapeFailure(_skip_reason)
            if scrape_start >= request_deadline:
                raise ScrapeTimeout("scrape deadline reached")
            observed_identity_before = self.identity_probe(request_deadline)
            if self._monotonic() > request_deadline:
                raise ScrapeTimeout("identity probe exceeded scrape deadline")
            if (not isinstance(observed_identity_before, tuple) or len(observed_identity_before) != 2
                    or not all(isinstance(value, str) and _IDENTITY.fullmatch(value)
                               for value in observed_identity_before)):
                raise SamplerError("process identity probe invalid")
            if observed_identity_before != (self.binding.process_identity, self.binding.process_start_identity):
                raise SamplerError("process identity mismatch")
            raw = self.scrape(request_deadline)
            if self._monotonic() > request_deadline:
                raise ScrapeTimeout("scrape callable returned after deadline", raw=raw)
            if not isinstance(raw, bytes):
                raise SamplerError("scrape callable must return bytes")
            observed_identity_after = self.identity_probe(request_deadline)
            if self._monotonic() > request_deadline:
                raise ScrapeTimeout("identity probe exceeded scrape deadline", raw=raw)
            if (not isinstance(observed_identity_after, tuple) or len(observed_identity_after) != 2
                    or not all(isinstance(value, str) and _IDENTITY.fullmatch(value)
                               for value in observed_identity_after)):
                raise SamplerError("process identity probe invalid")
            if observed_identity_after != observed_identity_before:
                raise SamplerError("process identity changed during scrape")
            def check_parse_deadline() -> None:
                if self._monotonic() > request_deadline:
                    raise ScrapeTimeout("Prometheus parsing exceeded scrape deadline", raw=raw)

            parsed = parse_prometheus(raw, deadline_check=check_parse_deadline)
            if self._monotonic() > request_deadline:
                raise ScrapeTimeout("Prometheus parsing exceeded scrape deadline", raw=raw)
        except ScrapeTimeout as exc:
            raw, raw_kind = exc.raw, exc.raw_kind
            scrape_status, scrape_reason = "error", "scrape_failed"
        except ScrapeFailure as exc:
            raw, raw_kind = exc.raw, exc.raw_kind
            scrape_status, scrape_reason = "error", _skip_reason or "scrape_failed"
        except SamplerError as exc:
            message = str(exc)
            if message in {"process identity mismatch", "process identity changed during scrape",
                           "process identity probe invalid"}:
                scrape_status, scrape_reason = "unsupported", "identity_changed"
            else:
                scrape_status, scrape_reason = "error", "parse_failed" if raw else "scrape_failed"
        except Exception:
            # Injected transports have the same fail-closed record contract as
            # the concrete transport.  Never retain exception text because it
            # can include endpoint or library internals.
            scrape_status, scrape_reason = "error", "scrape_failed"
        observed_ns, observed_utc_ns, uncertainty_ns = self._observation()
        native_samples: list[dict[str, object]] = []
        reset_series: list[dict[str, object]] = []
        for spec in self.metrics:
            matching = [] if parsed is None else [
                point for point in parsed.points
                if point.metric_name == spec.metric_name and dict(point.labels) == dict(spec.labels)
            ]
            status, reason, value = "ok", None, None
            help_text = declared_type = declared_unit = None
            if scrape_status == "unsupported":
                status, reason = "unsupported", "unsupported"
            elif scrape_status != "ok":
                status, reason = "error", "scrape_failed" if scrape_reason != "parse_failed" else "parse_failed"
            elif not matching:
                status, reason = "missing", "not_reported"
            elif len(matching) != 1:
                status, reason = "error", "parse_failed"
            else:
                point = matching[0]
                value, help_text = point.value, point.help
                declared_type, declared_unit = point.declared_type, point.declared_unit
                admitted_types = ({"counter"} if spec.kind == "counter"
                                  else {"gauge", "untyped"})
                # Prometheus exposes histogram totals as ``*_sum`` samples,
                # while TYPE metadata remains attached to the histogram
                # family.  The sum is monotonic and is therefore a counter
                # for the bounded-window delta used here.
                if spec.kind == "counter" and spec.metric_name.endswith("_sum"):
                    admitted_types.add("histogram")
                if declared_type is not None and declared_type not in admitted_types:
                    status, reason, value = "error", "parse_failed", None
                elif declared_unit is not None and declared_unit != spec.unit:
                    status, reason, value = "error", "parse_failed", None
            summary_sample = {
                "clock_domain": self.binding.clock_domain,
                "monotonic_ns": observed_ns,
                "process_identity": self.binding.process_identity,
                "process_start_identity": self.binding.process_start_identity,
                "runtime": self.binding.runtime,
                "block": self.binding.block,
                "metric_name": spec.metric_name,
                # MetricSpec owns this immutable-by-contract mapping; sharing it
                # avoids retaining thousands of duplicate label dictionaries.
                "labels": spec.labels,
                "value": value,
                "status": status,
                "reason": reason,
            }
            self.samples.append(summary_sample)
            native = dict(summary_sample)
            native.update({"labels": dict(spec.labels), "kind": spec.kind, "unit": spec.unit,
                           "help": help_text, "declared_type": declared_type,
                           "declared_unit": declared_unit})
            native_samples.append(native)
            if status == "ok" and spec.kind == "counter":
                key = (spec.metric_name, tuple(sorted(spec.labels.items())))
                prior = self._last_counter.get(key)
                if prior is not None and value is not None and value < prior:
                    reset_series.append({"metric_name": spec.metric_name, "labels": dict(spec.labels), "prior": prior, "current": value})
                self._last_counter[key] = float(value)
        envelope: dict[str, object] = {
            "schema_version": "episode1.native-scrape.v1",
            "binding": vars(self.binding),
            "sequence": self._sequence,
            "scheduled_monotonic_ns": scheduled_ns,
            "observed_monotonic_ns": observed_ns,
            "observed_utc_ns": observed_utc_ns,
            "clock_uncertainty_ns": uncertainty_ns,
            "scrape_start_monotonic_ns": scrape_start,
            "scrape_end_monotonic_ns": self._monotonic(),
            "scrape_deadline_monotonic_ns": request_deadline,
            "scrape_status": scrape_status,
            "scrape_reason": scrape_reason,
            "schedule_lag_ns": max(0, scrape_start - scheduled_ns),
            "observed_process_identity_before": observed_identity_before,
            "observed_process_identity_after": observed_identity_after,
            "raw_kind": raw_kind,
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "raw_base64": base64.b64encode(raw).decode("ascii"),
            "native_samples": native_samples,
            "counter_resets": reset_series,
        }
        projected_raw = self.total_raw_bytes + len(raw)
        encoded_size = len((json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n").encode())
        projected_artifact = self.total_artifact_bytes + encoded_size
        limit_reached = projected_raw > self.max_total_raw_bytes or projected_artifact > self.max_total_artifact_bytes
        if limit_reached:
            raw = b""
            envelope.update({
                "scrape_status": "error", "scrape_reason": "evidence_limit_reached",
                "raw_kind": "omitted_at_retention_bound", "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "raw_base64": "", "native_samples": [
                    {**sample, "value": None, "status": "error", "reason": "scrape_failed"}
                    for sample in native_samples
                ],
            })
            encoded_size = len((json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n").encode())
            if self.total_artifact_bytes + encoded_size > self.max_total_artifact_bytes:
                raise SamplerError("telemetry artifact retention bound reached before error receipt")
            del self.samples[-len(self.metrics):]
            self.samples.extend({key: sample[key] for key in (
                "clock_domain", "monotonic_ns", "process_identity", "process_start_identity",
                "runtime", "block", "metric_name", "labels", "value", "status", "reason"
            )} for sample in envelope["native_samples"])
        path, digest = self.store.persist(self._sequence, envelope)
        self.total_raw_bytes += len(raw)
        self.total_artifact_bytes += encoded_size
        receipt = {
            "sequence": self._sequence,
            "scheduled_monotonic_ns": scheduled_ns,
            "observed_monotonic_ns": observed_ns,
            "scrape_status": envelope["scrape_status"],
            "scrape_reason": envelope["scrape_reason"],
            "raw_sha256": envelope["raw_sha256"],
            "counter_reset_count": len(reset_series),
            "private_path": str(path),
            "file_sha256": digest,
        }
        self.records.append(receipt)
        if limit_reached:
            raise SamplerError("telemetry evidence retention bound reached")
        return receipt

    def collect_schedule(self, start_ns: int, drain_ns: int, hard_deadline_ns: int) -> None:
        """Deterministically collect fixed slots plus an exact final drain slot."""
        if drain_ns < start_ns or hard_deadline_ns < drain_ns:
            raise ValueError("invalid schedule bounds")
        slot = start_ns
        while slot <= drain_ns:
            self.sample_slot(slot, hard_deadline_ns)
            slot += self.interval_ns
        last_slot = slot - self.interval_ns
        if last_slot != drain_ns:
            self.sample_slot(drain_ns, hard_deadline_ns)

    def start(self, *, start_ns: int, hard_deadline_ns: int) -> None:
        if self._thread is not None:
            raise RuntimeError("sampler already started")
        if (isinstance(start_ns, bool) or not isinstance(start_ns, int) or start_ns < 0
                or isinstance(hard_deadline_ns, bool) or not isinstance(hard_deadline_ns, int)
                or hard_deadline_ns <= start_ns + self.reap_reserve_ns + self.finalize_reserve_ns):
            raise ValueError("hard deadline must follow start")
        self._start_ns, self._hard_deadline_ns = start_ns, hard_deadline_ns
        self._work_deadline_ns = hard_deadline_ns - self.reap_reserve_ns
        self._thread = threading.Thread(target=self._worker, name="episode1-native-sampler", daemon=False)
        self._thread.start()

    def _worker(self) -> None:
        assert self._start_ns is not None and self._work_deadline_ns is not None
        next_slot = self._start_ns
        last_slot: int | None = None
        try:
            while True:
                with self._stop_lock:
                    drain = self._drain_ns
                if drain is not None and next_slot > drain:
                    if last_slot != drain:
                        self.sample_slot(drain, self._work_deadline_ns)
                    return
                now = self._monotonic()
                if now >= self._work_deadline_ns:
                    raise TimeoutError("sampler work deadline reached before drain")
                target = next_slot if drain is None else min(next_slot, drain)
                if now < target:
                    self._wake.wait(min((target - now) / 1_000_000_000, 0.25))
                    self._wake.clear()
                    continue
                # Preserve every fixed slot but never issue catch-up traffic for
                # slots older than the most recent due interval.
                if next_slot + self.interval_ns <= now and (drain is None or next_slot < drain):
                    self.sample_slot(next_slot, self._work_deadline_ns, _skip_reason="scheduled_slot_missed")
                    last_slot = next_slot
                    next_slot += self.interval_ns
                    continue
                self.sample_slot(target, self._work_deadline_ns)
                last_slot = target
                if drain is not None and target == drain:
                    return
                next_slot += self.interval_ns
        except BaseException as exc:
            self._worker_error = exc

    def stop(self, *, drain_ns: int, join_deadline_ns: int) -> None:
        thread = self._thread
        if thread is None:
            raise RuntimeError("sampler was not started")
        if (isinstance(drain_ns, bool) or not isinstance(drain_ns, int)
                or isinstance(join_deadline_ns, bool) or not isinstance(join_deadline_ns, int)):
            raise ValueError("drain and join deadline must be integer monotonic timestamps")
        with self._stop_lock:
            if self._start_ns is None or drain_ns < self._start_ns:
                raise ValueError("drain precedes start")
            if self._work_deadline_ns is None or drain_ns > self._work_deadline_ns:
                raise ValueError("drain exceeds sampler work deadline")
            if join_deadline_ns > self._work_deadline_ns:
                raise ValueError("join deadline exceeds the predeclared sampler work deadline")
            if self._drain_ns is None:
                self._drain_ns = drain_ns
        self._wake.set()
        remaining = join_deadline_ns - self._monotonic()
        if remaining <= 0:
            raise TimeoutError("sampler join deadline reached")
        thread.join(remaining / 1_000_000_000)
        if thread.is_alive():
            raise TimeoutError("sampler did not stop by join deadline")
        if self._worker_error is not None:
            raise SamplerError("sampler worker failed") from self._worker_error

    def summarize(self, window: Window, spec: MetricSpec) -> Mapping[str, object]:
        if window.process_identity != self.binding.process_identity or window.process_start_identity != self.binding.process_start_identity:
            raise ValueError("window is not bound to sampler process")
        if window.runtime != self.binding.runtime or window.block != self.binding.block or window.clock_domain != self.binding.clock_domain:
            raise ValueError("window is not bound to sampler runtime/block/clock")
        return summarize(self.samples, window, spec.series(self.binding.runtime))
