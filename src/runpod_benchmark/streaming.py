"""Bounded OpenAI-compatible endpoint probing and SSE streaming."""

from __future__ import annotations

import codecs
import http.client
import ipaddress
import json
import math
import socket
import threading
import time
import urllib.request
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlsplit

MAX_ERROR_REDACTION_INPUT_CHARS = 64 * 1024
MAX_ERROR_SECRET_CHARS = 4096
REDACTION_MARKER = "[REDACTED]"
_OPTIMIZATION_KEYS = {
    "streaming",
    "prefix_caching",
    "continuous_batching",
    "chunked_prefill",
    "weight_quantization",
    "kv_cache_dtype",
    "speculative_decoding",
}
SUPPORTED_RUNTIME_DIALECTS = {
    "transformers-baseline",
    "vllm",
    "sglang",
    "tgi",
    "tensorrt_llm",
}
REQUIRED_STREAM_CAPABILITIES = {
    "streaming_sse",
    "done_event",
    "streamed_usage",
    "exact_completion_tokens",
}
STREAM_REQUEST_FIELDS = {
    "url", "runtime_id", "runtime_capabilities", "model", "messages",
    "maximum_output_tokens", "temperature", "top_p", "seed", "timeout_seconds",
    "max_response_bytes", "absolute_deadline_ns", "cancel_event", "api_key",
    "acknowledge_insecure_non_loopback_http", "thinking_enabled",
}


class ExperimentValidationError(ValueError):
    """Raised when an endpoint identity is unsafe or does not match the request."""


def _secret_text_variants(secret: str) -> set[str]:
    variants = {secret, repr(secret.encode("utf-8"))[2:-1]}
    for ensure_ascii in (False, True):
        rendered = json.dumps(secret, ensure_ascii=ensure_ascii)
        variants.add(rendered[1:-1])
    return {variant for variant in variants if variant}


def bounded_redact_environment_values(
    value: str,
    secret_values: tuple[str, ...],
    *,
    output_cap: int,
    input_cap: int = MAX_ERROR_REDACTION_INPUT_CHARS,
) -> str:
    """Redact raw and JSON-escaped secret renderings before truncation."""

    secrets = tuple(secret for secret in secret_values if isinstance(secret, str) and secret)
    if not secrets:
        return value[:output_cap]
    if any(len(secret) > MAX_ERROR_SECRET_CHARS for secret in secrets):
        return REDACTION_MARKER
    variants = sorted(
        {variant for secret in secrets for variant in _secret_text_variants(secret)},
        key=len,
        reverse=True,
    )
    output: list[str] = []
    output_length = 0
    source_index = 0
    source_limit = min(len(value), input_cap)
    while source_index < source_limit and output_length < output_cap:
        matched = next(
            (variant for variant in variants if value.startswith(variant, source_index)),
            None,
        )
        if matched is not None:
            if output_length + len(REDACTION_MARKER) > output_cap:
                retained = "".join(output)[: output_cap - len(REDACTION_MARKER)]
                return retained + REDACTION_MARKER
            output.append(REDACTION_MARKER)
            output_length += len(REDACTION_MARKER)
            source_index += len(matched)
            continue
        output.append(value[source_index])
        output_length += 1
        source_index += 1
    return "".join(output)


def validate_endpoint_identity(
    value: Any,
    *,
    expected_runtime_id: str | None = None,
    expected_model: str | None = None,
    expected_runtime_version: str | None = None,
) -> dict[str, Any]:
    """Validate the endpoint identity fields safe to retain as evidence."""

    if not isinstance(value, dict) or set(value) != {
        "runtime_id", "model", "runtime_version", "effective_settings"
    }:
        raise ExperimentValidationError("endpoint identity has invalid fields")
    runtime_id = value["runtime_id"]
    model = value["model"]
    runtime_version = value["runtime_version"]
    settings = value["effective_settings"]
    if not isinstance(runtime_id, str) or not 1 <= len(runtime_id) <= 32:
        raise ExperimentValidationError("runtime_id must be a bounded string")
    if not isinstance(model, str) or not 1 <= len(model) <= 512:
        raise ExperimentValidationError("model must be a bounded string")
    if runtime_version is not None and (
        not isinstance(runtime_version, str) or not 1 <= len(runtime_version) <= 64
    ):
        raise ExperimentValidationError("runtime_version must be a bounded string or null")
    if not isinstance(settings, dict) or not set(settings) <= _OPTIMIZATION_KEYS:
        raise ExperimentValidationError("effective_settings has invalid fields")
    for setting in settings.values():
        if isinstance(setting, (dict, list)) or not isinstance(
            setting, (str, int, float, bool, type(None))
        ):
            raise ExperimentValidationError("effective settings must be scalar JSON values")
        if isinstance(setting, float) and not math.isfinite(setting):
            raise ExperimentValidationError("effective settings must be finite")
    if expected_runtime_id is not None and runtime_id != expected_runtime_id:
        raise ExperimentValidationError("runtime_id does not match the requested runtime")
    if expected_model is not None and model != expected_model:
        raise ExperimentValidationError("model does not match the requested model")
    if expected_runtime_version is not None and runtime_version != expected_runtime_version:
        raise ExperimentValidationError("runtime_version does not match the requested version")
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ExperimentValidationError(f"endpoint identity must be JSON-safe: {exc}") from exc


MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_PROBE_BYTES = 1024 * 1024
TRANSPORT_ABORT_SETTLE_SECONDS = 0.02
# libc resolution cannot be interrupted. Stalled DNS-only workers retain one
# of these process-wide slots until they exit; retries cannot accumulate workers.
MAX_RESOLVER_WORKERS = 8
_RESOLVER_SLOTS = threading.BoundedSemaphore(MAX_RESOLVER_WORKERS)


class StreamingError(RuntimeError):
    """An operator-safe transport or streaming protocol failure."""

    def __init__(
        self,
        message: str,
        *,
        actual_send_ns: int | None = None,
        deadline_exceeded: bool = False,
        request_timed_out: bool = False,
    ) -> None:
        super().__init__(message)
        self.actual_send_ns = actual_send_ns
        self.deadline_exceeded = deadline_exceeded
        self.request_timed_out = request_timed_out


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise StreamingError(f"HTTP redirect refused ({code})")


class _TransportAborted(OSError):
    pass


class _Resolution:
    """DNS data only: never retains a request, owner, socket, or credential."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.done = threading.Event()
        self.addresses: list[Any] = []
        self.error: BaseException | None = None


def _resolve_host(result: _Resolution) -> None:
    try:
        result.addresses = socket.getaddrinfo(result.host, result.port, 0, socket.SOCK_STREAM)
    except BaseException as exc:
        result.error = exc.with_traceback(None)
    finally:
        result.done.set()
        _RESOLVER_SLOTS.release()


def _resolve_with_deadline(host: str, port: int, owner: _TransportOwner) -> list[Any]:
    # There is no pending-job queue. Waiting for DNS capacity consumes only the
    # caller's existing concurrency slot and the same absolute request budget.
    while True:
        remaining = owner.remaining_seconds()
        if _RESOLVER_SLOTS.acquire(timeout=min(0.01, remaining)):
            break
    try:
        owner.ensure_active()
        result = _Resolution(host, port)
        worker = threading.Thread(
            target=_resolve_host,
            args=(result,),
            name="benchmark-dns-resolver",
            daemon=True,
        )
        worker.start()
    except BaseException:
        _RESOLVER_SLOTS.release()
        raise
    while not result.done.wait(min(0.01, owner.remaining_seconds())):
        pass
    worker.join()
    owner.ensure_active()
    if result.error is not None:
        raise result.error
    return result.addresses


class _TransportOwner:
    """Synchronize cancellation with connection and response ownership."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._connection: Any = None
        self._response: Any = None
        self._aborted_reason: str | None = None
        self._clock: Callable[[], int] = time.monotonic_ns
        self._actual_send_ns: int | None = None
        self._deadline_ns: int | None = None
        self._cancel_event: Any = None
        self._transport_closed = False

    def configure(
        self,
        clock: Callable[[], int],
        deadline_ns: int,
        cancel_event: Any,
    ) -> None:
        with self._lock:
            self._clock = clock
            self._deadline_ns = deadline_ns
            self._cancel_event = cancel_event

    @property
    def actual_send_ns(self) -> int | None:
        with self._lock:
            return self._actual_send_ns

    @property
    def aborted_reason(self) -> str | None:
        with self._lock:
            return self._aborted_reason

    def attach_connection(self, connection: Any) -> None:
        with self._lock:
            if self._aborted_reason is not None:
                rejected = True
            else:
                self._connection = connection
                rejected = False
        if rejected:
            _abort_connection(connection)
            raise _TransportAborted("transport ownership was cancelled")

    def ensure_active(self) -> None:
        if self._cancel_event is not None and self._cancel_event.is_set():
            self.abort("cancelled")
        elif self._deadline_ns is not None and time.monotonic_ns() >= self._deadline_ns:
            self.abort("timeout")
        with self._lock:
            if self._aborted_reason is not None:
                raise _TransportAborted("transport ownership was cancelled")

    def remaining_seconds(self) -> float:
        self.ensure_active()
        assert self._deadline_ns is not None
        return max((self._deadline_ns - time.monotonic_ns()) / 1_000_000_000, 0.000001)

    def create_socket(self, connection: Any, family: int, kind: int, protocol: int) -> Any:
        self.ensure_active()
        with self._lock:
            if self._aborted_reason is not None:
                raise _TransportAborted("transport ownership was cancelled")
            connection.sock = socket.socket(family, kind, protocol)
            return connection.sock

    def mark_send(self) -> int:
        with self._lock:
            if self._aborted_reason is not None:
                raise _TransportAborted("transport ownership was cancelled")
            if self._actual_send_ns is None:
                self._actual_send_ns = self._clock()
            return self._actual_send_ns

    def claim_response(self, response: Any) -> bool:
        with self._lock:
            if self._aborted_reason is not None:
                claimed = False
            else:
                self._response = response
                claimed = True
        if not claimed:
            _close_response_transport(response)
        return claimed

    def abort(self, reason: str = "cancelled") -> None:
        with self._lock:
            if self._aborted_reason is None:
                self._aborted_reason = reason
            connection = self._connection
            response = self._response
        self.close_transport(response=response, connection=connection)

    def close_transport(self, *, response: Any = None, connection: Any = None) -> None:
        with self._lock:
            if self._transport_closed:
                return
            self._transport_closed = True
            owned_response = response if response is not None else self._response
            owned_connection = connection if connection is not None else self._connection
        if owned_response is not None:
            _close_response_transport(owned_response)
        if owned_connection is not None:
            _abort_connection(owned_connection)

    def release(self) -> None:
        with self._lock:
            self._connection = None
            self._response = None


def _abort_connection(connection: Any) -> None:
    transport_socket = getattr(connection, "sock", None)
    if transport_socket is not None:
        try:
            transport_socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        transport_socket.close()
    connection.close()


class _OwnedConnectionMixin:
    def __init__(self, *args: Any, owner: _TransportOwner, **kwargs: Any) -> None:
        self._transport_owner = owner
        super().__init__(*args, **kwargs)
        # Keep self.host/self.port and the request URL intact for Host, TLS SNI,
        # certificate verification, and proxy tunnel semantics. Only replace the
        # resolver/connect operation, never the endpoint's logical identity.
        # HTTPConnection installs an instance factory. Remove it to expose the
        # class override without retaining a bound-method reference cycle.
        del self._create_connection
        owner.attach_connection(self)

    def _create_connection(
        self,
        address: tuple[str, int],
        timeout: float,
        source_address: Any = None,
    ) -> Any:
        owner = self._transport_owner
        if address != (self.host, self.port):
            raise StreamingError("connection endpoint identity changed during resolution")
        addresses = _resolve_with_deadline(self.host, self.port, owner)
        error: OSError | None = None
        for family, kind, protocol, _, sockaddr in addresses:
            # Numeric address tuples avoid a second, unbounded getaddrinfo call.
            # Publish each socket before connect, so the watchdog can abort it.
            transport_socket = None
            try:
                transport_socket = owner.create_socket(self, family, kind, protocol)
                transport_socket.settimeout(owner.remaining_seconds())
                if source_address is not None:
                    transport_socket.bind(source_address)
                owner.ensure_active()
                transport_socket.connect(sockaddr)
                owner.ensure_active()
                # A previous address failure retains this frame via its
                # traceback unless cleared before the successful return.
                error = None
                return transport_socket
            except OSError as exc:
                if transport_socket is not None:
                    transport_socket.close()
                error = exc
                owner.ensure_active()
        if error is not None:
            raise error
        raise OSError("getaddrinfo returns an empty list")

    def connect(self) -> None:
        self._transport_owner.ensure_active()
        super().connect()
        try:
            self._transport_owner.ensure_active()
        except _TransportAborted:
            _abort_connection(self)
            raise

    def send(self, data: Any) -> None:
        if self.sock is None:
            if self.auto_open:
                self.connect()
            else:
                raise http.client.NotConnected()
        self._transport_owner.ensure_active()
        self._transport_owner.mark_send()
        super().send(data)


class _OwnedHTTPConnection(_OwnedConnectionMixin, http.client.HTTPConnection):
    pass


class _OwnedHTTPSConnection(_OwnedConnectionMixin, http.client.HTTPSConnection):
    pass


class _OwnedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, owner: _TransportOwner) -> None:
        super().__init__()
        self._transport_owner = owner

    def http_open(self, req: urllib.request.Request) -> Any:
        owner = self._transport_owner

        def connection(host: str, **kwargs: Any) -> _OwnedHTTPConnection:
            return _OwnedHTTPConnection(host, owner=owner, **kwargs)

        return self.do_open(connection, req)


class _OwnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, owner: _TransportOwner) -> None:
        super().__init__()
        self._transport_owner = owner

    def https_open(self, req: urllib.request.Request) -> Any:
        owner = self._transport_owner

        def connection(host: str, **kwargs: Any) -> _OwnedHTTPSConnection:
            return _OwnedHTTPSConnection(host, owner=owner, **kwargs)

        return self.do_open(connection, req, context=self._context)


def _is_loopback(hostname: str | None) -> bool:
    if hostname is None:
        return False
    normalized = hostname.rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def require_safe_http_url(url: object, *, acknowledge_insecure_non_loopback_http: bool = False) -> str:
    """Validate an HTTP(S) URL without resolving a hostname or following redirects."""

    if not isinstance(url, str) or len(url) > 2048:
        raise StreamingError("endpoint URL must be a bounded absolute HTTP(S) URL")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise StreamingError("endpoint URL must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise StreamingError("endpoint URL must not contain credentials or a fragment")
    if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
        if acknowledge_insecure_non_loopback_http is not True:
            raise StreamingError(
                "plain HTTP to a non-loopback endpoint requires "
                "acknowledge_insecure_non_loopback_http: true"
            )
    return url


def _opener(url: str) -> urllib.request.OpenerDirector:
    owner = _TransportOwner()
    handlers: list[Any] = [
        _NoRedirect(),
        _OwnedHTTPHandler(owner),
        _OwnedHTTPSHandler(owner),
    ]
    if _is_loopback(urlsplit(url).hostname):
        handlers.insert(0, urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    opener._transport_owner = owner  # type: ignore[attr-defined]
    return opener


def _redacted_message(exc: BaseException, api_key: object) -> str:
    return bounded_redact_environment_values(
        str(exc) or type(exc).__name__,
        (api_key,) if isinstance(api_key, str) and api_key else (),
        output_cap=1024,
    )


def _positive_timeout(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value <= 0
    ):
        raise StreamingError("timeout_seconds must be positive")
    return float(value)


def _bounded_cap(value: object, maximum: int) -> int:
    if value is None:
        return maximum
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= maximum:
        raise StreamingError(f"max_response_bytes must be between 1 and {maximum}")
    return value


def _absolute_deadline(
    timeout: float,
    explicit_deadline_ns: object = None,
    *,
    started_ns: int | None = None,
) -> tuple[int, str]:
    request_deadline_ns = (started_ns or time.monotonic_ns()) + int(timeout * 1_000_000_000)
    deadline_ns = request_deadline_ns
    timeout_kind = "request"
    if explicit_deadline_ns is not None:
        if (
            isinstance(explicit_deadline_ns, bool)
            or not isinstance(explicit_deadline_ns, int)
            or explicit_deadline_ns <= 0
        ):
            raise StreamingError("absolute_deadline_ns must be a positive monotonic timestamp")
        if explicit_deadline_ns <= request_deadline_ns:
            deadline_ns = explicit_deadline_ns
            timeout_kind = "run"
    return deadline_ns, timeout_kind


def _remaining_seconds(
    deadline_ns: int,
    *,
    actual_send_ns: int | None = None,
    timeout_kind: str = "request",
) -> float:
    remaining = (deadline_ns - time.monotonic_ns()) / 1_000_000_000
    if remaining <= 0:
        raise StreamingError(
            "absolute request deadline exceeded (timed out)",
            actual_send_ns=actual_send_ns,
            deadline_exceeded=timeout_kind == "run",
            request_timed_out=timeout_kind == "request",
        )
    return remaining


def _response_sockets(response: Any) -> tuple[Any, Any]:
    return (
        getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None),
        getattr(getattr(response, "fp", None), "_sock", None),
    )


def _set_response_timeout(response: Any, timeout: float) -> None:
    """Best-effort update of urllib's underlying socket timeout."""

    candidates = _response_sockets(response)
    for candidate in candidates:
        setter = getattr(candidate, "settimeout", None)
        if callable(setter):
            setter(timeout)
            return


def _close_response_transport(response: Any) -> None:
    """Close both the buffered response and its retained socket object."""

    sockets = _response_sockets(response)
    # Abort the kernel read before asking buffered wrappers to close.  Calling
    # HTTPResponse.close() first can wait behind a thread blocked in read().
    for candidate in sockets:
        shutdown = getattr(candidate, "shutdown", None)
        if callable(shutdown):
            try:
                shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        close = getattr(candidate, "close", None)
        if callable(close):
            close()
    try:
        response.close()
    finally:
        for candidate in sockets:
            close = getattr(candidate, "close", None)
            if callable(close):
                close()


@contextmanager
def _closing_response(response: Any) -> Any:
    try:
        yield response
    finally:
        cleanup = getattr(response, "_benchmark_transport_cleanup", None)
        if callable(cleanup):
            cleanup()
        else:
            _close_response_transport(response)


def _read_bounded(
    response: Any,
    cap: int,
    deadline_ns: int,
    *,
    timeout_kind: str = "request",
) -> bytes:
    declared = response.headers.get("Content-Length")
    if declared is not None:
        try:
            if int(declared) > cap:
                raise StreamingError(f"response byte cap exceeded ({cap})")
        except ValueError as exc:
            raise StreamingError("invalid Content-Length response header") from exc
    chunks: list[bytes] = []
    total = 0
    read_available = getattr(response, "read1", response.read)
    while True:
        remaining = _remaining_seconds(deadline_ns, timeout_kind=timeout_kind)
        _set_response_timeout(response, remaining)
        block = read_available(min(4096, cap + 1 - total))
        _remaining_seconds(deadline_ns, timeout_kind=timeout_kind)
        if not block:
            break
        total += len(block)
        if total > cap:
            raise StreamingError(f"response byte cap exceeded ({cap})")
        chunks.append(block)
        if declared is not None and total >= int(declared):
            break
    return b"".join(chunks)


def _open_with_deadline(
    opener: urllib.request.OpenerDirector,
    request: urllib.request.Request,
    deadline_ns: int,
    *,
    timeout_kind: str,
    cancel_event: Any = None,
    clock: Callable[[], int] = time.monotonic_ns,
) -> tuple[Any, int | None]:
    """Synchronously own open/send while a joined watchdog can abort its socket."""

    owner = getattr(opener, "_transport_owner", None)
    if not isinstance(owner, _TransportOwner):
        raise StreamingError("HTTP opener does not expose deterministic transport ownership")
    owner.configure(clock, deadline_ns, cancel_event)
    stopped = threading.Event()

    def enforce_boundary() -> None:
        while not stopped.is_set():
            if cancel_event is not None and cancel_event.is_set():
                owner.abort("cancelled")
                time.sleep(TRANSPORT_ABORT_SETTLE_SECONDS)
                return
            remaining_ns = deadline_ns - time.monotonic_ns()
            if remaining_ns <= 0:
                owner.abort("timeout")
                time.sleep(TRANSPORT_ABORT_SETTLE_SECONDS)
                return
            stopped.wait(min(0.01, remaining_ns / 1_000_000_000))

    watchdog = threading.Thread(
        target=enforce_boundary,
        name="benchmark-transport-watchdog",
    )
    watchdog.start()
    transferred = False
    try:
        try:
            response = opener.open(
                request,
                timeout=_remaining_seconds(
                    deadline_ns,
                    timeout_kind=timeout_kind,
                ),
            )
        except BaseException:
            reason = owner.aborted_reason
            if reason == "cancelled":
                raise StreamingError(
                    "request cancelled",
                    actual_send_ns=owner.actual_send_ns,
                ) from None
            if reason == "timeout":
                raise StreamingError(
                    "absolute request deadline exceeded (timed out)",
                    actual_send_ns=owner.actual_send_ns,
                    deadline_exceeded=timeout_kind == "run",
                    request_timed_out=timeout_kind == "request",
                ) from None
            raise
        if not owner.claim_response(response):
            reason = owner.aborted_reason
            if reason == "timeout":
                raise StreamingError(
                    "absolute request deadline exceeded (timed out)",
                    actual_send_ns=owner.actual_send_ns,
                    deadline_exceeded=timeout_kind == "run",
                    request_timed_out=timeout_kind == "request",
                )
            raise StreamingError(
                "request cancelled",
                actual_send_ns=owner.actual_send_ns,
            )
        reason = owner.aborted_reason
        if reason is not None:
            owner.close_transport(response=response)
            if reason == "timeout":
                raise StreamingError(
                    "absolute request deadline exceeded (timed out)",
                    actual_send_ns=owner.actual_send_ns,
                    deadline_exceeded=timeout_kind == "run",
                    request_timed_out=timeout_kind == "request",
                )
            raise StreamingError(
                "request cancelled",
                actual_send_ns=owner.actual_send_ns,
            )
        cleanup_lock = threading.Lock()
        cleaned = False

        def cleanup() -> None:
            nonlocal cleaned
            with cleanup_lock:
                if cleaned:
                    return
                cleaned = True
            owner.close_transport(response=response)
            stopped.set()
            watchdog.join()
            owner.release()

        response._benchmark_transport_cleanup = cleanup
        response._benchmark_transport_owner = owner
        transferred = True
        return response, owner.actual_send_ns
    finally:
        if not transferred:
            stopped.set()
            watchdog.join()
            owner.release()


def probe_endpoint(runtime: Mapping[str, Any], api_key: str | None = None) -> dict[str, Any]:
    """Probe ``/v1/models`` and return the bounded endpoint identity."""

    timeout_kind = "request"
    transport_owner: _TransportOwner | None = None
    try:
        base_url = require_safe_http_url(
            runtime.get("endpoint_base_url"),
            acknowledge_insecure_non_loopback_http=(
                runtime.get("acknowledge_insecure_non_loopback_http") is True
            ),
        )
        models_url = base_url.rstrip("/") + "/v1/models"
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(models_url, headers=headers, method="GET")
        timeout = _positive_timeout(runtime.get("timeout_seconds", 10.0))
        deadline_ns, timeout_kind = _absolute_deadline(
            timeout, runtime.get("absolute_deadline_ns")
        )
        opener = _opener(models_url)
        transport_owner = getattr(opener, "_transport_owner", None)
        response, _ = _open_with_deadline(
            opener,
            request,
            deadline_ns,
            timeout_kind=timeout_kind,
        )
        with _closing_response(response):
            raw = _read_bounded(
                response,
                MAX_PROBE_BYTES,
                deadline_ns,
                timeout_kind=timeout_kind,
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StreamingError("endpoint identity response is malformed JSON") from exc
        if not isinstance(payload, dict):
            raise StreamingError("endpoint identity response must be an object")
        data = payload.get("data")
        if not isinstance(data, list):
            raise StreamingError("endpoint identity response has no model list")
        model_ids = [item.get("id") for item in data if isinstance(item, dict)]
        expected_model = runtime.get("model")
        if not isinstance(expected_model, str) or expected_model not in model_ids:
            raise StreamingError(f"endpoint does not serve expected model {expected_model!r}")
        runtime_version = payload.get("runtime_version")
        if runtime_version is not None and not isinstance(runtime_version, str):
            raise StreamingError("endpoint runtime_version must be a string or null")
        expected_version = runtime.get("expected_version")
        if expected_version is not None and runtime_version != expected_version:
            raise StreamingError(
                f"endpoint runtime version changed: expected {expected_version!r}, "
                f"observed {runtime_version!r}"
            )
        effective_settings = payload.get("effective_settings", {})
        if not isinstance(effective_settings, dict):
            raise StreamingError("endpoint effective_settings must be an object")
        try:
            return validate_endpoint_identity(
                {
                    "runtime_id": runtime.get("id"),
                    "model": expected_model,
                    "runtime_version": runtime_version,
                    "effective_settings": effective_settings,
                },
                expected_runtime_id=runtime.get("id"),
                expected_model=expected_model,
                expected_runtime_version=expected_version,
            )
        except ExperimentValidationError as exc:
            raise StreamingError(f"unsafe endpoint identity response: {exc}") from None
    except Exception as exc:
        abort_reason = transport_owner.aborted_reason if transport_owner is not None else None
        timed_out = isinstance(exc, TimeoutError) or abort_reason == "timeout"
        classified = isinstance(exc, StreamingError)
        raise StreamingError(
            (
                "absolute request deadline exceeded (timed out)"
                if timed_out
                else "request cancelled"
                if abort_reason == "cancelled"
                else _redacted_message(exc, api_key)
            ),
            deadline_exceeded=(
                (timed_out and timeout_kind == "run")
                or (classified and exc.deadline_exceeded)
            ),
            request_timed_out=(
                (timed_out and timeout_kind == "request")
                or (classified and exc.request_timed_out)
            ),
        ) from None


def read_bounded_url(
    url: object,
    *,
    timeout_seconds: object,
    max_response_bytes: int,
    acknowledge_insecure_non_loopback_http: bool = False,
    absolute_deadline_ns: int | None = None,
    cancel_event: Any = None,
) -> str:
    """Read one bounded, no-redirect HTTP(S) text resource."""

    safe_url = require_safe_http_url(
        url,
        acknowledge_insecure_non_loopback_http=acknowledge_insecure_non_loopback_http,
    )
    timeout = _positive_timeout(timeout_seconds)
    cap = _bounded_cap(max_response_bytes, MAX_PROBE_BYTES)
    deadline_ns, timeout_kind = _absolute_deadline(timeout, absolute_deadline_ns)
    request = urllib.request.Request(
        safe_url,
        headers={"Accept": "text/plain"},
        method="GET",
    )
    response, _ = _open_with_deadline(
        _opener(safe_url),
        request,
        deadline_ns,
        timeout_kind=timeout_kind,
        cancel_event=cancel_event,
    )
    with _closing_response(response):
        raw = _read_bounded(response, cap, deadline_ns, timeout_kind=timeout_kind)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise StreamingError("HTTP telemetry response is not valid UTF-8") from None


def _request_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    messages = request.get("messages")
    if not isinstance(messages, list) or not messages:
        raise StreamingError("messages must be a non-empty list")
    maximum_output_tokens = request.get("maximum_output_tokens")
    if (
        isinstance(maximum_output_tokens, bool)
        or not isinstance(maximum_output_tokens, int)
        or not 1 <= maximum_output_tokens <= 4096
    ):
        raise StreamingError("maximum_output_tokens must be between 1 and 4096")
    payload: dict[str, Any] = {
        "model": request.get("model"),
        "messages": messages,
        "max_tokens": maximum_output_tokens,
        "temperature": request.get("temperature", 0.0),
        "top_p": request.get("top_p", 1.0),
        "seed": request.get("seed"),
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if "thinking_enabled" in request:
        payload["chat_template_kwargs"] = {
            "enable_thinking": request.get("thinking_enabled") is True
        }
    try:
        json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise StreamingError(f"request payload must be JSON-safe: {exc}") from exc
    return payload


def _validate_runtime_capabilities(request: Mapping[str, Any]) -> None:
    unknown = set(request) - STREAM_REQUEST_FIELDS
    if unknown:
        raise StreamingError(
            f"unsupported optional request field: {sorted(unknown)[0]}"
        )
    runtime_id = request.get("runtime_id")
    if runtime_id not in SUPPORTED_RUNTIME_DIALECTS:
        raise StreamingError(f"unsupported runtime dialect {runtime_id!r}")
    capabilities = request.get("runtime_capabilities")
    if not isinstance(capabilities, Mapping):
        raise StreamingError("runtime capability contract is required")
    if any(capabilities.get(name) is not True for name in REQUIRED_STREAM_CAPABILITIES):
        raise StreamingError("runtime capability contract lacks exact streaming evidence")
    unknown_capabilities = set(capabilities) - REQUIRED_STREAM_CAPABILITIES - {
        "thinking_enabled"
    }
    if unknown_capabilities:
        raise StreamingError("runtime capability contract contains unknown fields")
    if "thinking_enabled" in request and capabilities.get("thinking_enabled") is not True:
        raise StreamingError("unsupported optional request field: thinking_enabled")


def stream_chat(
    request: Mapping[str, Any],
    clock: Callable[[], int] = time.monotonic_ns,
) -> dict[str, Any]:
    """Send one bounded streaming request and derive client-side timings."""

    api_key = request.get("api_key")
    actual_send_ns: int | None = None
    deadline_ns: int | None = None
    timeout_kind = "request"
    response_sockets: tuple[Any, Any] = (None, None)
    transport_owner: _TransportOwner | None = None
    try:
        _validate_runtime_capabilities(request)
        url = require_safe_http_url(
            request.get("url"),
            acknowledge_insecure_non_loopback_http=(
                request.get("acknowledge_insecure_non_loopback_http") is True
            ),
        )
        timeout = _positive_timeout(request.get("timeout_seconds", 120.0))
        cap = _bounded_cap(request.get("max_response_bytes"), MAX_RESPONSE_BYTES)
        payload = json.dumps(
            _request_payload(request),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        headers = {"Accept": "text/event-stream", "Content-Type": "application/json"}
        if isinstance(api_key, str) and api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        outbound = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        opener = _opener(url)
        transport_owner = getattr(opener, "_transport_owner", None)
        cancel_event = request.get("cancel_event")
        if cancel_event is not None and not callable(getattr(cancel_event, "is_set", None)):
            raise StreamingError("cancel_event must expose is_set()")

        text_parts: list[str] = []
        content_times: list[int] = []
        output_tokens: int | None = None
        stop_reason: str | None = None
        saw_done = False
        total_bytes = 0
        decoder = codecs.getincrementaldecoder("utf-8")()
        text_buffer = ""
        event_lines: list[str] = []

        def consume_event(lines: list[str]) -> None:
            nonlocal output_tokens, saw_done, stop_reason
            data_lines = [line[5:].lstrip(" ") for line in lines if line.startswith("data:")]
            if not data_lines:
                return
            data = "\n".join(data_lines)
            if data == "[DONE]":
                saw_done = True
                return
            try:
                event = json.loads(data)
            except json.JSONDecodeError as exc:
                raise StreamingError("malformed JSON in streaming event") from exc
            if not isinstance(event, dict):
                raise StreamingError("malformed streaming event: expected an object")
            if "error" in event:
                error = event.get("error")
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"]
                elif isinstance(error, str):
                    message = error
                else:
                    message = "endpoint returned an error envelope"
                raise StreamingError(f"stream error: {message}")
            usage = event.get("usage")
            has_completion_tokens = False
            if usage is not None:
                if not isinstance(usage, dict):
                    raise StreamingError("malformed streaming usage")
                completion_tokens = usage.get("completion_tokens")
                if completion_tokens is not None:
                    if (
                        isinstance(completion_tokens, bool)
                        or not isinstance(completion_tokens, int)
                        or completion_tokens < 0
                    ):
                        raise StreamingError("malformed completion token count")
                    output_tokens = completion_tokens
                    has_completion_tokens = True
            if "choices" not in event and not has_completion_tokens:
                raise StreamingError("malformed streaming event shape")
            choices = event.get("choices", [])
            if not isinstance(choices, list):
                raise StreamingError("malformed streaming choices")
            if not choices:
                if not has_completion_tokens:
                    raise StreamingError("malformed empty streaming choices")
                return
            first = choices[0]
            if not isinstance(first, dict):
                raise StreamingError("malformed streaming choice")
            if "delta" not in first:
                raise StreamingError("malformed streaming choice")
            delta = first["delta"]
            if not isinstance(delta, dict):
                raise StreamingError("malformed streaming delta")
            if not delta and first.get("finish_reason") is None:
                raise StreamingError("malformed empty streaming delta")
            finish_reason = first.get("finish_reason")
            if finish_reason is not None:
                if not isinstance(finish_reason, str) or not finish_reason:
                    raise StreamingError("malformed finish reason")
                if stop_reason is not None and stop_reason != finish_reason:
                    raise StreamingError("conflicting finish reasons")
                stop_reason = finish_reason
            if "content" not in delta:
                return
            content = delta.get("content")
            if content is None:
                return
            if not isinstance(content, str):
                raise StreamingError("malformed streaming content")
            received_ns = clock()
            if content:
                text_parts.append(content)
                content_times.append(received_ns)

        transport_start_ns = time.monotonic_ns()
        deadline_ns, timeout_kind = _absolute_deadline(
            timeout,
            request.get("absolute_deadline_ns"),
            started_ns=transport_start_ns,
        )
        if cancel_event is not None and cancel_event.is_set():
            raise StreamingError("request cancelled")
        response, actual_send_ns = _open_with_deadline(
            opener,
            outbound,
            deadline_ns,
            timeout_kind=timeout_kind,
            cancel_event=cancel_event,
            clock=clock,
        )
        if actual_send_ns is None:
            cleanup = getattr(response, "_benchmark_transport_cleanup", None)
            if callable(cleanup):
                cleanup()
            else:
                _close_response_transport(response)
            raise StreamingError("transport returned a response before sending the request")
        with _closing_response(response):
            response_sockets = _response_sockets(response)
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    if int(declared) > cap:
                        raise StreamingError(f"response byte cap exceeded ({cap})")
                except ValueError as exc:
                    raise StreamingError("invalid Content-Length response header") from exc
            read_available = getattr(response, "read1", response.read)
            while not saw_done:
                if cancel_event is not None and cancel_event.is_set():
                    raise StreamingError("request cancelled", actual_send_ns=actual_send_ns)
                remaining = _remaining_seconds(
                    deadline_ns,
                    actual_send_ns=actual_send_ns,
                    timeout_kind=timeout_kind,
                )
                _set_response_timeout(response, remaining)
                try:
                    block = read_available(4096)
                except TimeoutError:
                    raise StreamingError(
                        "absolute request deadline exceeded (timed out)",
                        actual_send_ns=actual_send_ns,
                        deadline_exceeded=timeout_kind == "run",
                        request_timed_out=timeout_kind == "request",
                    ) from None
                _remaining_seconds(
                    deadline_ns,
                    actual_send_ns=actual_send_ns,
                    timeout_kind=timeout_kind,
                )
                if not block:
                    break
                total_bytes += len(block)
                if total_bytes > cap:
                    raise StreamingError(f"response byte cap exceeded ({cap})")
                try:
                    text_buffer += decoder.decode(block)
                except UnicodeDecodeError as exc:
                    raise StreamingError("stream response is not valid UTF-8") from exc
                while "\n" in text_buffer and not saw_done:
                    line, text_buffer = text_buffer.split("\n", 1)
                    if line.endswith("\r"):
                        line = line[:-1]
                    if line == "":
                        consume_event(event_lines)
                        event_lines = []
                    elif not line.startswith(":"):
                        event_lines.append(line)
            if not saw_done:
                try:
                    text_buffer += decoder.decode(b"", final=True)
                except UnicodeDecodeError as exc:
                    raise StreamingError("stream response is not valid UTF-8") from exc
                raise StreamingError("stream terminated before [DONE]")
        _remaining_seconds(
            deadline_ns,
            actual_send_ns=actual_send_ns,
            timeout_kind=timeout_kind,
        )
        end_ns = clock()
        if not content_times:
            raise StreamingError(
                "exact streaming content evidence and TTFT are required",
                actual_send_ns=actual_send_ns,
            )
        if output_tokens is None:
            raise StreamingError(
                "exact streamed usage with completion tokens is required",
                actual_send_ns=actual_send_ns,
            )
        if stop_reason is None:
            raise StreamingError(
                "exact finish reason is required",
                actual_send_ns=actual_send_ns,
            )
        return {
            "success": True,
            "text": "".join(text_parts),
            "ttft_ms": (
                (content_times[0] - actual_send_ns) / 1_000_000 if content_times else None
            ),
            "content_span_ms": (content_times[-1] - content_times[0]) / 1_000_000,
            "inter_chunk_ms": [
                (later - earlier) / 1_000_000
                for earlier, later in zip(content_times, content_times[1:])
            ],
            "e2e_ms": (end_ns - actual_send_ns) / 1_000_000,
            "output_tokens": output_tokens,
            "stop_reason": stop_reason,
            "actual_send_ns": actual_send_ns,
            "error": None,
        }
    except Exception as exc:
        for candidate in response_sockets:
            close = getattr(candidate, "close", None)
            if callable(close):
                close()
        abort_reason = transport_owner.aborted_reason if transport_owner is not None else None
        deadline_exceeded = (
            (isinstance(exc, StreamingError) and exc.deadline_exceeded)
            or (abort_reason == "timeout" and timeout_kind == "run")
        )
        request_timed_out = (
            (isinstance(exc, StreamingError) and exc.request_timed_out)
            or (abort_reason == "timeout" and timeout_kind == "request")
        )
        raise StreamingError(
            (
                "absolute request deadline exceeded (timed out)"
                if abort_reason == "timeout"
                else "request cancelled"
                if abort_reason == "cancelled"
                else _redacted_message(exc, api_key)
            ),
            actual_send_ns=(
                exc.actual_send_ns
                if isinstance(exc, StreamingError) and exc.actual_send_ns is not None
                else actual_send_ns
            ),
            deadline_exceeded=deadline_exceeded,
            request_timed_out=request_timed_out,
        ) from None
