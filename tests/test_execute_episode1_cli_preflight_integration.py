from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


BUNDLE = Path(__file__).resolve().parent
FROZEN = BUNDLE.parent
sys.path[:0] = [str(FROZEN / "scripts"), str(FROZEN / "src"), str(FROZEN / "tests")]

import episode1_build as build
import execute_episode1 as cli
from runpod_benchmark.episode1 import canonical_json
from runpod_benchmark.episode1_authorization import _strict_json
from runpod_benchmark.episode1_execution import (
    compile_execution_candidate,
    spend_approval_phrase,
    watchdog_risk_phrase,
)
from runpod_benchmark.episode1_material_closure import PRODUCTION_PROFILE, compile_material_closure
from test_episode1_build import fixture as build_fixture
from test_episode1_execution import inputs as execution_inputs
from test_episode1_execution import protocol


def canonical_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write(root: Path, relative: str, raw: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["/usr/bin/git", "-C", str(root), *args], check=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull},
        timeout=15,
    )
    return completed.stdout.decode("ascii", errors="strict").strip()


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Fixture:
    def __init__(self, parent: Path) -> None:
        self.root = parent / "repository"
        self.root.mkdir(mode=0o700)
        self.manifest = build_fixture(self.root)
        shutil.rmtree(self.root / ".git")
        for name in ("scripts", "src", "runtime", "schemas", "fixtures"):
            shutil.copytree(FROZEN / name, self.root / name, dirs_exist_ok=True)
        for name in ("pyproject.toml", "uv.lock"):
            shutil.copy2(FROZEN / name, self.root / name)

        # This exact fixed-path adapter is material, but preflight must parse it
        # only as source. Executing it creates a marker and then raises.
        self.marker = parent / "adapter-imported"
        adapter = (
            "from pathlib import Path\n"
            f"Path({str(self.marker)!r}).write_text('imported')\n"
            "raise RuntimeError('fixture adapter must never execute during preflight')\n"
        ).encode()
        write(self.root, cli.PROVIDER_ADAPTER, adapter)

        git(self.root, "init", "-q")
        git(self.root, "-c", "user.name=Episode1 Fixture", "-c", "user.email=fixture@example.invalid",
            "add", "scripts", "src", "runtime", "schemas", "fixtures", "pyproject.toml", "uv.lock")
        git(self.root, "-c", "user.name=Episode1 Fixture", "-c", "user.email=fixture@example.invalid",
            "commit", "-q", "-m", "synthetic preflight fixture")
        self.head = git(self.root, "rev-parse", "HEAD")

        self.manifest["source_commit"] = self.head
        self.manifest["tooling"] = {
            "build_tool_sha256": build.hashfile(Path(build.__file__)),
            "cpu_smoke_sha256": build.hashfile(Path(build.__file__).with_name("episode1_cpu_smoke.py")),
        }
        approved_materials: list[dict[str, str]] = []
        candidates = sorted((self.root / "src/runpod_benchmark").glob("*.py"))
        candidates += sorted((self.root / "schemas").glob("episode1-*.json"))
        candidates += sorted(
            item for item in (self.root / "runtime/episode1").rglob("*")
            if item.is_file() and item.suffix in {".json", ".sh"}
        )
        for path in candidates:
            relative = path.relative_to(self.root).as_posix()
            approved_materials.append({"path": relative, "sha256": sha(path.read_bytes())})
        self.manifest["materials"] = approved_materials
        self.policy = {
            item["runtime"]: {
                "lock_sha256": item["lock_sha256"],
                "package_count": 1,
                "required": {item["runtime"]: "1.0"},
            }
            for item in self.manifest["runtimes"]
        }

        self.paths = {
            "build_manifest": "private/build-manifest.json",
            "prompt_evidence": "private/prompt-evidence.json",
            "provider_adapter": cli.PROVIDER_ADAPTER,
            "build_attestation": "private/build-attestation.json",
            "material": "private/material.json",
            "plan": "private/plan.json",
            "authorization_receipt": "private/authorization-receipt.json",
            "authorization_source": "private/authorization-source.json",
        }
        write(self.root, self.paths["build_manifest"], canonical_bytes(self.manifest))
        prompt = {
            "schema_version": "episode1.prompt-evidence.v1",
            "classification": "synthetic_cli_fixture",
            "fixed": [{"id": "fixed-short", "input_tokens": 512}, {"id": "fixed-medium", "input_tokens": 2048}],
            "natural_quality": [{"id": "fixture-natural"}],
        }
        write(self.root, self.paths["prompt_evidence"], canonical_bytes(prompt))

        manifest_digest = sha(build.canonical(self.manifest))
        image = "sha256:" + "b" * 64
        dependencies = []
        for runtime in self.manifest["runtimes"]:
            name = runtime["runtime"]
            dependencies.append({
                "schema_version": "episode1.dependency-validation.v1",
                "status": "pass",
                "runtime": name,
                "lock_sha256": runtime["lock_sha256"],
                "lock_package_count": 1,
                "installed_package_count": 1,
                "bootstrap_allowlist": [],
                "inventory": [{"name": name, "version": "1.0"}],
                "active_dependency_checks": 1,
                "allowed_dependency_mismatches": (
                    [] if name == "vllm" else [{
                        "package": "torch",
                        "dependency": "nvidia-nccl-cu13",
                        "required": "==2.29.7",
                        "marker": 'sys_platform == "linux"',
                        "installed": "2.30.7",
                    }]
                ),
                "errors": [],
                "python_version": "3.12.13",
                "platform": "linux-x86_64",
                "bootstrap_manifest_sha256": None,
            })
        cpu_report = {
            "schema_version": "episode1.cpu-smoke.v1",
            "status": "pass",
            "manifest_sha256": manifest_digest,
            "platform": "linux/amd64",
            "python_version": "3.12.13",
            "materials": self.manifest["materials"],
            "system_inventory": [
                {key: item[key] for key in ("name", "version", "architecture")}
                for item in self.manifest["system_packages"]
            ],
            "dependencies": dependencies,
            "host_keys_present": False,
            "gpu_validation": "not_run",
        }
        attestation = {
            "schema_version": "episode1.image-attestation.v2",
            "classification": "cpu_build_evidence",
            "build_manifest_sha256": manifest_digest,
            "image_manifest_digest": image,
            "config_digest": "sha256:" + "c" * 64,
            "layer_digests": ["sha256:" + "d" * 64],
            "oci_archive_sha256": "e" * 64,
            "final_filesystem_sha256": "f" * 64,
            "local_build_receipt_sha256": "1" * 64,
            "resource_bounds": build.RESOURCE_BOUNDS,
            "cpu_report_sha256": sha(build.canonical(cpu_report)),
            "attestation_digests": {
                "https://slsa.dev/provenance/v0.2": "sha256:" + "2" * 64,
                "https://spdx.dev/Document": "sha256:" + "3" * 64,
            },
            "cpu_report": cpu_report,
            "gpu_validation": "not_run",
            "registry_publication": "not_performed",
        }
        write(self.root, self.paths["build_attestation"], canonical_bytes(attestation))

        with mock.patch.object(build, "RUNTIME_POLICY", self.policy):
            build.validate_manifest(self.manifest, self.root, bind_source=True)
            compiled = compile_material_closure(
                self.root, PRODUCTION_PROFILE, self.manifest,
                {key: self.paths[key] for key in (
                    "build_manifest", "prompt_evidence", "provider_adapter", "build_attestation"
                )},
                dockerfile_builder=build.dockerfile_bytes,
            )
        self.compiled = compiled
        material = compiled["material_manifest"]
        material_raw = canonical_bytes(material)
        write(self.root, self.paths["material"], material_raw)

        now = datetime.now(timezone.utc).replace(microsecond=0)
        values = execution_inputs()
        values["material_sha256"] = material["aggregate_sha256"]
        values["source_commit"] = self.head
        values["provider"]["observed_at"] = iso(now - timedelta(minutes=1))
        values["provider"]["expires_at"] = iso(now + timedelta(minutes=10))
        for component in values["cost_components"]:
            component["observed_at"] = iso(now - timedelta(minutes=1))
            component["expires_at"] = iso(now + timedelta(minutes=10))
        derived = compiled["derived_plan_digests"]
        for runtime_build in values["runtime_builds"]:
            family = runtime_build["runtime"].split("-", 1)[0]
            runtime_build.update({
                "build_spec_sha256": derived["build_spec_sha256"],
                "dependency_lock_sha256": derived["dependency_lock_sha256"][family],
                "launcher_sha256": derived["launcher_sha256"],
                "build_attestation_sha256": derived["build_attestation_sha256"],
                "derived_image_digest": image,
            })
        values["capture"].update({
            "collector_sha256": derived["collector_sha256"],
            "private_schema_sha256": derived["private_schema_sha256"],
        })
        plan = compile_execution_candidate(protocol(), values)
        plan_raw = canonical_bytes(plan)
        write(self.root, self.paths["plan"], plan_raw)

        approved_at = iso(now - timedelta(seconds=15))
        source = {
            "schema_version": "episode1.owner-approval-record.v1",
            "source_channel": "codex_user_message",
            "plan_sha256": plan["plan_sha256"],
            "approved_at": approved_at,
            "spend_approval": spend_approval_phrase(plan),
            "watchdog_risk_approval": watchdog_risk_phrase(plan),
        }
        source_raw = canonical_bytes(source)
        write(self.root, self.paths["authorization_source"], source_raw)
        receipt = {
            "schema_version": "episode1.authorization-receipt.v1",
            "plan_sha256": plan["plan_sha256"],
            "plan_file_sha256": sha(plan_raw),
            "material_file_sha256": sha(material_raw),
            "material_sha256": material["aggregate_sha256"],
            "source_commit": self.head,
            "approved_at": approved_at,
            "source_kind": "retained_owner_record",
            "source_reference_sha256": sha(source_raw),
            "spend_approval": source["spend_approval"],
            "watchdog_risk_approval": source["watchdog_risk_approval"],
        }
        write(self.root, self.paths["authorization_receipt"], canonical_bytes(receipt))
        self.plan = plan

    def argv(self) -> list[str]:
        result = [
            "preflight", "--repository-root", str(self.root),
            "--build-manifest", self.paths["build_manifest"],
            "--prompt-evidence", self.paths["prompt_evidence"],
            "--provider-adapter", self.paths["provider_adapter"],
            "--build-attestation", self.paths["build_attestation"],
            "--material", self.paths["material"],
            "--plan", self.paths["plan"],
            "--authorization-receipt", self.paths["authorization_receipt"],
            "--authorization-source", self.paths["authorization_source"],
            "--unique-name", "episode1-candidate-1-synthetic-fixture",
            "--private-evidence-directory", str(self.root / "private/evidence-unused"),
            "--run-id", "run-synthetic-preflight",
        ]
        return result

    @contextlib.contextmanager
    def reduced_build_policy(self):
        with mock.patch.object(build, "RUNTIME_POLICY", self.policy):
            yield


class ExecuteEpisode1PreflightIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="episode1-cli-integration-")
        self.fixture = Fixture(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def invoke(self) -> tuple[int, dict[str, object]]:
        output = io.StringIO()
        # The managed test sandbox denies Darwin sysctl. Inject one closed,
        # fixture-only clock-domain observation at that OS boundary; all
        # compiler, material, authorization, and RunContext code remains real.
        with (
            self.fixture.reduced_build_policy(),
            mock.patch.object(cli, "observe_clock_domain", return_value="synthetic-local-boot-domain"),
            contextlib.redirect_stdout(output),
        ):
            status = cli.main(self.fixture.argv())
        return status, json.loads(output.getvalue())

    def test_real_cli_preflight_composes_all_pure_gates_without_importing_adapter(self) -> None:
        status, output = self.invoke()
        self.assertEqual(0, status)
        self.assertEqual("preflight", output["mode"])
        self.assertEqual(self.fixture.plan["plan_sha256"], output["plan_sha256"])
        self.assertEqual(self.fixture.compiled["closure_receipt"]["receipt_sha256"], output["closure_receipt_sha256"])
        self.assertFalse(self.fixture.marker.exists())

    def test_material_mutation_rejected_before_adapter_import(self) -> None:
        target = self.fixture.root / "src/runpod_benchmark/episode1_capture.py"
        target.write_bytes(target.read_bytes() + b"\n# post-approval mutation\n")
        with self.assertRaisesRegex(ValueError, "material manifest|material bytes|exact closure|material_hash"):
            self.invoke()
        self.assertFalse(self.fixture.marker.exists())

    def test_rehashed_plan_projection_mutation_rejected_before_adapter_import(self) -> None:
        path = self.fixture.root / self.fixture.paths["plan"]
        plan = _strict_json(path.read_bytes(), "plan")
        plan["runtime_builds"][0]["launcher_sha256"] = "9" * 64
        body = dict(plan)
        body.pop("plan_sha256")
        plan["plan_sha256"] = sha(canonical_json(body).encode())
        path.write_bytes(canonical_bytes(plan))
        with self.assertRaisesRegex(ValueError, "byte-derived|authorization|digest"):
            self.invoke()
        self.assertFalse(self.fixture.marker.exists())

    def test_prompt_material_mutation_rejected_before_adapter_import(self) -> None:
        path = self.fixture.root / self.fixture.paths["prompt_evidence"]
        prompt = _strict_json(path.read_bytes(), "prompt")
        prompt["natural_quality"].append({"id": "unapproved"})
        path.write_bytes(canonical_bytes(prompt))
        with self.assertRaisesRegex(ValueError, "exact closure|material"):
            self.invoke()
        self.assertFalse(self.fixture.marker.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
