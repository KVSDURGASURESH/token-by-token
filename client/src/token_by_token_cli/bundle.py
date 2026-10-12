from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from collections.abc import Sequence
import zipfile

from .contracts import validate_document
from .errors import ClientError
from .model import SyntheticEvent


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def write_synthetic_bundle(events: Sequence[SyntheticEvent], output_path: Path) -> Path:
    output_path = Path(output_path)
    if not output_path.name.endswith(".tbt.zip"):
        raise ClientError("BUNDLE_PATH", "output must end in .tbt.zip")
    if output_path.exists() or output_path.is_symlink():
        raise ClientError("OUTPUT_EXISTS", f"refusing to overwrite {output_path}")
    if not output_path.parent.is_dir():
        raise ClientError("BUNDLE_PATH", "output parent directory does not exist")
    if not events or events[0].kind != "plan" or events[-1].kind not in {"run_completed", "run_interrupted"}:
        raise ClientError("INVALID_EVENTS", "synthetic events must include plan and terminal events")

    event_bytes = b"".join(canonical_json(event.to_json()) for event in events)
    plan = events[0].payload
    replay = {
        "schema_version": "run-replay.v1",
        "classification": "synthetic_mock",
        "episode": plan["episode"],
        "protocol": plan["protocol"],
        "status": "complete" if events[-1].kind == "run_completed" else "interrupted",
        "events_sha256": hashlib.sha256(event_bytes).hexdigest(),
        "summary": {
            "events": len(events),
            "requests": sum(event.kind == "request" for event in events),
            "users": plan["users"],
        },
    }
    validate_document("run-replay.v1", replay)
    replay_bytes = canonical_json(replay)
    entries = [
        {"path": "events.jsonl", "size": len(event_bytes), "media_type": "application/x-ndjson", "sha256": hashlib.sha256(event_bytes).hexdigest()},
        {"path": "replay.json", "size": len(replay_bytes), "media_type": "application/json", "sha256": hashlib.sha256(replay_bytes).hexdigest()},
    ]
    inventory = {"schema_version": "inventory.v1", "classification": "synthetic_mock", "entries": entries}
    validate_document("inventory.v1", inventory)
    inventory_bytes = canonical_json(inventory)

    owned_identity: tuple[int, int] | None = None
    try:
        with output_path.open("xb") as target:
            opened = os.fstat(target.fileno())
            owned_identity = (opened.st_dev, opened.st_ino)
            with zipfile.ZipFile(target, "w") as archive:
                for name, body in (("inventory.json", inventory_bytes), ("events.jsonl", event_bytes), ("replay.json", replay_bytes)):
                    archive.writestr(_zip_info(name), body)
    except FileExistsError as error:
        raise ClientError("OUTPUT_EXISTS", f"refusing to overwrite {output_path}") from error
    except Exception:
        if owned_identity is not None:
            try:
                current = output_path.lstat()
                if (current.st_dev, current.st_ino) == owned_identity:
                    output_path.unlink()
            except FileNotFoundError:
                pass
        raise
    return output_path
