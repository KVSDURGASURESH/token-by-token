from __future__ import annotations

from copy import deepcopy
from importlib.resources import files
import json
from collections.abc import Mapping

from jsonschema import Draft202012Validator

from .errors import ClientError


RESOURCE_PACKAGE = "token_by_token_cli.resources"


def load_resource_json(relative_path: str) -> dict[str, object]:
    resource = files(RESOURCE_PACKAGE).joinpath(relative_path)
    try:
        value = json.loads(resource.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise ClientError("RESOURCE_ERROR", f"public resource is unavailable: {relative_path}") from error
    if not isinstance(value, dict):
        raise ClientError("RESOURCE_ERROR", f"public resource must be a JSON object: {relative_path}")
    return value


def validate_document(schema_name: str, document: Mapping[str, object]) -> None:
    schema = load_resource_json(f"schemas/{schema_name}.schema.json")
    errors = sorted(Draft202012Validator(schema).iter_errors(document), key=lambda item: list(item.absolute_path))
    if not errors:
        return
    first = errors[0]
    code = "UNKNOWN_PROPERTY" if first.validator == "additionalProperties" else "INVALID_CONTRACT"
    path = ".".join(str(part) for part in first.absolute_path) or "$"
    raise ClientError(code, f"{schema_name} at {path}: {first.message}")


def episode_manifest(episode: int, protocol: str | None = None) -> dict[str, object]:
    catalog = load_resource_json("episodes/catalog.v1.json")
    entry = next((item for item in catalog["episodes"] if item["episode"] == episode), None)
    if entry is None:
        raise ClientError("UNKNOWN_EPISODE", f"episode {episode} is not in the public catalog", 2)
    document = deepcopy(entry)
    expected_protocol = f"episode-{episode:02d}-public-v1"
    if protocol is not None and protocol != expected_protocol:
        raise ClientError("UNKNOWN_PROTOCOL", f"episode {episode:02d} supports {expected_protocol}", 2)
    document.update(
        {
            "schema_version": "episode-manifest.v1",
            "classification": "synthetic_mock",
            "protocol": expected_protocol,
            "protocol_status": "recorded_reference" if entry["status"] == "recorded" else "draft_unapproved",
            "allowed_parameters": {
                "protocol": {"type": "string", "const": expected_protocol},
                "users": {"type": "integer", "enum": entry["load_levels"]},
                "seed": {"type": "integer", "minimum": 0, "maximum": 2147483647},
                "output": {"type": "string", "suffix": ".tbt.zip"},
            },
            "selftest": {
                "classification": "synthetic_mock",
                "cost_usd": 0,
                "network": "forbidden",
                "meaning": "Validates the public client and bundle path only; it is not benchmark evidence.",
            },
        }
    )
    validate_document("episode-manifest.v1", document)
    return document


def public_capabilities(episode: int) -> dict[str, object]:
    """Return the deliberately closed public execution surface.

    Real model, GPU, and load aliases must eventually come from an authenticated,
    signed service manifest.  Until that service exists, an empty allowlist is safer
    than mirroring private harness configuration into the public client.
    """
    manifest = episode_manifest(episode)
    return {
        "schema_version": "public-capabilities.v1",
        "episode": episode,
        "episode_status": manifest["status"],
        "execution_status": "unavailable",
        "real_submission": False,
        "models": [],
        "gpus": [],
        "load_profiles": [],
        "offline_diagnostic": True,
        "reason": "The authenticated benchmark worker service is not implemented.",
    }
