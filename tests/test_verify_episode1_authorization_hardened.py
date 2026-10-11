from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from runpod_benchmark.episode1 import canonical_json
from runpod_benchmark.episode1_authorization import verify_authorization_receipt
from runpod_benchmark.episode1_execution import (
    compile_execution_candidate, spend_approval_phrase, watchdog_risk_phrase,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_episode1_authorization.py"
SPEC = importlib.util.spec_from_file_location("isolated_authorization_verifier", SCRIPT)
verifier = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(verifier)
CANDIDATE = Path(importlib.util.find_spec("runpod_benchmark").submodule_search_locations[0]).parents[1]
FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "authorization_cli_execution_fixtures", CANDIDATE / "tests" / "test_episode1_execution.py"
)
fixtures = importlib.util.module_from_spec(FIXTURE_SPEC)
assert FIXTURE_SPEC.loader is not None
FIXTURE_SPEC.loader.exec_module(fixtures)


class HardenedAuthorizationVerifierTests(unittest.TestCase):
    def _repository(self, parent: Path, name: str, payload: bytes) -> tuple[Path, str]:
        repository = parent / name
        repository.mkdir()
        subprocess.run(["/usr/bin/git", "-C", str(repository), "init", "-q"], check=True)
        subprocess.run(["/usr/bin/git", "-C", str(repository), "config", "user.name", "fixture"], check=True)
        subprocess.run(["/usr/bin/git", "-C", str(repository), "config", "user.email", "fixture@example.invalid"], check=True)
        (repository / "payload.bin").write_bytes(payload)
        subprocess.run(["/usr/bin/git", "-C", str(repository), "add", "payload.bin"], check=True)
        subprocess.run(["/usr/bin/git", "-C", str(repository), "commit", "-qm", "fixture"], check=True)
        head = subprocess.run(
            ["/usr/bin/git", "-C", str(repository), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        return repository, head

    def test_git_head_ignores_ambient_git_environment(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            parent = Path(temporary)
            target, target_head = self._repository(parent, "target", b"target")
            foreign, foreign_head = self._repository(parent, "foreign", b"foreign")
            self.assertNotEqual(target_head, foreign_head)
            poisoned = {
                "GIT_DIR": str(foreign / ".git"),
                "GIT_WORK_TREE": str(foreign),
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "core.worktree",
                "GIT_CONFIG_VALUE_0": str(foreign),
            }
            with patch.dict(os.environ, poisoned):
                self.assertEqual(verifier._observed_head(target), target_head)
            target_link = parent / "target-link"
            target_link.symlink_to(target, target_is_directory=True)
            with self.assertRaises(OSError):
                verifier._observed_head(target_link)

    def test_regular_reader_rejects_symlink_fifo_and_oversize(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            root = Path(temporary)
            regular = root / "regular.json"
            regular.write_bytes(b"{}")
            self.assertEqual(verifier._read_regular(regular, limit=2), b"{}")
            link = root / "link.json"
            link.symlink_to(regular)
            with self.assertRaises(OSError):
                verifier._read_regular(link, limit=10)
            fifo = root / "fifo"
            os.mkfifo(fifo)
            with self.assertRaises(ValueError):
                verifier._read_regular(fifo, limit=10)
            oversized = root / "oversized"
            with oversized.open("wb") as stream:
                stream.truncate(verifier.MAX_DOCUMENT_BYTES + 1)
            with self.assertRaises(ValueError):
                verifier._read_regular(oversized, limit=verifier.MAX_DOCUMENT_BYTES)

    def test_material_paths_are_canonical_unique_bounded_and_nofollow(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            root = Path(temporary)
            (root / "safe").mkdir()
            (root / "safe" / "one.bin").write_bytes(b"one")
            manifest = {"files": [{"path": "safe/one.bin"}]}
            self.assertEqual(verifier._material_files(root, manifest), {"safe/one.bin": b"one"})
            with self.assertRaisesRegex(ValueError, "duplicate"):
                verifier._material_files(root, {"files": manifest["files"] * 2})
            for path in ("../one.bin", "safe/./one.bin", "safe\\one.bin", "/safe/one.bin"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    verifier._material_files(root, {"files": [{"path": path}]})
            (root / "linked.bin").symlink_to(root / "safe" / "one.bin")
            with self.assertRaises(OSError):
                verifier._material_files(root, {"files": [{"path": "linked.bin"}]})
            (root / "linked-directory").symlink_to(root / "safe", target_is_directory=True)
            with self.assertRaises(OSError):
                verifier._material_files(root, {"files": [{"path": "linked-directory/one.bin"}]})
            (root / "large.bin").write_bytes(b"")
            with (root / "large.bin").open("r+b") as stream:
                stream.truncate(verifier.MAX_MATERIAL_FILE_BYTES + 1)
            with self.assertRaises(ValueError):
                verifier._material_files(root, {"files": [{"path": "large.bin"}]})
            (root / "two.bin").write_bytes(b"22")
            with patch.object(verifier, "MAX_MATERIAL_TOTAL_BYTES", 3), \
                    patch.object(verifier, "MAX_MATERIAL_FILE_BYTES", 3):
                with self.assertRaises(ValueError):
                    verifier._material_files(root, {"files": [
                        {"path": "safe/one.bin"}, {"path": "two.bin"},
                    ]})

    def test_json_rejects_duplicate_keys_and_nonfinite_numbers(self):
        for raw in (b'{"a":1,"a":2}', b'{"value":NaN}', b'{"value":Infinity}',
                    b'{"value":1e999}', b'{"value":-1e999}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                verifier._strict_json(raw, "fixture")

    def test_successful_cli_uses_actual_git_head_and_preserves_output(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            root = Path(temporary)
            repository, head = self._repository(root, "repository", b"bound material")
            material_bytes = b"bound material"
            files = [{"path": "payload.bin", "sha256": hashlib.sha256(material_bytes).hexdigest()}]
            aggregate = hashlib.sha256(canonical_json(files).encode()).hexdigest()
            manifest_bytes = (canonical_json({
                "aggregate_sha256": aggregate,
                "classification": "execution_material_hashes",
                "files": files,
            }) + "\n").encode()
            inputs = fixtures.inputs()
            inputs["source_commit"] = head
            inputs["material_sha256"] = aggregate
            plan = compile_execution_candidate(fixtures.protocol(), inputs)
            plan_bytes = (canonical_json(plan) + "\n").encode()
            approved_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(
                timespec="seconds"
            ).replace("+00:00", "Z")
            source_bytes = (canonical_json({
                "schema_version": "episode1.owner-approval-record.v1",
                "source_channel": "codex_user_message",
                "plan_sha256": plan["plan_sha256"],
                "approved_at": approved_at,
                "spend_approval": spend_approval_phrase(plan),
                "watchdog_risk_approval": watchdog_risk_phrase(plan),
            }) + "\n").encode()
            receipt = {
                "schema_version": "episode1.authorization-receipt.v1",
                "plan_sha256": plan["plan_sha256"],
                "plan_file_sha256": hashlib.sha256(plan_bytes).hexdigest(),
                "material_file_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "material_sha256": aggregate,
                "source_commit": head,
                "approved_at": approved_at,
                "source_kind": "retained_owner_record",
                "source_reference_sha256": hashlib.sha256(source_bytes).hexdigest(),
                "spend_approval": spend_approval_phrase(plan),
                "watchdog_risk_approval": watchdog_risk_phrase(plan),
            }
            paths = {
                "plan": plan_bytes,
                "material": manifest_bytes,
                "receipt": (canonical_json(receipt) + "\n").encode(),
                "source": source_bytes,
            }
            for name, value in paths.items():
                (root / f"{name}.json").write_bytes(value)
            before = subprocess.run(
                ["/usr/bin/git", "-C", str(repository), "status", "--porcelain"],
                check=True, capture_output=True,
            ).stdout
            completed = subprocess.run([
                sys.executable, str(SCRIPT),
                "--plan", str(root / "plan.json"),
                "--material", str(root / "material.json"),
                "--receipt", str(root / "receipt.json"),
                "--authorization-source", str(root / "source.json"),
                "--repository-root", str(repository),
            ], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(CANDIDATE / "src"),
                     "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1"}, timeout=5)
            self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
            output = json.loads(completed.stdout)
            self.assertEqual(set(output), {"authorization_receipt_sha256"})
            self.assertRegex(output["authorization_receipt_sha256"], r"^[0-9a-f]{64}$")
            expected = verify_authorization_receipt(
                plan, receipt, plan_file_bytes=plan_bytes,
                material_file_bytes=manifest_bytes,
                material_files={"payload.bin": material_bytes},
                observed_source_commit=head, source_record_bytes=source_bytes,
                verification_time=datetime.now(timezone.utc),
            )
            self.assertEqual(output["authorization_receipt_sha256"], expected)
            after = subprocess.run(
                ["/usr/bin/git", "-C", str(repository), "status", "--porcelain"],
                check=True, capture_output=True,
            ).stdout
            self.assertEqual(after, before)

    def test_help_has_no_filesystem_side_effect(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            root = Path(temporary)
            before = list(root.iterdir())
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--help"], cwd=root,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(CANDIDATE / "src"),
                     "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1"},
                timeout=5,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
            self.assertIn(b"--authorization-source", completed.stdout)
            self.assertEqual(list(root.iterdir()), before)


if __name__ == "__main__":
    unittest.main()
