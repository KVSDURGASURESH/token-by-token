"""Closed Episode 02 selections. A selection never authorizes resource creation."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid

from .contracts import validate_document
from .errors import ClientError
from .local_worker import _invoke


def capability_digest(capability: dict) -> str:
    try:
        raw = json.dumps(capability, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise ClientError("INVALID_CONTRACT", "invalid capability document") from error
    return hashlib.sha256(raw).hexdigest()


def validate_capability(capability: dict) -> None:
    validate_document("episode2-capabilities.v1", capability)
    status = capability["status"]
    combinations = capability["combinations"]
    if status == "unavailable":
        if combinations or capability["proof"] is not None or capability["expires_at"] is not None or capability["observed_at"] is not None:
            raise ClientError("INVALID_CONTRACT", "unavailable capability must have no proof or combinations")
        return
    if not combinations or capability["proof"] is None or capability["expires_at"] is None or capability["observed_at"] is None:
        raise ClientError("INVALID_CONTRACT", "verified capability requires bounded proof")
    try:
        expiry = datetime.fromisoformat(capability["expires_at"].replace("Z", "+00:00"))
        observed = datetime.fromisoformat(capability["observed_at"].replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        horizon = 900 if status == "provider_verified" else 86400
        if observed.tzinfo is None or expiry.tzinfo is None or not observed <= now < expiry or not 0 < (expiry-observed).total_seconds() <= horizon or (now-observed).total_seconds() > horizon:
            raise ValueError("expired")
    except (TypeError, ValueError) as error:
        raise ClientError("UNAVAILABLE_SELECTION", "capability is expired or has an invalid timestamp") from error
    identities = set()
    for c in combinations:
        if c["limits"]["max_turns_per_block"] != 12:
            raise ClientError("INVALID_CONTRACT", "public fixture capability requires twelve turns per block")
        triple = (c["mixture_id"], c["model_id"], c["gpu_id"])
        if triple in identities:
            raise ClientError("INVALID_CONTRACT", "duplicate capability combination")
        identities.add(triple)
        if c["mode"] == "synthetic_mock":
            if triple != ("public-fixture-v1", "loopback-model", "none"):
                raise ClientError("INVALID_CONTRACT", "synthetic capability uses unsupported aliases")
        elif status != "provider_verified" or triple != ("public-fixture-v1", "qwen2.5-32b-instruct", "h200-sxm"):
            raise ClientError("UNAVAILABLE_SELECTION", "recorded combination lacks provider verification")


def select_episode2(request: dict, capability: dict) -> dict:
    validate_document("episode2-selection.v1", request)
    validate_capability(capability)
    if capability["status"] == "unavailable":
        raise ClientError("UNAVAILABLE_SELECTION", "Episode 02 execution capability is unavailable")
    if request["capability_sha256"] != capability_digest(capability) or request["protocol_sha256"] != capability["protocol_sha256"]:
        raise ClientError("UNAVAILABLE_SELECTION", "selection identity does not match capability")
    triples = {(c["mixture_id"], c["model_id"], c["gpu_id"]) for c in capability["combinations"]}
    if (request["mixture_id"], request["model_id"], request["gpu_id"]) not in triples:
        raise ClientError("UNAVAILABLE_SELECTION", "selection has no approved capability")
    return dict(request)


def read_episode2_capability(worker: Path) -> dict:
    capability = _invoke(Path(worker).absolute(), ["capabilities", "--episode", "2", "--json"])
    validate_capability(capability)
    return capability


def write_selection(output: Path, request: dict, capability: dict) -> dict:
    selected = select_episode2(request, capability)
    output = Path(output).absolute()
    if output.suffix != ".json" or ".." in output.parts:
        raise ClientError("OUTPUT_PATH", "selection output must be a new JSON file")
    descriptor = None
    try:
        descriptor = os.open(output.anchor, os.O_RDONLY | os.O_DIRECTORY)
        for part in output.parent.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file_descriptor = os.open(output.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
        with os.fdopen(file_descriptor, "wb") as stream:
            stream.write(json.dumps(selected, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(descriptor)
    except OSError as error:
        raise ClientError("OUTPUT_PATH", "could not write exclusive selection output") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return selected


def create_selection(worker: Path, output: Path, *, mixture: str, model: str, gpu: str) -> dict:
    capability = read_episode2_capability(worker)
    request = {"schema_version": "episode2-selection.v1", "episode": 2,
               "protocol_sha256": capability["protocol_sha256"], "mixture_id": mixture,
               "model_id": model, "gpu_id": gpu, "request_id": uuid.uuid4().hex,
               "capability_sha256": capability_digest(capability)}
    return write_selection(output, request, capability)
