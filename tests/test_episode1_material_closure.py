from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runpod_benchmark.episode1 import canonical_json
from runpod_benchmark.episode1_material_closure import (
    MaterialClosureError,
    MaterialClosureProfile,
    compile_material_closure,
    read_material_bytes,
    verify_exact_material_manifest,
)


class MaterialClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        files = {
            "scripts/execute.py": "from runpod_benchmark import app\n",
            "scripts/watchdog.py": "from runpod_benchmark.guard import Guard\n",
            "adapter/provider.py": "from runpod_benchmark import transport\n",
            "src/runpod_benchmark/__init__.py": "\n",
            "src/runpod_benchmark/app.py": "from . import capture\n",
            "src/runpod_benchmark/capture.py": "from .telemetry import sample\n",
            "src/runpod_benchmark/telemetry.py": "def sample(): return 1\n",
            "src/runpod_benchmark/guard.py": "class Guard: pass\n",
            "src/runpod_benchmark/transport.py": "VALUE = 1\n",
            "runtime/entrypoint.sh": "#!/bin/sh\n",
            "locks/client.lock": "client==1 --hash=sha256:00\n",
            "locks/vllm.lock": "vllm==1\n",
            "locks/sglang.lock": "sglang==1\n",
            "schemas/private.json": "{}\n",
            "prompt/evidence.json": "{}\n",
            "evidence/cpu-smoke.json": "{\"ok\":true}\n",
        }
        for relative, value in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)
        self.build = {
            "materials": [
                {"path": "runtime/entrypoint.sh", "sha256": hashlib.sha256(files["runtime/entrypoint.sh"].encode()).hexdigest()}
            ],
            "runtimes": [
                {"runtime": "vllm", "lock_path": "locks/vllm.lock"},
                {"runtime": "sglang", "lock_path": "locks/sglang.lock"},
            ],
        }
        (self.root / "build.json").write_text(canonical_json(self.build) + "\n")
        self.profile = MaterialClosureProfile(
            "episode1.material-closure-profile.v1",
            ("scripts/execute.py", "scripts/watchdog.py"),
            ("runtime/entrypoint.sh", "locks/client.lock", "schemas/private.json"),
            ("src/runpod_benchmark/capture.py",),
            "runtime/entrypoint.sh",
            "schemas/private.json",
        )
        self.inputs = {
            "build_manifest": "build.json",
            "prompt_evidence": "prompt/evidence.json",
            "provider_adapter": "adapter/provider.py",
            "build_attestation": "evidence/cpu-smoke.json",
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def compile(self):
        return compile_material_closure(
            self.root, self.profile, self.build, self.inputs,
            dockerfile_builder=lambda manifest, digest: (canonical_json(manifest) + digest).encode(),
        )

    def test_derives_exact_transitive_closure_and_plan_digests(self) -> None:
        result = self.compile()
        entries = result["material_manifest"]["files"]
        paths = [item["path"] for item in entries]
        self.assertEqual(paths, sorted(paths))
        for required in (
            "src/runpod_benchmark/__init__.py",
            "src/runpod_benchmark/app.py",
            "src/runpod_benchmark/capture.py",
            "src/runpod_benchmark/telemetry.py",
            "src/runpod_benchmark/guard.py",
            "src/runpod_benchmark/transport.py",
            "locks/vllm.lock",
            "locks/sglang.lock",
            "prompt/evidence.json",
            "evidence/cpu-smoke.json",
        ):
            self.assertIn(required, paths)
        derived = result["derived_plan_digests"]
        self.assertEqual(
            derived["dependency_lock_sha256"]["vllm"],
            hashlib.sha256((self.root / "locks/vllm.lock").read_bytes()).hexdigest(),
        )
        self.assertEqual(
            derived["private_schema_sha256"],
            hashlib.sha256((self.root / "schemas/private.json").read_bytes()).hexdigest(),
        )
        self.assertEqual(result["closure_receipt"]["material_sha256"], derived["material_sha256"])

    def test_rejects_caller_supplied_subset_or_extra_manifest(self) -> None:
        result = self.compile()
        supplied = json.loads(json.dumps(result["material_manifest"]))
        supplied["files"].pop()
        with self.assertRaisesRegex(MaterialClosureError, "exact closure"):
            verify_exact_material_manifest(result, supplied)
        supplied = json.loads(json.dumps(result["material_manifest"]))
        supplied["files"].append({"path": "other", "sha256": "0" * 64})
        with self.assertRaisesRegex(MaterialClosureError, "exact closure"):
            verify_exact_material_manifest(result, supplied)

    def test_rejects_open_roles_and_symlink_material(self) -> None:
        values = dict(self.inputs, opaque_digest="0" * 64)
        with self.assertRaisesRegex(MaterialClosureError, "roles"):
            compile_material_closure(
                self.root, self.profile, self.build, values,
                dockerfile_builder=lambda _manifest, _digest: b"Dockerfile",
            )
        target = self.root / "prompt/evidence.json"
        target.unlink()
        os.symlink(self.root / "schemas/private.json", target)
        with self.assertRaisesRegex(MaterialClosureError, "linked, or unsafe"):
            self.compile()

    def test_rejects_build_manifest_object_not_matching_selected_bytes(self) -> None:
        changed = json.loads(json.dumps(self.build))
        changed["runtimes"].reverse()
        with self.assertRaisesRegex(MaterialClosureError, "differs"):
            compile_material_closure(
                self.root, self.profile, changed, self.inputs,
                dockerfile_builder=lambda _manifest, _digest: b"Dockerfile",
            )

    def test_rejects_definite_unresolved_static_local_import(self) -> None:
        (self.root / "scripts/execute.py").write_text(
            "import runpod_benchmark.definitely_missing\n"
        )
        with self.assertRaisesRegex(
            MaterialClosureError,
            "required local import does not resolve: runpod_benchmark.definitely_missing",
        ):
            self.compile()

    def test_from_package_symbol_is_not_misclassified_as_missing_module(self) -> None:
        (self.root / "src/runpod_benchmark/app.py").write_text(
            "from runpod_benchmark.guard import Guard\nVALUE = Guard\n"
        )
        result = self.compile()
        paths = {entry["path"] for entry in result["material_manifest"]["files"]}
        self.assertIn("src/runpod_benchmark/guard.py", paths)
        self.assertNotIn("src/runpod_benchmark/guard/Guard.py", paths)

    def test_rooted_package_module_includes_ancestor_initializers(self) -> None:
        (self.root / "scripts/execute.py").write_text("VALUE = 1\n")
        (self.root / "scripts/watchdog.py").write_text("VALUE = 1\n")
        (self.root / "adapter/provider.py").write_text("VALUE = 1\n")
        result = self.compile()
        paths = {entry["path"] for entry in result["material_manifest"]["files"]}
        self.assertIn("src/runpod_benchmark/__init__.py", paths)

    def test_retains_first_validated_build_manifest_bytes(self) -> None:
        original_bytes = (self.root / "build.json").read_bytes()
        changed = json.loads(json.dumps(self.build))
        changed["runtimes"][0]["lock_path"] = "locks/unselected.lock"
        (self.root / "locks/unselected.lock").write_text("unselected==1\n")
        real_read = __import__(
            "runpod_benchmark.episode1_material_closure", fromlist=["_read"]
        )._read
        did_change = False

        def racing_read(root, relative, **kwargs):
            nonlocal did_change
            raw = real_read(root, relative, **kwargs)
            if relative == "build.json" and not did_change:
                did_change = True
                (self.root / "build.json").write_text(canonical_json(changed) + "\n")
            return raw

        with patch("runpod_benchmark.episode1_material_closure._read", side_effect=racing_read):
            result = self.compile()
        entries = {entry["path"]: entry["sha256"] for entry in result["material_manifest"]["files"]}
        self.assertEqual(entries["build.json"], hashlib.sha256(original_bytes).hexdigest())
        self.assertIn("locks/vllm.lock", entries)
        self.assertNotIn("locks/unselected.lock", entries)
        with self.assertRaisesRegex(MaterialClosureError, "differ from compiled digest"):
            read_material_bytes(self.root, result["material_manifest"])


if __name__ == "__main__":
    unittest.main()
