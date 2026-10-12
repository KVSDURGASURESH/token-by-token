from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

from token_by_token_cli.errors import ClientError
from token_by_token_cli.verify import MAX_TOTAL, verify_bundle


CLIENT_SRC = Path(__file__).resolve().parents[1] / "src"


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


class HostileBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.outside = self.root.parent / "token-by-token-escape"
        self.outside.unlink(missing_ok=True)

    def tearDown(self) -> None:
        self.outside.unlink(missing_ok=True)
        self.temp.cleanup()

    def build(
        self,
        *,
        extra_name: str | None = None,
        duplicate: bool = False,
        symlink: bool = False,
        payload: bytes | None = None,
        replay_override: object | None = None,
        compression: int = zipfile.ZIP_DEFLATED,
    ) -> Path:
        path = self.root / "hostile.tbt.zip"
        if payload is None:
            payload = canonical(
                {
                    "kind": "plan",
                    "monotonic_ms": 0,
                    "payload": {
                        "classification": "synthetic_mock",
                        "episode": 2,
                        "protocol": "episode-02-public-v1",
                        "seed": 42,
                        "users": 2,
                    },
                    "sequence": 0,
                }
            ) + canonical(
                {
                    "kind": "run_completed",
                    "monotonic_ms": 10,
                    "payload": {"arms": 0, "classification": "synthetic_mock", "requests": 0},
                    "sequence": 1,
                }
            )
        replay_document = replay_override if replay_override is not None else {
            "schema_version": "run-replay.v1",
            "classification": "synthetic_mock",
            "episode": 2,
            "protocol": "episode-02-public-v1",
            "status": "complete",
            "events_sha256": hashlib.sha256(payload).hexdigest(),
            "summary": {"events": payload.count(b"\n"), "requests": 0, "users": 2},
        }
        replay = canonical(replay_document)
        entries = []
        for name, body, media in (("events.jsonl", payload, "application/x-ndjson"), ("replay.json", replay, "application/json")):
            entries.append({"path":name,"size":len(body),"media_type":media,"sha256":hashlib.sha256(body).hexdigest()})
        inventory = canonical({"schema_version":"inventory.v1","classification":"synthetic_mock","entries":entries})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with zipfile.ZipFile(path, "w", compression=compression) as archive:
                archive.writestr("inventory.json", inventory)
                archive.writestr("events.jsonl", payload)
                archive.writestr("replay.json", replay)
                if duplicate:
                    archive.writestr("events.jsonl", payload)
                if extra_name is not None:
                    archive.writestr(extra_name, b"escape")
                if symlink:
                    info = zipfile.ZipInfo("link")
                    info.create_system = 3
                    info.external_attr = 0o120777 << 16
                    archive.writestr(info, b"target")
        return path

    def test_traversal_absolute_duplicate_symlink_and_unlisted_fail_closed(self) -> None:
        cases = [
            ("traversal", {"extra_name": "../token-by-token-escape"}),
            ("absolute", {"extra_name": "/absolute"}),
            ("duplicate", {"duplicate": True}),
            ("symlink", {"symlink": True}),
            ("unlisted", {"extra_name": "extra.json"}),
        ]
        for name, kwargs in cases:
            with self.subTest(name=name):
                with self.assertRaises(ClientError):
                    verify_bundle(self.build(**kwargs))
                self.assertFalse(self.outside.exists())

    def test_oversized_entry_and_compression_bomb_fail(self) -> None:
        with self.assertRaisesRegex(ClientError, "(ENTRY_TOO_LARGE|COMPRESSION_RATIO)"):
            verify_bundle(self.build(payload=b"0" * (8 * 1024 * 1024 + 1)))
        with self.assertRaisesRegex(ClientError, "COMPRESSION_RATIO"):
            verify_bundle(self.build(payload=b"0" * (1024 * 1024)))

    def test_non_json_events_and_wrong_event_classification_fail_closed(self) -> None:
        with self.assertRaisesRegex(ClientError, "INVALID_EVENTS"):
            verify_bundle(self.build(payload=b"not-json\nnot-json\n"))
        recorded = canonical(
            {
                "kind": "plan",
                "monotonic_ms": 0,
                "payload": {
                    "classification": "recorded",
                    "episode": 2,
                    "protocol": "episode-02-public-v1",
                    "seed": 42,
                    "users": 2,
                },
                "sequence": 0,
            }
        ) + canonical(
            {
                "kind": "run_completed",
                "monotonic_ms": 10,
                "payload": {"arms": 0, "classification": "synthetic_mock", "requests": 0},
                "sequence": 1,
            }
        )
        with self.assertRaisesRegex(ClientError, "MIXED_CLASSIFICATION"):
            verify_bundle(self.build(payload=recorded))

    def test_middle_event_payloads_cannot_hide_classification_or_omit_fields(self) -> None:
        plan = canonical(
            {
                "kind": "plan",
                "monotonic_ms": 0,
                "payload": {
                    "classification": "synthetic_mock",
                    "episode": 2,
                    "protocol": "episode-02-public-v1",
                    "seed": 42,
                    "users": 2,
                },
                "sequence": 0,
            }
        )
        terminal = canonical(
            {
                "kind": "run_completed",
                "monotonic_ms": 20,
                "payload": {"arms": 0, "classification": "synthetic_mock", "requests": 1},
                "sequence": 2,
            }
        )
        request = {
            "kind": "request",
            "monotonic_ms": 10,
            "payload": {},
            "sequence": 1,
        }
        for payload in ({}, {"classification": "recorded"}):
            with self.subTest(payload=payload):
                request["payload"] = payload
                with self.assertRaisesRegex(ClientError, "INVALID_EVENTS"):
                    verify_bundle(self.build(payload=plan + canonical(request) + terminal))

    def test_unhashable_event_arm_fails_without_traceback(self) -> None:
        plan = canonical(
            {
                "kind": "plan",
                "monotonic_ms": 0,
                "payload": {
                    "classification": "synthetic_mock",
                    "episode": 2,
                    "protocol": "episode-02-public-v1",
                    "seed": 42,
                    "users": 2,
                },
                "sequence": 0,
            }
        )
        request = canonical(
            {
                "kind": "request",
                "monotonic_ms": 10,
                "payload": {
                    "arm": [],
                    "input_tokens": 128,
                    "output_tokens": 128,
                    "request_id": "mock-001",
                    "seed": 42,
                    "users": 2,
                },
                "sequence": 1,
            }
        )
        terminal = canonical(
            {
                "kind": "run_completed",
                "monotonic_ms": 20,
                "payload": {"arms": 0, "classification": "synthetic_mock", "requests": 1},
                "sequence": 2,
            }
        )
        archive = self.build(payload=plan + request + terminal)
        with self.assertRaisesRegex(ClientError, "INVALID_EVENTS"):
            verify_bundle(archive)
        result = subprocess.run(
            [sys.executable, "-m", "token_by_token_cli", "evidence", "verify", str(archive)],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
            check=False,
        )
        self.assertEqual(result.returncode, 3)
        self.assertNotIn("Traceback", result.stderr)

    def test_invalid_unicode_fails_without_traceback(self) -> None:
        surrogate_events = (
            b'{"kind":"plan","monotonic_ms":0,"payload":{"classification":"synthetic_mock",'
            b'"episode":2,"protocol":"\\ud800","seed":42,"users":2},"sequence":0}\n'
            b'{"kind":"run_interrupted","monotonic_ms":10,"payload":{"classification":"synthetic_mock",'
            b'"completed_events":1},"sequence":1}\n'
        )
        archives = [self.build(payload=surrogate_events), self.build()]
        raw = bytearray(archives[1].read_bytes())
        central = raw.find(b"PK\x01\x02")
        while central >= 0:
            name_length = struct.unpack_from("<H", raw, central + 28)[0]
            name_start = central + 46
            if bytes(raw[name_start : name_start + name_length]) == b"events.jsonl":
                flags = struct.unpack_from("<H", raw, central + 8)[0]
                struct.pack_into("<H", raw, central + 8, flags | 0x800)
                raw[name_start] = 0xFF
                break
            central = raw.find(b"PK\x01\x02", name_start + name_length)
        else:
            self.fail("events.jsonl central-directory record not found")
        archives[1].write_bytes(raw)

        for archive in archives:
            with self.subTest(archive=archive.name):
                with self.assertRaises(ClientError):
                    verify_bundle(archive)
                result = subprocess.run(
                    [sys.executable, "-m", "token_by_token_cli", "evidence", "verify", str(archive)],
                    capture_output=True,
                    text=True,
                    env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
                    check=False,
                )
                self.assertEqual(result.returncode, 3)
                self.assertNotIn("Traceback", result.stderr)

    def test_malformed_replay_and_corrupt_crc_fail_without_traceback(self) -> None:
        malformed = self.build(replay_override=[])
        with self.assertRaises(ClientError):
            verify_bundle(malformed)
        result = subprocess.run(
            [sys.executable, "-m", "token_by_token_cli", "evidence", "verify", str(malformed)],
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONPATH": str(CLIENT_SRC)},
            check=False,
        )
        self.assertEqual(result.returncode, 3)
        self.assertNotIn("Traceback", result.stderr)
        archive = self.build(compression=zipfile.ZIP_STORED)
        raw = bytearray(archive.read_bytes())
        index = raw.find(b'"kind":"plan"')
        self.assertNotEqual(index, -1)
        raw[index] ^= 1
        archive.write_bytes(raw)
        with self.assertRaises(ClientError):
            verify_bundle(archive)

    def test_corrupt_deflate_and_oversized_json_integer_fail_closed(self) -> None:
        archive = self.build()
        with zipfile.ZipFile(archive, "r") as reader:
            info = reader.getinfo("events.jsonl")
        raw = bytearray(archive.read_bytes())
        header = struct.unpack("<IHHHHHIIIHH", raw[info.header_offset : info.header_offset + 30])
        data_start = info.header_offset + 30 + header[-2] + header[-1]
        raw[data_start + max(info.compress_size // 2, 1)] ^= 1
        archive.write_bytes(raw)
        with self.assertRaises(ClientError):
            verify_bundle(archive)

        huge_integer = b"9" * 5_000
        malicious = (
            b'{"kind":"plan","monotonic_ms":0,"payload":{"classification":"synthetic_mock",'
            b'"episode":2,"protocol":"episode-02-public-v1","seed":42,"users":2},"sequence":0}\n'
            b'{"kind":"run_interrupted","monotonic_ms":10,"payload":{"classification":"synthetic_mock",'
            b'"completed_events":'
            + huge_integer
            + b'},"sequence":1}\n'
        )
        with self.assertRaisesRegex(ClientError, "INVALID_EVENTS"):
            verify_bundle(self.build(payload=malicious))

    def test_physical_archive_limit_precedes_zip_metadata_parsing(self) -> None:
        archive = self.root / "metadata-heavy.tbt.zip"
        with archive.open("wb") as output:
            output.write(b"PK")
            output.seek(MAX_TOTAL)
            output.write(b"\0")
        with mock.patch("token_by_token_cli.verify.zipfile.ZipFile") as parser:
            with self.assertRaisesRegex(ClientError, "BUNDLE_TOO_LARGE"):
                verify_bundle(archive)
        parser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
