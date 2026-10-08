from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import warnings
import zipfile

from token_by_token_cli.errors import ClientError
from token_by_token_cli.verify import verify_bundle


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

    def build(self, *, extra_name: str | None = None, duplicate: bool = False, symlink: bool = False, payload: bytes = b'{}\n') -> Path:
        path = self.root / "hostile.tbt.zip"
        replay = canonical({"schema_version":"run-replay.v1","classification":"synthetic_mock","episode":2,"protocol":"episode-02-public-v1","status":"complete","events_sha256":hashlib.sha256(payload).hexdigest(),"summary":{"requests":0}})
        entries = []
        for name, body, media in (("events.jsonl", payload, "application/x-ndjson"), ("replay.json", replay, "application/json")):
            entries.append({"path":name,"size":len(body),"media_type":media,"sha256":hashlib.sha256(body).hexdigest()})
        inventory = canonical({"schema_version":"inventory.v1","classification":"synthetic_mock","entries":entries})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
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


if __name__ == "__main__":
    unittest.main()
