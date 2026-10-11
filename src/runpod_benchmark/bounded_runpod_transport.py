"""Bounded, dependency-free transport for the narrow Runpod REST v2 adapter.

The production origin is fixed.  Each request is executed by a previously
started broker process so blocking DNS, connect, TLS, header, and body work can
be cut off by the caller's absolute monotonic deadline.
"""

from __future__ import annotations

import http.client
import base64
import json
import math
import multiprocessing
import os
import selectors
import socket
import ssl
import struct
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode, urlsplit


PRODUCTION_ORIGIN = "https://api.runpod.io/v2"
_ALLOWED_METHODS = frozenset({"GET", "POST", "DELETE"})
_BEARER_HEADER_NAME = "Author" + "ization"


@dataclass(frozen=True)
class Response:
    """Structural match for runpod_v2.Response."""

    status: int
    body: Any
    raw_body: bytes
    completed_monotonic_ns: int


class TransportError(RuntimeError):
    """Base class whose messages contain no response data or credentials."""


class TransportProtocolError(TransportError):
    pass


class TransportNetworkError(TransportError):
    pass


class TransportWorkerError(TransportError):
    pass


class TransportDeadlineExceeded(TimeoutError, TransportError):
    """The HTTP outcome is unresolved; mutation callers must reconcile it."""

    outcome = "unresolved"

    def __init__(self, *, worker_reaped: bool) -> None:
        super().__init__("provider operation deadline reached; HTTP outcome is unresolved")
        self.worker_reaped = worker_reaped


class TransportResponseError(TransportError):
    """Base for failures that retain one bounded, completed HTTP response.

    Consumers may retain ``response`` as failed-call evidence.  The exception
    is never a successful provider result and ``validation_error`` is a closed
    sink-facing classification.
    """

    response: Any
    validation_error: str
    stage: str


class TransportInvalidResponseError(TransportProtocolError, TransportResponseError):
    validation_error = "invalid_body"

    def __init__(self, message: str, *, response: Any, stage: str) -> None:
        TransportProtocolError.__init__(self, message)
        self.response = response
        self.stage = stage


class TransportLateResponseError(TransportDeadlineExceeded, TransportResponseError):
    validation_error = "late_response"

    def __init__(self, *, response: Any, worker_reaped: bool, stage: str) -> None:
        TransportDeadlineExceeded.__init__(self, worker_reaped=worker_reaped)
        self.response = response
        self.stage = stage


@dataclass(frozen=True)
class _RequestSpec:
    method: str
    origin: str
    path: str
    query: tuple[tuple[str, str], ...]
    body_bytes: bytes | None
    bearer_token: str
    deadline_monotonic: float
    max_response_bytes: int


class _SafeFailure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


def _strict_json(raw: bytes) -> Any:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError()
            result[key] = value
        return result

    try:
        text = raw.decode("utf-8", errors="strict")
        return json.loads(
            text,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            object_pairs_hook=unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise _SafeFailure("invalid_json") from None


def _remaining(deadline: float) -> float:
    value = deadline - time.monotonic()
    if value <= 0:
        raise _SafeFailure("deadline")
    return value


def _perform_http(spec: _RequestSpec) -> tuple[str, int, str, int]:
    parsed = urlsplit(spec.origin)
    connection: http.client.HTTPConnection | http.client.HTTPSConnection | None = None
    try:
        timeout = _remaining(spec.deadline_monotonic)
        if parsed.scheme == "https":
            # Default trust roots, certificate validation, and hostname checking.
            context = ssl.create_default_context()
            connection = http.client.HTTPSConnection(
                parsed.hostname,
                parsed.port or 443,
                timeout=timeout,
                context=context,
            )
        elif parsed.scheme == "http":  # admitted only by the loopback test constructor
            connection = http.client.HTTPConnection(
                parsed.hostname, parsed.port or 80, timeout=timeout
            )
        else:  # defensive: constructors already validate this
            raise _SafeFailure("internal")

        target = parsed.path.rstrip("/") + spec.path
        if spec.query:
            target += "?" + urlencode(spec.query, quote_via=quote, safe="")
        headers = {
            "Accept": "application/json",
            "Connection": "close",
            "User-Agent": "episode1-bounded-transport/1",
        }
        headers[_BEARER_HEADER_NAME] = "Bearer " + spec.bearer_token
        if spec.body_bytes is not None:
            headers["Content-Type"] = "application/json"
        connection.timeout = _remaining(spec.deadline_monotonic)
        connection.request(spec.method, target, body=spec.body_bytes, headers=headers)
        if connection.sock is not None:
            connection.sock.settimeout(_remaining(spec.deadline_monotonic))
        response = connection.getresponse()

        lengths = response.headers.get_all("Content-Length", failobj=[])
        transfer_encodings = response.headers.get_all("Transfer-Encoding", failobj=[])
        if len(lengths) > 1:
            raise _SafeFailure("malformed_length")
        if len(transfer_encodings) > 1:
            raise _SafeFailure("ambiguous_framing")
        if transfer_encodings:
            # http.client decodes chunk framing before response.read().  Admit
            # only its single supported framing and reject TE/CL ambiguity.
            if transfer_encodings[0].strip().lower() != "chunked" or lengths:
                raise _SafeFailure("ambiguous_framing")
        declared: int | None = None
        if lengths:
            try:
                declared = int(lengths[0], 10)
            except ValueError:
                raise _SafeFailure("malformed_length") from None
            if declared < 0 or declared > spec.max_response_bytes:
                raise _SafeFailure("oversize")

        chunks: list[bytes] = []
        total = 0
        while True:
            if connection.sock is not None:
                connection.sock.settimeout(_remaining(spec.deadline_monotonic))
            chunk = response.read(min(65_536, spec.max_response_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > spec.max_response_bytes:
                raise _SafeFailure("oversize")
        if declared is not None and total != declared:
            # Bounded response.read(amt) may return EOF without raising
            # IncompleteRead, so verify the declared framing explicitly.
            raise _SafeFailure("truncated_body")
        raw = b"".join(chunks)
        completed_monotonic_ns = time.monotonic_ns()
        # Body validation belongs to the parent.  Returning the exact bounded
        # bytes lets it create a typed failed-response observation without ever
        # presenting invalid, empty, redirect, or late responses as success.
        return (
            "response", response.status,
            base64.b64encode(raw).decode("ascii"), completed_monotonic_ns,
        )
    except _SafeFailure:
        raise
    except (TimeoutError, socket.timeout):
        raise _SafeFailure("deadline") from None
    except ssl.SSLError:
        raise _SafeFailure("tls") from None
    except (OSError, http.client.HTTPException):
        raise _SafeFailure("network") from None
    finally:
        if connection is not None:
            connection.close()


_FRAME_HEADER = struct.Struct("!Q")
_FRAME_OVERHEAD_BYTES = 65_536


def _recv_exact_blocking(channel: socket.socket, size: int) -> bytes | None:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = channel.recv(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _recv_frame_blocking(channel: socket.socket, max_bytes: int) -> bytes | None:
    header = _recv_exact_blocking(channel, _FRAME_HEADER.size)
    if header is None:
        return None
    (length,) = _FRAME_HEADER.unpack(header)
    if length > max_bytes:
        return None
    return _recv_exact_blocking(channel, length)


def _send_frame_blocking(channel: socket.socket, payload: bytes) -> None:
    channel.sendall(_FRAME_HEADER.pack(len(payload)) + payload)


def _wait_socket(channel: socket.socket, event: int, deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    with selectors.DefaultSelector() as selector:
        selector.register(channel, event)
        if not selector.select(remaining):
            raise TimeoutError


def _send_frame_until(channel: socket.socket, payload: bytes, deadline: float) -> None:
    pending = memoryview(_FRAME_HEADER.pack(len(payload)) + payload)
    while pending:
        _wait_socket(channel, selectors.EVENT_WRITE, deadline)
        try:
            sent = channel.send(pending)
        except BlockingIOError:
            continue
        if sent <= 0:
            raise BrokenPipeError
        pending = pending[sent:]


def _recv_exact_until(channel: socket.socket, size: int, deadline: float) -> bytes:
    result = bytearray()
    while len(result) < size:
        _wait_socket(channel, selectors.EVENT_READ, deadline)
        try:
            chunk = channel.recv(size - len(result))
        except BlockingIOError:
            continue
        if not chunk:
            raise EOFError
        result.extend(chunk)
    return bytes(result)


def _recv_frame_until(channel: socket.socket, max_bytes: int, deadline: float) -> bytes:
    header = _recv_exact_until(channel, _FRAME_HEADER.size, deadline)
    (length,) = _FRAME_HEADER.unpack(header)
    if length > max_bytes:
        raise ValueError("oversize IPC frame")
    return _recv_exact_until(channel, length, deadline)


def _encode_spec(spec: _RequestSpec) -> bytes:
    value = {
        "method": spec.method,
        "origin": spec.origin,
        "path": spec.path,
        "query": [list(item) for item in spec.query],
        "body": None if spec.body_bytes is None else spec.body_bytes.decode("utf-8"),
        "bearer_token": spec.bearer_token,
        "deadline_monotonic": spec.deadline_monotonic,
        "max_response_bytes": spec.max_response_bytes,
    }
    return json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8")


def _decode_spec(raw: bytes) -> _RequestSpec:
    value = _strict_json(raw)
    if not isinstance(value, dict) or set(value) != {
        "method", "origin", "path", "query", "body", "bearer_token",
        "deadline_monotonic", "max_response_bytes",
    }:
        raise _SafeFailure("internal")
    try:
        query = tuple((item[0], item[1]) for item in value["query"])
        body = None if value["body"] is None else value["body"].encode("utf-8")
        return _RequestSpec(
            value["method"], value["origin"], value["path"], query, body,
            value["bearer_token"], value["deadline_monotonic"], value["max_response_bytes"],
        )
    except (AttributeError, IndexError, KeyError, TypeError):
        raise _SafeFailure("internal") from None


def _broker(
    channel: socket.socket,
    operation: Callable[[_RequestSpec], tuple[str, int, str, int]],
    max_frame_bytes: int,
) -> None:
    while True:
        try:
            raw = _recv_frame_blocking(channel, max_frame_bytes)
        except OSError:
            return
        if raw is None or raw == b"null":
            return
        try:
            result = operation(_decode_spec(raw))
        except _SafeFailure as exc:
            result = ("error", exc.code)
        except BaseException:
            result = ("error", "internal")
        try:
            encoded = json.dumps(result, allow_nan=False, separators=(",", ":")).encode("utf-8")
            _send_frame_blocking(channel, encoded)
        except (BrokenPipeError, OSError, TypeError, ValueError):
            return


class BoundedRunpodTransport:
    """Single-caller transport implementing the candidate Transport protocol."""

    def __init__(
        self,
        bearer_token: str,
        *,
        max_response_bytes: int = 2 * 1024 * 1024,
        max_request_bytes: int = 1024 * 1024,
        cleanup_reserve_seconds: float = 1.0,
        response_factory: Callable[[int, Any, bytes, int], Any] = Response,
        _origin: str = PRODUCTION_ORIGIN,
        _operation: Callable[[_RequestSpec], tuple[str, int, str, int]] = _perform_http,
        _allow_loopback_http: bool = False,
    ) -> None:
        self._validate_token(bearer_token)
        self._origin = self._validate_origin(_origin, _allow_loopback_http)
        if isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int) or max_response_bytes < 1:
            raise ValueError("max_response_bytes must be a positive integer")
        if isinstance(max_request_bytes, bool) or not isinstance(max_request_bytes, int) or max_request_bytes < 1:
            raise ValueError("max_request_bytes must be a positive integer")
        if not math.isfinite(cleanup_reserve_seconds) or cleanup_reserve_seconds <= 0:
            raise ValueError("cleanup_reserve_seconds must be finite and positive")
        self._bearer_token = bearer_token
        self._max_response_bytes = max_response_bytes
        self._max_request_bytes = max_request_bytes
        self._cleanup_reserve_seconds = float(cleanup_reserve_seconds)
        self._response_factory = response_factory
        self._lock = threading.Lock()
        self._poisoned = False
        self._closed = False
        context = multiprocessing.get_context("spawn")
        self._connection, child_connection = socket.socketpair()
        self._connection.setblocking(False)
        encoded_response_bytes = ((max_response_bytes + 2) // 3) * 4
        max_frame_bytes = max(max_request_bytes, encoded_response_bytes) + _FRAME_OVERHEAD_BYTES
        self._max_frame_bytes = max_frame_bytes
        self._process = context.Process(
            target=_broker,
            args=(child_connection, _operation, max_frame_bytes),
            name="episode1-http-broker",
            daemon=True,
        )
        self._process.start()
        child_connection.close()

    @classmethod
    def for_loopback_test(cls, bearer_token: str, origin: str, **kwargs: Any) -> "BoundedRunpodTransport":
        """Explicit test-only entry point; accepts only numeric loopback hosts."""

        return cls(
            bearer_token,
            _origin=origin,
            _allow_loopback_http=True,
            **kwargs,
        )

    @staticmethod
    def _validate_token(value: str) -> None:
        if not isinstance(value, str) or not value or "\r" in value or "\n" in value:
            raise ValueError("bearer_token must be a nonempty header-safe string")

    @staticmethod
    def _validate_origin(value: str, allow_loopback_http: bool) -> str:
        if value == PRODUCTION_ORIGIN:
            return value
        parsed = urlsplit(value)
        allowed_host = parsed.hostname in {"127.0.0.1", "::1"}
        clean = not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
        if (
            allow_loopback_http
            and parsed.scheme == "http"
            and allowed_host
            and parsed.port is not None
            and clean
            and parsed.path == "/v2"
        ):
            return value.rstrip("/")
        raise ValueError("origin is not the fixed production endpoint or an explicit loopback test endpoint")

    @staticmethod
    def _validate_path(path: str) -> None:
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise ValueError("path must be an absolute API path")
        if any(character.isspace() or ord(character) < 32 for character in path):
            raise ValueError("path contains forbidden characters")
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or "\\" in path:
            raise ValueError("path may not contain an origin, query, fragment, or backslash")
        if any(segment in {".", ".."} for segment in path.split("/")):
            raise ValueError("path traversal segments are forbidden")

    @staticmethod
    def _validate_deadline(value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("deadline_monotonic must be a finite number")
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("deadline_monotonic must be a finite number")
        return value

    @staticmethod
    def _query_items(query: Mapping[str, str] | None) -> tuple[tuple[str, str], ...]:
        if query is None:
            return ()
        if not isinstance(query, Mapping):
            raise ValueError("query must be a mapping")
        items: list[tuple[str, str]] = []
        for key, value in query.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("query keys and values must be strings")
            items.append((key, value))
        return tuple(sorted(items))

    def _encode_body(self, body: Mapping[str, Any] | None) -> bytes | None:
        if body is None:
            return None
        if not isinstance(body, Mapping):
            raise ValueError("json_body must be a mapping")
        try:
            raw = json.dumps(
                body, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
        except (TypeError, ValueError):
            raise ValueError("json_body is not strict JSON") from None
        if len(raw) > self._max_request_bytes:
            raise ValueError("json_body exceeds the configured byte limit")
        return raw

    def _reap_until(self, cutoff: float) -> bool:
        self._poisoned = True
        if self._process.is_alive():
            self._process.terminate()
        remaining = max(0.0, cutoff - time.monotonic())
        self._process.join(remaining / 2)
        if self._process.is_alive() and hasattr(self._process, "kill"):
            self._process.kill()
            self._process.join(max(0.0, cutoff - time.monotonic()))
        return not self._process.is_alive()

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
        deadline_monotonic: float,
    ) -> Any:
        if method not in _ALLOWED_METHODS:
            raise ValueError("method is outside the closed REST v2 subset")
        self._validate_path(path)
        deadline = self._validate_deadline(deadline_monotonic)
        query_items = self._query_items(query)
        body_bytes = self._encode_body(json_body)
        if method != "POST" and body_bytes is not None:
            raise ValueError("only POST accepts json_body")
        if time.monotonic() >= deadline:
            raise TransportDeadlineExceeded(worker_reaped=not self._process.is_alive())
        io_deadline = deadline - self._cleanup_reserve_seconds
        if time.monotonic() >= io_deadline:
            reaped = self._reap_until(deadline)
            raise TransportDeadlineExceeded(worker_reaped=reaped)

        acquired = self._lock.acquire(timeout=max(0.0, io_deadline - time.monotonic()))
        if not acquired:
            reaped = self._reap_until(deadline)
            raise TransportDeadlineExceeded(worker_reaped=reaped)
        try:
            if self._closed or self._poisoned or not self._process.is_alive():
                raise TransportWorkerError("transport worker is unavailable")
            spec = _RequestSpec(
                method,
                self._origin,
                path,
                query_items,
                body_bytes,
                self._bearer_token,
                io_deadline,
                self._max_response_bytes,
            )
            try:
                _send_frame_until(self._connection, _encode_spec(spec), io_deadline)
            except TimeoutError:
                reaped = self._reap_until(deadline)
                raise TransportDeadlineExceeded(worker_reaped=reaped) from None
            except (BrokenPipeError, EOFError, OSError):
                self._poisoned = True
                raise TransportWorkerError("transport worker failed") from None
            try:
                raw_result = _recv_frame_until(
                    self._connection,
                    self._max_frame_bytes,
                    io_deadline,
                )
                received_monotonic_ns = time.monotonic_ns()
            except TimeoutError:
                reaped = self._reap_until(deadline)
                raise TransportDeadlineExceeded(worker_reaped=reaped) from None
            except (EOFError, OSError, ValueError):
                self._poisoned = True
                raise TransportWorkerError("transport worker failed") from None
            try:
                result = _strict_json(raw_result)
            except (_SafeFailure, ValueError):
                self._poisoned = True
                raise TransportWorkerError("transport worker returned an invalid result") from None
            if not isinstance(result, list) or not result:
                self._poisoned = True
                raise TransportWorkerError("transport worker returned an invalid result")
            if result[0] == "response" and len(result) == 4:
                status = result[1]
                if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
                    self._poisoned = True
                    raise TransportWorkerError("transport worker returned an invalid result")
                encoded_raw, completed_monotonic_ns = result[2], result[3]
                if not isinstance(encoded_raw, str):
                    self._poisoned = True
                    raise TransportWorkerError("transport worker returned an invalid result")
                try:
                    exact_raw = base64.b64decode(encoded_raw, validate=True)
                except (ValueError, TypeError):
                    self._poisoned = True
                    raise TransportWorkerError("transport worker returned an invalid result") from None
                if (
                    len(exact_raw) > self._max_response_bytes
                    or isinstance(completed_monotonic_ns, bool)
                    or not isinstance(completed_monotonic_ns, int)
                    or completed_monotonic_ns < 1
                    or completed_monotonic_ns > received_monotonic_ns
                ):
                    self._poisoned = True
                    raise TransportWorkerError("transport worker returned an invalid result")
                completion_late = completed_monotonic_ns >= math.ceil(
                    io_deadline * 1_000_000_000
                )
                if not exact_raw and (
                    (method == "DELETE" and status == 204)
                    or (method == "GET" and status == 404)
                ):
                    parsed_body = None
                    body_error = None
                elif not exact_raw:
                    parsed_body = None
                    body_error = "empty_body"
                else:
                    try:
                        parsed_body = _strict_json(exact_raw)
                    except _SafeFailure:
                        parsed_body = None
                        body_error = "invalid_json"
                    else:
                        body_error = None
                result_value = self._response_factory(
                    status, parsed_body, exact_raw, completed_monotonic_ns
                )
                if completion_late or time.monotonic() > io_deadline:
                    reaped = self._reap_until(deadline)
                    raise TransportLateResponseError(
                        response=result_value,
                        worker_reaped=reaped,
                        stage=(
                            "body_completed_after_deadline"
                            if completion_late else "post_decode_deadline"
                        ),
                    )
                if 300 <= status <= 399:
                    raise TransportInvalidResponseError(
                        "provider redirect responses are forbidden",
                        response=result_value,
                        stage="redirect_response",
                    )
                if body_error is not None:
                    description = (
                        "provider response body is unexpectedly empty"
                        if body_error == "empty_body"
                        else "provider response is not strict JSON"
                    )
                    raise TransportInvalidResponseError(
                        description,
                        response=result_value,
                        stage=body_error,
                    )
                return result_value
            if result[0] == "error" and len(result) == 2:
                code = result[1]
                if code == "deadline":
                    reaped = self._reap_until(deadline)
                    raise TransportDeadlineExceeded(worker_reaped=reaped)
                if code in {
                    "oversize", "malformed_length", "ambiguous_framing",
                    "truncated_body",
                }:
                    descriptions = {
                        "oversize": "provider response exceeds the configured byte limit",
                        "malformed_length": "provider response has an invalid Content-Length",
                        "ambiguous_framing": "provider response has ambiguous HTTP body framing",
                        "truncated_body": "provider response body ended before Content-Length",
                    }
                    raise TransportProtocolError(descriptions[code])
                if code in {"tls", "network"}:
                    raise TransportNetworkError("provider TLS/network operation failed")
                raise TransportWorkerError("transport worker failed")
            self._poisoned = True
            raise TransportWorkerError("transport worker returned an invalid result")
        finally:
            self._lock.release()

    def close(self, *, deadline_monotonic: float | None = None) -> bool:
        """Stop and reap the broker within one absolute cleanup cutoff."""

        cutoff = (
            time.monotonic() + self._cleanup_reserve_seconds
            if deadline_monotonic is None else self._validate_deadline(deadline_monotonic)
        )
        acquired = self._lock.acquire(timeout=max(0.0, cutoff - time.monotonic()))
        if not acquired:
            return False
        try:
            if self._closed:
                return not self._process.is_alive()
            self._closed = True
            if self._process.is_alive() and not self._poisoned:
                try:
                    _send_frame_until(
                        self._connection,
                        b"null",
                        cutoff,
                    )
                except (BrokenPipeError, EOFError, OSError, TimeoutError):
                    pass
            remaining = max(0.0, cutoff - time.monotonic())
            self._process.join(remaining / 2)
            if self._process.is_alive():
                self._reap_until(cutoff)
            self._connection.close()
            return not self._process.is_alive()
        finally:
            self._lock.release()

    def __enter__(self) -> "BoundedRunpodTransport":
        return self

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(origin={self._origin!r}, "
            f"max_response_bytes={self._max_response_bytes!r}, closed={self._closed!r})"
        )
