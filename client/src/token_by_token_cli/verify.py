from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import unicodedata
import zipfile

from .bundle import canonical_json
from .contracts import validate_document
from .errors import ClientError


MAX_TOTAL = 32 * 1024 * 1024
MAX_ENTRY = 8 * 1024 * 1024
MAX_ENTRIES = 64
MAX_RATIO = 100


@dataclass(frozen=True, slots=True)
class VerificationReport:
    classification: str
    files: tuple[str, ...]
    digest: str


def _safe_name(name: str) -> str:
    normalized = unicodedata.normalize("NFC", name)
    path = PurePosixPath(normalized)
    if normalized != name or "\\" in name or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ClientError("UNSAFE_PATH", "bundle contains a non-canonical path")
    return normalized


def verify_bundle(path: Path) -> VerificationReport:
    path = Path(path)
    if not path.name.endswith(".tbt.zip") or not path.is_file():
        raise ClientError("BUNDLE_PATH", "bundle must be an existing .tbt.zip file")
    try:
        with path.open("rb") as source:
            magic = source.read(2)
    except OSError as error:
        raise ClientError("BUNDLE_PATH", "bundle cannot be read") from error
    if magic != b"PK":
        raise ClientError("INVALID_ARCHIVE", "bundle does not have ZIP magic")
    try:
        archive = zipfile.ZipFile(path, "r")
    except (OSError, zipfile.BadZipFile) as error:
        raise ClientError("INVALID_ARCHIVE", "bundle is not a readable ZIP archive") from error
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRIES:
            raise ClientError("TOO_MANY_ENTRIES", "bundle contains too many entries")
        names: list[str] = []
        total = 0
        for info in infos:
            name = _safe_name(info.filename)
            if name in names:
                raise ClientError("DUPLICATE_ENTRY", "bundle contains duplicate paths")
            names.append(name)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ClientError("UNSAFE_LINK", "bundle links are forbidden")
            if info.file_size > MAX_ENTRY:
                raise ClientError("ENTRY_TOO_LARGE", "bundle entry exceeds 8 MiB")
            total += info.file_size
            if total > MAX_TOTAL:
                raise ClientError("BUNDLE_TOO_LARGE", "bundle exceeds 32 MiB")
            if info.file_size and info.file_size / max(info.compress_size, 1) > MAX_RATIO:
                raise ClientError("COMPRESSION_RATIO", "bundle entry exceeds 100:1 compression")
        if "inventory.json" not in names:
            raise ClientError("MISSING_INVENTORY", "bundle inventory is missing")
        try:
            inventory_bytes = archive.read("inventory.json")
            inventory = json.loads(inventory_bytes)
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ClientError("INVALID_INVENTORY", "bundle inventory is not valid JSON") from error
        validate_document("inventory.v1", inventory)
        entries = inventory["entries"]
        listed = [entry["path"] for entry in entries]
        expected = {"inventory.json", *listed}
        if set(names) != expected or len(names) != len(expected):
            raise ClientError("UNLISTED_ENTRY", "archive members do not match the inventory")
        bodies: dict[str, bytes] = {}
        for entry in entries:
            body = archive.read(entry["path"])
            bodies[entry["path"]] = body
            if len(body) != entry["size"] or hashlib.sha256(body).hexdigest() != entry["sha256"]:
                raise ClientError("DIGEST_MISMATCH", f"integrity check failed for {entry['path']}")
        try:
            replay = json.loads(bodies["replay.json"])
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ClientError("INVALID_REPLAY", "replay.json is invalid") from error
        if replay["classification"] != inventory["classification"]:
            raise ClientError("MIXED_CLASSIFICATION", "bundle classifications do not match")
        validate_document("run-replay.v1", replay)
        if replay["events_sha256"] != hashlib.sha256(bodies["events.jsonl"]).hexdigest():
            raise ClientError("DIGEST_MISMATCH", "events digest does not match replay")
        canonical_inventory = canonical_json(inventory)
        if inventory_bytes != canonical_inventory:
            raise ClientError("NON_CANONICAL_INVENTORY", "inventory JSON is not canonical")
        return VerificationReport(
            classification=inventory["classification"],
            files=tuple(sorted(listed)),
            digest=hashlib.sha256(inventory_bytes).hexdigest(),
        )
