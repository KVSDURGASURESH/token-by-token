"""Fail-closed Runpod REST v2 lifecycle logic with an injected transport.

This module intentionally contains no concrete HTTP client.  Transport and the
durable ownership journal are injected by the caller.
"""

from __future__ import annotations

import copy
import base64
import hashlib
import ipaddress
import math
import re
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import Any, Protocol

from .bounded_runpod_transport import TransportResponseError
from .episode1_orchestrator import CreateOutcomeUnknown, LifecycleError


@dataclass(frozen=True)
class Response:
    status: int
    body: Any
    raw_body: bytes | None = None
    completed_monotonic_ns: int | None = None


@dataclass(frozen=True)
class ProviderObservationBinding:
    """Immutable run and ownership binding supplied by the capture owner."""

    run_id: str
    attempt_id: str
    plan_sha256: str
    resource_identity_sha256: str
    ownership_identity_sha256: str
    private_id: str
    unique_name: str
    original_deadline_monotonic_ns: int


@dataclass(frozen=True)
class ProviderCleanupObservation:
    """One cleanup fact plus exact bytes accepted by capture v5."""

    value: bool
    capture_input: Mapping[str, Any]
    raw_bytes: bytes
    provider_artifact: Mapping[str, Any]


@dataclass(frozen=True)
class ProviderCleanupFailureObservation:
    """One closed, non-promotable cleanup failure evidence envelope."""

    evidence_bytes: bytes
    evidence_sha256: str


class Transport(Protocol):
    def request(
        self, method: str, path: str, *, query: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None, deadline_monotonic: float,
    ) -> Response: ...


class _ProviderPostRequestDeadline(TimeoutError):
    """A completed response rejected by the provider adapter's own clock."""

    validation_error = "late_response"

    def __init__(self, response: Response) -> None:
        super().__init__("provider operation deadline reached after response")
        self.response = response


@dataclass(frozen=True)
class OwnedResource:
    """Minimum durable deletion authority, emitted before readiness polling."""

    private_id: str
    unique_name: str
    ownership_token: str
    billing_started_monotonic: float | None


@dataclass(frozen=True)
class ProviderAllocation:
    """Facts the REST v2 pod readback can establish.

    A resolved image digest and offer/account public-IP support are deliberately
    absent.  Runtime attestation and operator evidence must supply those facts.
    """

    private_id: str
    unique_name: str
    ssh_host: str
    ssh_public_port: int
    container_ssh_port: int
    ownership_token: str
    gpu: str
    gpu_count: int
    data_center_id: str
    cloud_type: str
    container_disk_gb: int
    volume_gb: int
    volume_mount_path: str
    requested_image_reference: str
    provider_image_reference: str
    billing_started_monotonic: float | None


class RunpodV2Provider:
    OWNERSHIP_ENV = "EPISODE1_OWNERSHIP_SHA256"
    PLAN_ENV = "EPISODE1_PLAN_SHA256"
    AUTHORIZED_KEY_FINGERPRINT_ENV = "EPISODE1_AUTHORIZED_KEY_FINGERPRINT"
    COST_CATEGORIES = {
        "gpu", "container_storage", "volume_storage", "network_volume",
        "public_ip", "startup", "egress", "tax", "other",
    }
    DEFINITIVE_CREATE_REJECTIONS = {400, 401, 403, 404, 413, 422, 429}
    SAFE_POD_ID = re.compile(r"[A-Za-z0-9_-]+", re.ASCII)
    SAFE_EVIDENCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", re.ASCII)
    HEX64 = re.compile(r"[0-9a-f]{64}", re.ASCII)
    MAX_PROVIDER_ARTIFACT_BYTES = 16 * 1024 * 1024
    MAX_INVENTORY_PAGES = 4096

    def __init__(
        self,
        transport: Transport,
        *,
        approved_image_reference: str,
        approved_authorized_key_fingerprint: str,
        persist_owned: Callable[[OwnedResource], None],
        failure_observation_sink: Callable[[ProviderCleanupFailureObservation], None] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if "@sha256:" not in approved_image_reference:
            raise ValueError("approved image must be a digest-qualified reference")
        if not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", approved_authorized_key_fingerprint):
            raise ValueError("approved SSH key fingerprint must be a SHA256 fingerprint")
        if not callable(persist_owned):
            raise TypeError("persist_owned must be callable")
        if failure_observation_sink is not None and not callable(failure_observation_sink):
            raise TypeError("failure_observation_sink must be callable")
        self.transport = transport
        self.image_reference = approved_image_reference
        self.authorized_key_fingerprint = approved_authorized_key_fingerprint
        self.persist_owned = persist_owned
        self.failure_observation_sink = failure_observation_sink
        self.monotonic = monotonic
        self.sleep = sleep
        self._owned: dict[str, OwnedResource] = {}
        self._recovery: tuple[Mapping[str, Any], str, float | None] | None = None
        self._cleanup_owner: Callable[[OwnedResource], None] | None = None
        self._cleanup_observation_started = False

    def bind_failure_observation_sink(
        self, callback: Callable[[ProviderCleanupFailureObservation], None]
    ) -> None:
        """Bind durable failure capture before the first observed cleanup call."""
        if not callable(callback):
            raise TypeError("failure observation sink must be callable")
        if self.failure_observation_sink is not None:
            raise LifecycleError("failure observation sink is already bound")
        if self._cleanup_observation_started:
            raise LifecycleError("failure observation sink cannot be bound after cleanup starts")
        self.failure_observation_sink = callback

    def bind_cleanup_owner(self, callback: Callable[[OwnedResource], None]) -> None:
        """Bind the in-process finally owner before any create may be attempted."""
        if not callable(callback):
            raise TypeError("cleanup owner must be callable")
        if self._owned:
            raise LifecycleError("cleanup owner cannot be rebound after ownership exists")
        self._cleanup_owner = callback

    def make_cleanup_observation_binding(
        self, allocation: OwnedResource | ProviderAllocation, *, run_id: str,
        attempt_id: str, plan_sha256: str, resource_identity_sha256: str,
        original_deadline_monotonic_ns: int,
    ) -> ProviderObservationBinding:
        owned = self._require_owned(allocation)
        return ProviderObservationBinding(
            run_id=run_id, attempt_id=attempt_id, plan_sha256=plan_sha256,
            resource_identity_sha256=resource_identity_sha256,
            ownership_identity_sha256=self._ownership_identity(owned),
            private_id=owned.private_id, unique_name=owned.unique_name,
            original_deadline_monotonic_ns=original_deadline_monotonic_ns,
        )

    def _check_deadline(self, deadline: float) -> None:
        now = self.monotonic()
        if (
            isinstance(deadline, bool) or not isinstance(deadline, (int, float))
            or not math.isfinite(deadline)
            or isinstance(now, bool) or not isinstance(now, (int, float))
            or not math.isfinite(now)
        ):
            raise LifecycleError("provider deadline clock is invalid")
        if now >= deadline:
            raise TimeoutError("provider operation deadline reached")

    def _request(
        self, method: str, path: str, *, deadline: float,
        query: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> Response:
        self._check_deadline(deadline)
        response = self.transport.request(
            method, path, query=query, json_body=json_body, deadline_monotonic=deadline
        )
        try:
            self._check_deadline(deadline)
        except TimeoutError:
            if isinstance(response, Response):
                raise _ProviderPostRequestDeadline(response) from None
            raise
        if not isinstance(response, Response):
            raise LifecycleError("provider transport returned an invalid response")
        if isinstance(response.status, bool) or not isinstance(response.status, int):
            raise LifecycleError("provider response status is invalid")
        return response

    @staticmethod
    def _canonical(value: Any) -> bytes:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

    @staticmethod
    def _sha(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()

    @classmethod
    def _checked_binding(
        cls, binding: ProviderObservationBinding, owned: OwnedResource,
        deadline_monotonic: float,
    ) -> None:
        if not isinstance(binding, ProviderObservationBinding):
            raise LifecycleError("provider observation binding is invalid")
        if any(
            not isinstance(value, str) or cls.SAFE_EVIDENCE_ID.fullmatch(value) is None
            for value in (binding.run_id, binding.attempt_id)
        ):
            raise LifecycleError("provider observation identity is invalid")
        if (
            cls.HEX64.fullmatch(binding.plan_sha256) is None
            or cls.HEX64.fullmatch(binding.resource_identity_sha256) is None
            or cls.HEX64.fullmatch(binding.ownership_identity_sha256) is None
            or binding.ownership_identity_sha256 != cls._ownership_identity(owned)
            or binding.private_id != owned.private_id
            or binding.unique_name != owned.unique_name
            or isinstance(binding.original_deadline_monotonic_ns, bool)
            or not isinstance(binding.original_deadline_monotonic_ns, int)
            or binding.original_deadline_monotonic_ns < 1
        ):
            raise LifecycleError("provider observation ownership binding mismatch")
        try:
            deadline_value = Decimal(str(deadline_monotonic))
            if not deadline_value.is_finite() or deadline_value <= 0:
                raise InvalidOperation
            deadline_ns = int(
                (deadline_value * Decimal(1_000_000_000)).to_integral_value()
            )
        except (InvalidOperation, ValueError):
            raise LifecycleError("provider observation deadline is invalid") from None
        if deadline_ns > binding.original_deadline_monotonic_ns:
            raise LifecycleError("provider operation deadline exceeds the original deadline")

    @classmethod
    def _ownership_identity(cls, owned: OwnedResource) -> str:
        billing=owned.billing_started_monotonic
        if (isinstance(billing,bool) or not isinstance(billing,(int,float))
                or not math.isfinite(billing) or billing<0):
            raise LifecycleError("provider ownership billing identity is invalid")
        return cls._sha(cls._canonical({
            "provider": "runpod-rest-v2",
            "private_id": owned.private_id,
            "unique_name": owned.unique_name,
            "ownership_token_sha256": cls._token_hash(owned.ownership_token),
            "billing_started_monotonic_ns": int(billing * 1_000_000_000),
        }))

    def _call_artifact(
        self, *, role: str, method: str, path: str,
        query: Mapping[str, str] | None, response: Response,
        request_started_monotonic_ns: int, binding: ProviderObservationBinding,
        owned: OwnedResource, operation_deadline_monotonic: float,
        delete_attempt: int,
    ) -> dict[str, Any]:
        self._check_delete_attempt(delete_attempt)
        raw = response.raw_body
        completed = response.completed_monotonic_ns
        if (not isinstance(raw, bytes) or isinstance(response.status, bool)
                or not isinstance(response.status, int) or not 100 <= response.status <= 599):
            raise LifecycleError("provider response lacks exact typed bytes/status")
        try:
            operation_deadline_ns = int(
                (Decimal(str(operation_deadline_monotonic)) * Decimal(1_000_000_000)).to_integral_value()
            )
        except (InvalidOperation, ValueError, OverflowError):
            raise LifecycleError("provider operation deadline is invalid") from None
        if (
            isinstance(completed, bool) or not isinstance(completed, int)
            or completed < request_started_monotonic_ns
            or completed >= operation_deadline_ns
            or completed >= binding.original_deadline_monotonic_ns
        ):
            raise LifecycleError("provider response completion time is invalid")
        if not raw:
            if not ((method == "DELETE" and response.status == 204)
                    or (method == "GET" and response.status == 404)) or response.body is not None:
                raise LifecycleError("provider empty response is incoherent")
        else:
            def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
                result: dict[str, Any] = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError
                    result[key] = value
                return result
            try:
                parsed = json.loads(raw.decode("utf-8", errors="strict"),
                    parse_constant=lambda _v: (_ for _ in ()).throw(ValueError()),
                    object_pairs_hook=unique)
                if self._canonical(parsed) != self._canonical(response.body):
                    raise ValueError
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                raise LifecycleError("provider parsed response differs from exact bytes") from None
        body: dict[str, Any] = {
            "schema_version": "episode1.provider-call-evidence.v1",
            "role": role,
            "delete_attempt": delete_attempt,
            "run_id": binding.run_id,
            "attempt_id": binding.attempt_id,
            "plan_sha256": binding.plan_sha256,
            "resource_identity_sha256": binding.resource_identity_sha256,
            "ownership_identity_sha256": binding.ownership_identity_sha256,
            "http_method": method,
            "request_path": path,
            "request_query": dict(sorted((query or {}).items())),
            "http_status": response.status,
            "request_started_monotonic_ns": request_started_monotonic_ns,
            "body_complete_monotonic_ns": completed,
            "absolute_deadline_monotonic_ns": binding.original_deadline_monotonic_ns,
            "operation_deadline_monotonic_ns": operation_deadline_ns,
            "raw_body_sha256": self._sha(raw),
            "raw_body_base64": base64.b64encode(raw).decode("ascii"),
        }
        body["artifact_sha256"] = self._sha(self._canonical(body))
        return body

    def _capture_input(
        self, *, delete_attempt: int, kind: str, status: str,
        complete: bool | None, resource_absent: bool | None,
        raw_bytes: bytes, observed_monotonic_ns: int,
        binding: ProviderObservationBinding,
    ) -> dict[str, Any]:
        if isinstance(delete_attempt, bool) or not isinstance(delete_attempt, int) or delete_attempt < 1:
            raise LifecycleError("delete attempt is invalid")
        return {
            "schema_version": "episode1.provider-call-observation.v1",
            "delete_attempt": delete_attempt,
            "kind": kind,
            "run_id": binding.run_id,
            "attempt_id": binding.attempt_id,
            "plan_sha256": binding.plan_sha256,
            "resource_identity_sha256": binding.resource_identity_sha256,
            "observed_monotonic_ns": observed_monotonic_ns,
            "provider_response_sha256": self._sha(raw_bytes),
            "status": status,
            "complete": complete,
            "resource_absent": resource_absent,
        }

    def _failed_call_artifact(
        self, *, role: str, method: str, path: str,
        query: Mapping[str, str] | None, response: Response,
        request_started_monotonic_ns: int, binding: ProviderObservationBinding,
        operation_deadline_monotonic: float, delete_attempt: int,
        validation_error: str,
    ) -> dict[str, Any]:
        """Retain exact response bytes that cannot qualify as success evidence."""
        self._check_delete_attempt(delete_attempt)
        if validation_error not in {"invalid_body", "late_response", "http_status"}:
            raise LifecycleError("provider failure validation error is invalid")
        raw=response.raw_body; completed=response.completed_monotonic_ns
        if (not isinstance(raw,bytes) or len(raw)>2*1024*1024 or
                isinstance(response.status,bool) or not isinstance(response.status,int) or
                not 100<=response.status<=599 or isinstance(completed,bool) or
                not isinstance(completed,int) or completed<request_started_monotonic_ns):
            raise LifecycleError("failed provider response lacks bounded typed evidence")
        try:
            operation_deadline_ns=int((Decimal(str(operation_deadline_monotonic))*
                Decimal(1_000_000_000)).to_integral_value())
        except (InvalidOperation,ValueError,OverflowError):
            raise LifecycleError("provider operation deadline is invalid") from None
        if operation_deadline_ns>binding.original_deadline_monotonic_ns:
            raise LifecycleError("provider operation deadline exceeds original deadline")
        body={
            "schema_version":"episode1.provider-failed-http-call.v1",
            "role":role,"delete_attempt":delete_attempt,
            "run_id":binding.run_id,"attempt_id":binding.attempt_id,
            "plan_sha256":binding.plan_sha256,
            "resource_identity_sha256":binding.resource_identity_sha256,
            "ownership_identity_sha256":binding.ownership_identity_sha256,
            "http_method":method,"request_path":path,
            "request_query":dict(sorted((query or {}).items())),
            "http_status":response.status,
            "request_started_monotonic_ns":request_started_monotonic_ns,
            "body_complete_monotonic_ns":completed,
            "absolute_deadline_monotonic_ns":binding.original_deadline_monotonic_ns,
            "operation_deadline_monotonic_ns":operation_deadline_ns,
            "raw_body_sha256":self._sha(raw),
            "raw_body_base64":base64.b64encode(raw).decode("ascii"),
            "validation_error":validation_error,
        }
        body["artifact_sha256"]=self._sha(self._canonical(body))
        return body

    def _emit_failure_envelope(self, body: dict[str, Any]) -> None:
        if self.failure_observation_sink is None:
            return
        body["artifact_sha256"]=self._sha(self._canonical(body))
        encoded=self._canonical(body)
        if len(encoded)>self.MAX_PROVIDER_ARTIFACT_BYTES:
            raise LifecycleError("provider failure evidence exceeds retention bounds")
        observation=ProviderCleanupFailureObservation(encoded,self._sha(encoded))
        try:
            self.failure_observation_sink(observation)
        except Exception as exc:
            raise LifecycleError("provider failure observation persistence failed") from exc

    def _retain_cleanup_failure(
        self, *, binding: ProviderObservationBinding, delete_attempt: int,
        kind: str, failure_stage: str,
        call_artifacts: Sequence[Mapping[str, Any]],
        validated_inventory_pages: Sequence[Mapping[str, Any]]=(),
    ) -> None:
        """Synchronously persist each bounded call, then an incomplete terminal."""
        if self.failure_observation_sink is None or not call_artifacts:
            return
        if kind not in {"delete_ack","inventory_read","direct_read"}:
            raise LifecycleError("provider failure observation kind is invalid")
        if failure_stage not in {"call_artifact","http_status","schema","pagination",
                "retention","manifest","capture","deadline"}:
            raise LifecycleError("provider failure observation stage is invalid")
        self._check_delete_attempt(delete_attempt)
        digests=[]
        for index,item in enumerate(call_artifacts,1):
            call=copy.deepcopy(dict(item)); digests.append(call.get("artifact_sha256"))
            self._emit_failure_envelope({
                "schema_version":"episode1.provider-cleanup-failure-call.v1",
                "delete_attempt":delete_attempt,"kind":kind,"call_index":index,
                "run_id":binding.run_id,"attempt_id":binding.attempt_id,
                "plan_sha256":binding.plan_sha256,
                "resource_identity_sha256":binding.resource_identity_sha256,
                "ownership_identity_sha256":binding.ownership_identity_sha256,
                "absolute_deadline_monotonic_ns":binding.original_deadline_monotonic_ns,
                "failure_stage":failure_stage,"provider_call":call,
            })
        page_prefix=[{
            "sequence":item.get("sequence"),"request_cursor":item.get("request_cursor"),
            "has_next_page":item.get("has_next_page"),"next_cursor":item.get("next_cursor"),
            "page_artifact_sha256":item.get("artifact_sha256"),
        } for item in validated_inventory_pages]
        self._emit_failure_envelope({
            "schema_version":"episode1.provider-cleanup-failure-terminal.v1",
            "delete_attempt":delete_attempt,"kind":kind,
            "run_id":binding.run_id,"attempt_id":binding.attempt_id,
            "plan_sha256":binding.plan_sha256,
            "resource_identity_sha256":binding.resource_identity_sha256,
            "ownership_identity_sha256":binding.ownership_identity_sha256,
            "absolute_deadline_monotonic_ns":binding.original_deadline_monotonic_ns,
            "status":"failed","complete":False,"resource_absent":None,
            "failure_stage":failure_stage,
            "provider_call_artifact_sha256":digests,
            "validated_inventory_pages":page_prefix,
        })

    @staticmethod
    def _check_delete_attempt(delete_attempt: int) -> None:
        if isinstance(delete_attempt, bool) or not isinstance(delete_attempt, int) or delete_attempt < 1:
            raise LifecycleError("delete attempt is invalid")

    def _object(self, value: Any, label: str, deadline: float) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise LifecycleError(f"provider {label} is not an object")
        self._check_deadline(deadline)
        return value

    def _pages(self, *, deadline: float) -> list[Mapping[str, Any]]:
        cursor: str | None = None
        seen: set[str] = set()
        pods: list[Mapping[str, Any]] = []
        while True:
            query = {"includeClusterPods": "true", "limit": "1000"}
            if cursor is not None:
                query["cursor"] = cursor
            response = self._request("GET", "/pods", query=query, deadline=deadline)
            if response.status != 200:
                raise LifecycleError("provider inventory request failed")
            body = self._object(response.body, "inventory body", deadline)
            if set(body) != {"pods", "pagination"} or not isinstance(body["pods"], list):
                raise LifecycleError("provider inventory response is malformed")
            pagination = self._object(body["pagination"], "pagination", deadline)
            if set(pagination) != {"nextCursor", "hasNextPage"} or not isinstance(
                pagination["hasNextPage"], bool
            ):
                raise LifecycleError("provider pagination response is malformed")
            for pod in body["pods"]:
                pods.append(self._object(pod, "pod", deadline))
            self._check_deadline(deadline)
            if not pagination["hasNextPage"]:
                if pagination["nextCursor"] is not None:
                    raise LifecycleError("terminal provider page contains a cursor")
                return pods
            next_cursor = pagination["nextCursor"]
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen:
                raise LifecycleError("provider pagination cursor is missing or repeated")
            seen.add(next_cursor)
            cursor = next_cursor

    @staticmethod
    def _token_hash(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _exact_int(value: Any, expected: Any) -> bool:
        return (
            not isinstance(value, bool) and isinstance(value, int)
            and not isinstance(expected, bool) and isinstance(expected, int)
            and value == expected
        )

    @staticmethod
    def _mounts(plan: Mapping[str, Any]) -> Mapping[str, Any]:
        size = plan["allocation"]["volume_gb"]
        path = plan["allocation"]["volume_mount_path"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise LifecycleError("plan volume size is invalid")
        if not isinstance(path, str):
            raise LifecycleError("plan volume mount path is invalid")
        if size == 0:
            if path:
                raise LifecycleError("zero volume requires an empty mount path")
            return {}
        if size < 10 or not path.startswith("/"):
            raise LifecycleError("persistent volume requires at least 10 GB and an absolute path")
        return {"persistent": {"size": size, "path": path}}

    @classmethod
    def _safe_pod_id(cls, pod_id: Any) -> bool:
        return isinstance(pod_id, str) and cls.SAFE_POD_ID.fullmatch(pod_id) is not None

    @classmethod
    def _path_id(cls, pod_id: Any) -> str:
        if not cls._safe_pod_id(pod_id):
            raise LifecycleError("provider pod id is unsafe for a request path")
        return pod_id

    def _matches(
        self, pod: Mapping[str, Any], plan: Mapping[str, Any], name: str,
        token: str, *, expected_id: str | None = None,
    ) -> bool:
        gpu = pod.get("gpu")
        env = pod.get("env")
        return (
            (expected_id is None or pod.get("id") == expected_id)
            and pod.get("name") == name
            and isinstance(env, Mapping)
            and env.get(self.OWNERSHIP_ENV) == self._token_hash(token)
            and pod.get("image") == self.image_reference
            and isinstance(gpu, Mapping)
            and isinstance(gpu.get("id"), str)
            and gpu.get("id") == plan["allocation"]["gpu"]
            and self._exact_int(gpu.get("count"), plan["allocation"]["gpu_count"])
            and isinstance(pod.get("cloud"), str)
            and pod.get("cloud") == plan["allocation"]["cloud_type"]
            and self._exact_int(pod.get("disk"), plan["allocation"]["container_disk_gb"])
            and isinstance(pod.get("dataCenterId"), str)
            and pod.get("dataCenterId") == plan["allocation"]["data_center_id"]
            and pod.get("ports") == ["22/tcp"]
            and pod.get("mounts") == self._mounts(plan)
        )

    def _register_owned(
        self, pod_id: str, name: str, token: str, billing_started: float | None
    ) -> OwnedResource:
        if not isinstance(pod_id, str) or not pod_id:
            raise CreateOutcomeUnknown("provider create/recovery omitted a usable pod id")
        owned = OwnedResource(pod_id, name, token, billing_started)
        previous = self._owned.get(pod_id)
        if previous is not None:
            if previous != owned:
                raise LifecycleError("provider id is already bound to different ownership intent")
            return previous
        self._owned[pod_id] = owned
        if self._cleanup_owner is None:
            raise LifecycleError("cleanup owner was not bound before resource creation")
        # The finally owner is established before durable evidence is written.
        # Thus even a journal failure leaves this process able to delete.
        self._cleanup_owner(owned)
        self.persist_owned(owned)
        return owned

    def _allocation(
        self, pod: Mapping[str, Any], owned: OwnedResource, plan: Mapping[str, Any]
    ) -> ProviderAllocation:
        if pod.get("id") != owned.private_id:
            raise LifecycleError("provider readback id differs from the owned resource")
        runtime, ssh = pod.get("runtime"), pod.get("ssh")
        if pod.get("status") != "RUNNING" or not isinstance(runtime, Mapping) or not isinstance(ssh, Mapping):
            raise LifecycleError("provider pod is not ready")
        direct, ports = ssh.get("direct"), runtime.get("ports")
        if not isinstance(direct, Mapping) or not isinstance(ports, list):
            raise LifecycleError("direct SSH evidence is missing")
        candidates = [
            item for item in ports
            if isinstance(item, Mapping)
            and not isinstance(item.get("private"), bool)
            and isinstance(item.get("private"), int)
            and item.get("private") == 22
        ]
        if len(candidates) != 1:
            raise LifecycleError("runtime SSH port evidence is ambiguous")
        port = candidates[0]
        public, host = port.get("public"), port.get("ip")
        if (
            port.get("type") != "tcp"
            or isinstance(public, bool) or not isinstance(public, int) or not 1 <= public <= 65535
            or not isinstance(host, str) or not host
        ):
            raise LifecycleError("runtime SSH port is not a valid public TCP endpoint")
        try:
            ipaddress.ip_address(host)
        except ValueError as exc:
            raise LifecycleError("runtime SSH address is not an IP address") from exc
        if (
            not isinstance(direct.get("host"), str)
            or isinstance(direct.get("port"), bool)
            or not isinstance(direct.get("port"), int)
            or direct["host"] != host
            or direct["port"] != public
        ):
            raise LifecycleError("direct SSH fields disagree with runtime port evidence")
        return ProviderAllocation(
            owned.private_id, owned.unique_name, host, public, 22, owned.ownership_token,
            str(pod["gpu"]["id"]), int(pod["gpu"]["count"]), str(pod["dataCenterId"]),
            str(pod["cloud"]), int(pod["disk"]), int(plan["allocation"]["volume_gb"]),
            str(plan["allocation"]["volume_mount_path"]), self.image_reference,
            str(pod["image"]), owned.billing_started_monotonic,
        )

    def _wait_ready(
        self, owned: OwnedResource, token: str, plan: Mapping[str, Any], *, deadline: float
    ) -> ProviderAllocation:
        path_id = self._path_id(owned.private_id)
        while True:
            response = self._request("GET", f"/pods/{path_id}", deadline=deadline)
            if response.status != 200:
                raise LifecycleError("created provider pod could not be read")
            pod = self._object(response.body, "pod readback", deadline)
            if not self._matches(
                pod, plan, owned.unique_name, token, expected_id=owned.private_id
            ):
                raise LifecycleError("provider pod readback violates immutable ownership fields")
            if pod.get("status") == "RUNNING":
                allocation = self._allocation(pod, owned, plan)
                self._check_deadline(deadline)
                return allocation
            if pod.get("status") in {"EXITED", "TERMINATED", "ERROR"}:
                raise LifecycleError("provider pod entered a terminal state before readiness")
            self.sleep(min(.25, max(0.0, deadline - self.monotonic())))

    def bind_recovery(
        self, plan: Mapping[str, Any], ownership_token: str, *,
        billing_started_monotonic: float | None = None,
    ) -> None:
        self._recovery = (copy.deepcopy(plan), ownership_token, billing_started_monotonic)

    def create_allocation(
        self, *, unique_name: str, ownership_token: str, plan: Mapping[str, Any],
        deadline_monotonic: float,
    ) -> ProviderAllocation:
        self._validate_budget_before_create(plan)
        digest = plan["runtime_builds"][0]["derived_image_digest"]
        if not self.image_reference.endswith("@" + digest):
            raise LifecycleError("approved provider image reference is not bound to the plan digest")
        mounts = self._mounts(plan)
        body = {
            "name": unique_name, "image": self.image_reference,
            "cloud": plan["allocation"]["cloud_type"],
            "dataCenterIds": [plan["allocation"]["data_center_id"]],
            "gpu": {"id": plan["allocation"]["gpu"], "count": plan["allocation"]["gpu_count"]},
            "disk": plan["allocation"]["container_disk_gb"], "mounts": mounts,
            "ports": ["22/tcp"],
            "env": {
                self.OWNERSHIP_ENV: self._token_hash(ownership_token),
                self.PLAN_ENV: plan["plan_sha256"],
                self.AUTHORIZED_KEY_FINGERPRINT_ENV: self.authorized_key_fingerprint,
            },
            "startSsh": True,
        }
        billing_started = self.monotonic()
        self._check_deadline(deadline_monotonic)
        self.bind_recovery(
            plan, ownership_token, billing_started_monotonic=billing_started
        )
        try:
            response = self._request(
                "POST", "/pods", json_body=body, deadline=deadline_monotonic
            )
        except Exception as exc:
            raise CreateOutcomeUnknown("provider create outcome is unknown") from exc
        if response.status in self.DEFINITIVE_CREATE_REJECTIONS:
            raise LifecycleError("provider create request failed definitively")
        if response.status != 201:
            raise CreateOutcomeUnknown("provider create response is not a documented rejection")
        try:
            if not isinstance(response.body, Mapping):
                raise CreateOutcomeUnknown("successful create response is malformed")
            pod = response.body
            self._check_deadline(deadline_monotonic)
            pod_id = pod.get("id")
            if not isinstance(pod_id, str) or not pod_id:
                raise CreateOutcomeUnknown("successful create omitted a usable pod id")
            owned = self._register_owned(pod_id, unique_name, ownership_token, billing_started)
            if not self._safe_pod_id(pod_id):
                raise CreateOutcomeUnknown("provider returned an unsafe opaque pod id")
            if not self._matches(
                pod, plan, unique_name, ownership_token, expected_id=pod_id
            ):
                raise LifecycleError("provider create response violates immutable ownership fields")
            self._check_deadline(deadline_monotonic)
        except CreateOutcomeUnknown:
            raise
        except TimeoutError as exc:
            raise CreateOutcomeUnknown("provider create parsing exceeded its deadline") from exc
        return self._wait_ready(owned, ownership_token, plan, deadline=deadline_monotonic)

    def recover_exact_name(
        self, unique_name: str, *, deadline_monotonic: float
    ) -> Sequence[ProviderAllocation]:
        if self._recovery is None:
            raise LifecycleError("recovery intent is not bound")
        plan, token, billing_started = self._recovery
        exact_name = [pod for pod in self._pages(deadline=deadline_monotonic) if pod.get("name") == unique_name]
        if not exact_name:
            return []
        if len(exact_name) != 1:
            raise LifecycleError("multiple exact-name resources make create recovery ambiguous")
        pod = exact_name[0]
        if not self._matches(pod, plan, unique_name, token):
            raise LifecycleError("exact-name resource is not owned by this approved intent")
        pod_id = pod.get("id")
        if not isinstance(pod_id, str) or not pod_id:
            raise LifecycleError("owned exact-name resource has no usable id")
        owned = self._register_owned(pod_id, unique_name, token, billing_started)
        if not self._safe_pod_id(pod_id):
            raise CreateOutcomeUnknown("provider recovery returned an unsafe opaque pod id")
        self._check_deadline(deadline_monotonic)
        return [self._wait_ready(owned, token, plan, deadline=deadline_monotonic)]

    def read_allocation(
        self, allocation: ProviderAllocation, *, deadline_monotonic: float
    ) -> ProviderAllocation:
        owned = self._require_owned(allocation)
        if self._recovery is None:
            raise LifecycleError("allocation readback intent is not bound")
        plan, token, _ = self._recovery
        path_id = self._path_id(owned.private_id)
        response = self._request(
            "GET", f"/pods/{path_id}", deadline=deadline_monotonic
        )
        if response.status != 200:
            raise LifecycleError("provider allocation readback failed")
        pod = self._object(response.body, "allocation readback", deadline_monotonic)
        if not self._matches(
            pod, plan, allocation.unique_name, token, expected_id=allocation.private_id
        ):
            raise LifecycleError("allocation readback violates immutable fields")
        result = self._allocation(pod, owned, plan)
        self._check_deadline(deadline_monotonic)
        return result

    @staticmethod
    def _decimal(value: Any, label: str, *, positive: bool = False) -> Decimal:
        if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
            raise LifecycleError(f"{label} is invalid")
        try:
            result = Decimal(str(value))
        except InvalidOperation as exc:
            raise LifecycleError(f"{label} is invalid") from exc
        if not result.is_finite() or result < 0 or (positive and result <= 0):
            raise LifecycleError(f"{label} is invalid")
        return result

    def _conservative_charge(self, plan: Mapping[str, Any], elapsed: Decimal) -> Decimal:
        total = Decimal(0)
        categories: set[str] = set()
        included_edges: list[tuple[str, str]] = []
        for component in plan.get("cost_components", []):
            if not isinstance(component, Mapping):
                raise LifecycleError("cost component is malformed")
            category, status = component.get("category"), component.get("status")
            if not isinstance(category, str) or category in categories:
                raise LifecycleError("cost categories are duplicated or invalid")
            categories.add(category)
            if status == "included":
                amount = self._decimal(component.get("amount_usd"), "cost amount")
                target = component.get("included_in")
                if (
                    amount != 0 or component.get("billing_unit") != "included"
                    or not isinstance(target, str) or not target
                ):
                    raise LifecycleError("included cost component is invalid")
                included_edges.append((category, target))
                continue
            if status == "verified_not_applicable":
                amount = self._decimal(component.get("amount_usd"), "cost amount")
                if (
                    amount != 0
                    or component.get("billing_unit") != "not_applicable"
                    or component.get("included_in") is not None
                ):
                    raise LifecycleError("not-applicable cost component is invalid")
                continue
            if status != "priced":
                raise LifecycleError("cost envelope contains an unknown charge category")
            amount = self._decimal(component.get("amount_usd"), "cost amount")
            unit = component.get("billing_unit")
            if unit == "fixed":
                total += amount
            elif unit == "per_hour":
                rounding = component.get("rounding_seconds")
                if isinstance(rounding, bool) or not isinstance(rounding, int) or rounding <= 0:
                    raise LifecycleError("cost rounding interval is invalid")
                # An active allocation can incur its first billing quantum even
                # when two monotonic reads happen to be equal.
                units = max(
                    Decimal(1),
                    (elapsed / Decimal(rounding)).to_integral_value(rounding=ROUND_CEILING),
                )
                total += amount * units * Decimal(rounding) / Decimal(3600)
            else:
                raise LifecycleError("priced cost component has an invalid billing unit")
        if categories != self.COST_CATEGORIES:
            raise LifecycleError("cost envelope categories are incomplete")
        if any(target not in categories or target == source for source, target in included_edges):
            raise LifecycleError("included cost component target is invalid")
        return total

    def _validate_budget_before_create(self, plan: Mapping[str, Any]) -> None:
        budget = plan.get("budget")
        if not isinstance(budget, Mapping):
            raise LifecycleError("plan budget is malformed")
        maximum = self._decimal(
            budget.get("maximum_spend_usd"), "maximum spend", positive=True
        )
        lifetime = budget.get("maximum_lifetime_seconds")
        if isinstance(lifetime, bool) or not isinstance(lifetime, int) or lifetime <= 0:
            raise LifecycleError("maximum lifetime is invalid")
        projected = self._conservative_charge(plan, Decimal(lifetime))
        if projected > maximum:
            raise LifecycleError("approved cost envelope exceeds maximum spend")

    def current_exposure_fraction(
        self, allocation: ProviderAllocation, plan: Mapping[str, Any], *,
        deadline_monotonic: float,
    ) -> float:
        self._require_owned(allocation)
        if self._recovery is None or plan != self._recovery[0]:
            raise LifecycleError("cost check plan differs from the bound create intent")
        # Validate the entire approved envelope before performing even a
        # read-only provider call.  The result is recomputed after the read so
        # elapsed hourly rounding includes transport/body-decode time.
        self._conservative_charge(plan, Decimal(0))
        start = allocation.billing_started_monotonic
        if (
            isinstance(start, bool) or not isinstance(start, (int, float))
            or not math.isfinite(start)
        ):
            raise LifecycleError("billing start is unavailable after recovery")
        before_read = self.monotonic()
        if (
            isinstance(before_read, bool) or not isinstance(before_read, (int, float))
            or not math.isfinite(before_read)
        ):
            raise LifecycleError("billing clock is invalid")
        if before_read < start:
            raise LifecycleError("monotonic clock moved backwards")
        path_id = self._path_id(allocation.private_id)
        response = self._request(
            "GET", f"/pods/{path_id}", deadline=deadline_monotonic
        )
        if response.status != 200:
            raise LifecycleError("provider cost readback failed")
        pod = self._object(response.body, "cost readback", deadline_monotonic)
        live_rate = self._decimal(pod.get("cost"), "provider cost readback")
        now = self.monotonic()
        if (
            isinstance(now, bool) or not isinstance(now, (int, float))
            or not math.isfinite(now)
        ):
            raise LifecycleError("billing clock is invalid")
        if now < start:
            raise LifecycleError("monotonic clock moved backwards")
        elapsed = self._decimal(now - start, "billing elapsed seconds")
        maximum = self._decimal(plan["budget"]["maximum_spend_usd"], "maximum spend", positive=True)
        charge = self._conservative_charge(plan, elapsed)
        # A current provider pod rate above every quoted per-hour component is
        # quote drift.  Its allocation across categories is unknown, so fail.
        quoted_hourly = sum(
            (self._decimal(c["amount_usd"], "cost amount") for c in plan["cost_components"]
             if c.get("status") == "priced" and c.get("billing_unit") == "per_hour"),
            Decimal(0),
        )
        if live_rate > quoted_hourly:
            raise LifecycleError("provider current rate exceeds the approved hourly envelope")
        self._check_deadline(deadline_monotonic)
        return float(charge / maximum)

    @staticmethod
    def _id(resource: OwnedResource | ProviderAllocation) -> str:
        return resource.private_id

    def _require_owned(
        self, resource: OwnedResource | ProviderAllocation
    ) -> OwnedResource:
        pod_id = self._id(resource)
        owned = self._owned.get(pod_id)
        if owned is None:
            raise LifecycleError("resource lacks a bound ownership handle")
        if (
            resource.unique_name != owned.unique_name
            or not isinstance(resource.ownership_token, str)
            or resource.ownership_token != owned.ownership_token
            or resource.billing_started_monotonic != owned.billing_started_monotonic
        ):
            raise LifecycleError("resource disagrees with its bound ownership handle")
        return owned

    def delete_allocation(
        self, allocation: OwnedResource | ProviderAllocation, *, deadline_monotonic: float
    ) -> bool:
        pod_id = self._require_owned(allocation).private_id
        path_id = self._path_id(pod_id)
        response = self._request("DELETE", f"/pods/{path_id}", deadline=deadline_monotonic)
        if response.status == 204:
            return True
        if response.status == 404:
            return False
        raise LifecycleError("provider deletion was not accepted")

    def delete_allocation_observed(
        self, allocation: OwnedResource | ProviderAllocation, *,
        binding: ProviderObservationBinding, delete_attempt: int,
        deadline_monotonic: float,
    ) -> ProviderCleanupObservation:
        self._check_delete_attempt(delete_attempt)
        owned=self._require_owned(allocation)
        self._checked_binding(binding,owned,deadline_monotonic)
        self._cleanup_observation_started=True
        path=f"/pods/{self._path_id(owned.private_id)}"; started=time.monotonic_ns()
        try:
            response=self._request("DELETE",path,deadline=deadline_monotonic)
        except (TransportResponseError, _ProviderPostRequestDeadline) as exc:
            failed=self._failed_call_artifact(role="delete-response",method="DELETE",path=path,
                query=None,response=exc.response,request_started_monotonic_ns=started,binding=binding,
                operation_deadline_monotonic=deadline_monotonic,delete_attempt=delete_attempt,
                validation_error=exc.validation_error)
            self._retain_cleanup_failure(binding=binding,delete_attempt=delete_attempt,
                kind="delete_ack",failure_stage="call_artifact",call_artifacts=(failed,))
            raise
        try:
            artifact=self._call_artifact(role="delete-response",method="DELETE",path=path,
                query=None,response=response,request_started_monotonic_ns=started,
                binding=binding,owned=owned,operation_deadline_monotonic=deadline_monotonic,
                delete_attempt=delete_attempt)
        except Exception:
            error="late_response" if isinstance(response.completed_monotonic_ns,int) and not isinstance(response.completed_monotonic_ns,bool) and response.completed_monotonic_ns>=int(Decimal(str(deadline_monotonic))*Decimal(1_000_000_000)) else "invalid_body"
            failed=self._failed_call_artifact(role="delete-response",method="DELETE",path=path,
                query=None,response=response,request_started_monotonic_ns=started,binding=binding,
                operation_deadline_monotonic=deadline_monotonic,delete_attempt=delete_attempt,
                validation_error=error)
            self._retain_cleanup_failure(binding=binding,delete_attempt=delete_attempt,
                kind="delete_ack",failure_stage="call_artifact",call_artifacts=(failed,))
            raise
        try:
            if response.status==204: value,status=True,"acknowledged"
            elif response.status==404: value,status=False,"not_found"
            else: raise LifecycleError("provider deletion was not accepted")
            raw=response.raw_body; assert isinstance(raw,bytes)
            capture=self._capture_input(delete_attempt=delete_attempt,kind="delete_ack",status=status,
                complete=None,resource_absent=None,raw_bytes=raw,
                observed_monotonic_ns=artifact["body_complete_monotonic_ns"],binding=binding)
            self._check_deadline(deadline_monotonic)
            return ProviderCleanupObservation(value,capture,raw,artifact)
        except Exception:
            self._retain_cleanup_failure(binding=binding,delete_attempt=delete_attempt,
                kind="delete_ack",failure_stage="http_status",call_artifacts=(artifact,))
            raise

    def inventory_absent(
        self, allocation: OwnedResource | ProviderAllocation, *, deadline_monotonic: float
    ) -> bool:
        pod_id = self._require_owned(allocation).private_id
        result = all(pod.get("id") != pod_id for pod in self._pages(deadline=deadline_monotonic))
        self._check_deadline(deadline_monotonic)
        return result

    def inventory_absent_observed(
        self, allocation: OwnedResource | ProviderAllocation, *,
        binding: ProviderObservationBinding, delete_attempt: int,
        deadline_monotonic: float,
    ) -> ProviderCleanupObservation:
        self._check_delete_attempt(delete_attempt)
        owned=self._require_owned(allocation); self._checked_binding(binding,owned,deadline_monotonic)
        self._cleanup_observation_started=True
        cursor=None; seen=set(); pages=[]; calls=[]; retained=0; absent=True
        stage="call_artifact"
        try:
            while True:
                query={"includeClusterPods":"true","limit":"1000"}
                if cursor is not None: query["cursor"]=cursor
                started=time.monotonic_ns()
                try:
                    response=self._request("GET","/pods",query=query,deadline=deadline_monotonic)
                except (TransportResponseError, _ProviderPostRequestDeadline) as exc:
                    calls.append(self._failed_call_artifact(role="inventory-page",method="GET",path="/pods",
                        query=query,response=exc.response,request_started_monotonic_ns=started,binding=binding,
                        operation_deadline_monotonic=deadline_monotonic,delete_attempt=delete_attempt,
                        validation_error=exc.validation_error))
                    raise
                try:
                    artifact=self._call_artifact(role="inventory-page",method="GET",path="/pods",
                        query=query,response=response,request_started_monotonic_ns=started,
                        binding=binding,owned=owned,operation_deadline_monotonic=deadline_monotonic,
                        delete_attempt=delete_attempt)
                except Exception:
                    error="late_response" if isinstance(response.completed_monotonic_ns,int) and not isinstance(response.completed_monotonic_ns,bool) and response.completed_monotonic_ns>=int(Decimal(str(deadline_monotonic))*Decimal(1_000_000_000)) else "invalid_body"
                    artifact=self._failed_call_artifact(role="inventory-page",method="GET",path="/pods",
                        query=query,response=response,request_started_monotonic_ns=started,binding=binding,
                        operation_deadline_monotonic=deadline_monotonic,delete_attempt=delete_attempt,
                        validation_error=error)
                    calls.append(artifact)
                    raise
                calls.append(artifact); stage="http_status"
                if response.status!=200: raise LifecycleError("provider inventory request failed")
                stage="schema"; body=self._object(response.body,"inventory body",deadline_monotonic)
                if set(body)!={"pods","pagination"} or not isinstance(body["pods"],list):
                    raise LifecycleError("provider inventory response is malformed")
                pagination=self._object(body["pagination"],"pagination",deadline_monotonic)
                if set(pagination)!={"nextCursor","hasNextPage"} or not isinstance(pagination["hasNextPage"],bool):
                    raise LifecycleError("provider pagination response is malformed")
                for pod in body["pods"]:
                    checked=self._object(pod,"pod",deadline_monotonic); pod_id=checked.get("id")
                    if not self._safe_pod_id(pod_id): raise LifecycleError("provider inventory pod id is invalid")
                    if pod_id==owned.private_id: absent=False
                page=dict(artifact); page.update(sequence=len(pages)+1,request_cursor=cursor,
                    has_next_page=pagination["hasNextPage"],next_cursor=pagination["nextCursor"])
                bare=dict(page); bare.pop("artifact_sha256"); page["artifact_sha256"]=self._sha(self._canonical(bare))
                retained+=len(self._canonical(page)); stage="retention"
                if len(pages)+1>self.MAX_INVENTORY_PAGES or retained>self.MAX_PROVIDER_ARTIFACT_BYTES:
                    raise LifecycleError("provider inventory evidence exceeds retention bounds")
                stage="pagination"
                if not pagination["hasNextPage"]:
                    if pagination["nextCursor"] is not None: raise LifecycleError("terminal provider page contains a cursor")
                    pages.append(page)
                    self._check_deadline(deadline_monotonic)
                    break
                nxt=pagination["nextCursor"]
                if not isinstance(nxt,str) or not nxt or nxt in seen: raise LifecycleError("provider pagination cursor is missing or repeated")
                pages.append(page); self._check_deadline(deadline_monotonic)
                seen.add(nxt); cursor=nxt
            stage="manifest"
            manifest={"schema_version":"episode1.provider-inventory-evidence.v1",
                "role":"inventory-after-delete","delete_attempt":delete_attempt,
                "run_id":binding.run_id,"attempt_id":binding.attempt_id,"plan_sha256":binding.plan_sha256,
                "resource_identity_sha256":binding.resource_identity_sha256,
                "ownership_identity_sha256":self._ownership_identity(owned),
                "absolute_deadline_monotonic_ns":binding.original_deadline_monotonic_ns,
                "pages":pages,"terminal_page_sequence":len(pages),"terminal_next_cursor":None,
                "complete":True,"resource_absent":absent}
            manifest["artifact_sha256"]=self._sha(self._canonical(manifest)); raw=self._canonical(manifest)
            if len(raw)>self.MAX_PROVIDER_ARTIFACT_BYTES: raise LifecycleError("provider inventory evidence exceeds retention bounds")
            capture=self._capture_input(delete_attempt=delete_attempt,kind="inventory_read",status="complete",
                complete=True,resource_absent=absent,raw_bytes=raw,
                observed_monotonic_ns=pages[-1]["body_complete_monotonic_ns"],binding=binding)
            self._check_deadline(deadline_monotonic)
            return ProviderCleanupObservation(absent,capture,raw,manifest)
        except Exception:
            self._retain_cleanup_failure(binding=binding,delete_attempt=delete_attempt,
                kind="inventory_read",failure_stage=stage,call_artifacts=calls,
                validated_inventory_pages=pages)
            raise

    def direct_not_found(
        self, allocation: OwnedResource | ProviderAllocation, *, deadline_monotonic: float
    ) -> bool:
        pod_id = self._require_owned(allocation).private_id
        path_id = self._path_id(pod_id)
        response = self._request(
            "GET", f"/pods/{path_id}", deadline=deadline_monotonic
        )
        if response.status == 404:
            return True
        if response.status == 200:
            return False
        raise LifecycleError("provider direct deletion readback failed")

    def direct_not_found_observed(
        self, allocation: OwnedResource | ProviderAllocation, *,
        binding: ProviderObservationBinding, delete_attempt: int,
        deadline_monotonic: float,
    ) -> ProviderCleanupObservation:
        self._check_delete_attempt(delete_attempt)
        owned=self._require_owned(allocation); self._checked_binding(binding,owned,deadline_monotonic)
        self._cleanup_observation_started=True
        path=f"/pods/{self._path_id(owned.private_id)}"; started=time.monotonic_ns()
        try:
            response=self._request("GET",path,deadline=deadline_monotonic)
        except (TransportResponseError, _ProviderPostRequestDeadline) as exc:
            failed=self._failed_call_artifact(role="direct-after-delete",method="GET",path=path,
                query=None,response=exc.response,request_started_monotonic_ns=started,binding=binding,
                operation_deadline_monotonic=deadline_monotonic,delete_attempt=delete_attempt,
                validation_error=exc.validation_error)
            self._retain_cleanup_failure(binding=binding,delete_attempt=delete_attempt,
                kind="direct_read",failure_stage="call_artifact",call_artifacts=(failed,))
            raise
        try:
            artifact=self._call_artifact(role="direct-after-delete",method="GET",path=path,
                query=None,response=response,request_started_monotonic_ns=started,
                binding=binding,owned=owned,operation_deadline_monotonic=deadline_monotonic,
                delete_attempt=delete_attempt)
        except Exception:
            error="late_response" if isinstance(response.completed_monotonic_ns,int) and not isinstance(response.completed_monotonic_ns,bool) and response.completed_monotonic_ns>=int(Decimal(str(deadline_monotonic))*Decimal(1_000_000_000)) else "invalid_body"
            failed=self._failed_call_artifact(role="direct-after-delete",method="GET",path=path,
                query=None,response=response,request_started_monotonic_ns=started,binding=binding,
                operation_deadline_monotonic=deadline_monotonic,delete_attempt=delete_attempt,
                validation_error=error)
            self._retain_cleanup_failure(binding=binding,delete_attempt=delete_attempt,
                kind="direct_read",failure_stage="call_artifact",call_artifacts=(failed,))
            raise
        try:
            if response.status==404: value,status=True,"not_found"
            elif response.status==200: value,status=False,"found"
            else: raise LifecycleError("provider direct deletion readback failed")
            raw=response.raw_body; assert isinstance(raw,bytes)
            capture=self._capture_input(delete_attempt=delete_attempt,kind="direct_read",status=status,
                complete=None,resource_absent=None,raw_bytes=raw,
                observed_monotonic_ns=artifact["body_complete_monotonic_ns"],binding=binding)
            self._check_deadline(deadline_monotonic)
            return ProviderCleanupObservation(value,capture,raw,artifact)
        except Exception:
            self._retain_cleanup_failure(binding=binding,delete_attempt=delete_attempt,
                kind="direct_read",failure_stage="http_status",call_artifacts=(artifact,))
            raise
