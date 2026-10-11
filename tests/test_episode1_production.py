import hashlib
import importlib.metadata
import json
import platform
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from runpod_benchmark.episode1_production import (
    ProductionCompositionError,
    _canonical_json_bytes,
    _verify_client_environment,
    _verify_image_attestation,
    _verify_prompt_evidence,
    execute_prepared_production,
)


class ProductionGateTests(unittest.TestCase):
    @patch("runpod_benchmark.episode1_production._load_adapter")
    def test_invalid_factory_output_still_closes_provider(self, load_adapter) -> None:
        provider = MagicMock()
        provider.close.return_value = True
        load_adapter.return_value = SimpleNamespace(
            build_episode1_components=lambda **_kwargs: {"provider": provider}
        )
        with self.assertRaisesRegex(ProductionCompositionError, "component set"):
            execute_prepared_production(
                SimpleNamespace(context=object(), prompt_evidence={}),
                private_evidence_directory=Path("unused"),
            )
        provider.close.assert_called_once_with()

    def _client_contract(self):
        return {
            "schema_version": "episode1.client-environment.v1",
            "python_implementation": platform.python_implementation(),
            "python_version": ".".join(str(value) for value in sys.version_info[:3]),
            "distributions": {
                "jsonschema": "1", "packaging": "2", "transformers": "3",
                "zstandard": "4",
            },
        }

    def _client_lock(self):
        return b'''version = 1
revision = 3
requires-python = ">=3.12"

[[package]]
name = "jsonschema"
version = "1"
dependencies = [{ name = "attrs" }]

[[package]]
name = "attrs"
version = "5"

[[package]]
name = "packaging"
version = "2"

[[package]]
name = "transformers"
version = "3"
dependencies = [{ name = "active", marker = "python_version >= '3.0'" }, { name = "inactive", marker = "python_version < '2.0'" }]

[[package]]
name = "active"
version = "6"

[[package]]
name = "inactive"
version = "7"

[[package]]
name = "zstandard"
version = "4"

[[package]]
name = "unrelated"
version = "99"
'''

    @patch(
        "runpod_benchmark.episode1_production.importlib.metadata.version",
        side_effect=lambda name: {
            "jsonschema": "1", "packaging": "2", "transformers": "3",
            "zstandard": "4", "attrs": "5", "active": "6",
        }[name],
    )
    def test_client_environment_requires_active_transitive_closure(self, version) -> None:
        _verify_client_environment(
            json.dumps(self._client_contract()).encode(), self._client_lock()
        )
        queried = {call.args[0] for call in version.call_args_list}
        self.assertTrue({"attrs", "active"} <= queried)
        self.assertNotIn("inactive", queried)
        self.assertNotIn("unrelated", queried)

    @patch("runpod_benchmark.episode1_production.importlib.metadata.version")
    def test_client_environment_rejects_absent_transitive(self, version) -> None:
        versions = {
            "jsonschema": "1", "packaging": "2", "transformers": "3",
            "zstandard": "4", "active": "6",
        }
        def observed(name):
            if name not in versions:
                raise importlib.metadata.PackageNotFoundError(name)
            return versions[name]
        version.side_effect = observed
        with self.assertRaisesRegex(ProductionCompositionError, "absent"):
            _verify_client_environment(
                json.dumps(self._client_contract()).encode(), self._client_lock()
            )

    @patch("runpod_benchmark.episode1_production.importlib.metadata.version", return_value="1")
    def test_client_environment_rejects_contract_lock_disagreement(self, _version) -> None:
        contract = self._client_contract()
        contract["distributions"]["jsonschema"] = "wrong"
        with self.assertRaisesRegex(ProductionCompositionError, "differs from dependency lock"):
            _verify_client_environment(json.dumps(contract).encode(), self._client_lock())

    def test_prompt_evidence_comes_from_retained_bytes(self) -> None:
        retained = {"fixed": [{"id": "retained"}], "natural_quality": []}
        raw = json.dumps(retained, sort_keys=True).encode()
        self.assertEqual(retained, _verify_prompt_evidence(raw, retained))
        with self.assertRaisesRegex(ProductionCompositionError, "retained material bytes"):
            _verify_prompt_evidence(raw, {"fixed": [], "natural_quality": []})

    def _runtime_locks(self):
        def locked(name):
            return (
                "--index-url https://pypi.org/simple\n"
                "--only-binary :all:\n\n"
                f"{name}==1 \\\n"
                f"    --hash=sha256:{'a' * 64}\n"
            ).encode()
        return {
            "runtime/episode1/locks/vllm.lock": locked("vllm"),
            "runtime/episode1/locks/sglang.lock": locked("sglang"),
        }

    def _manifest(self, locks):
        return {
            "materials": [{"path": "runtime/episode1/control.sh", "sha256": "1" * 64}],
            "system_packages": [
                {"name": "python3.12", "version": "3.12.13", "architecture": "amd64",
                 "path": "python.deb", "sha256": "2" * 64, "source_url": "https://example.invalid/python.deb"}
            ],
            "runtimes": [
                {"runtime": "vllm", "lock_path": "runtime/episode1/locks/vllm.lock",
                 "lock_sha256": hashlib.sha256(locks["runtime/episode1/locks/vllm.lock"]).hexdigest()},
                {"runtime": "sglang", "lock_path": "runtime/episode1/locks/sglang.lock",
                 "lock_sha256": hashlib.sha256(locks["runtime/episode1/locks/sglang.lock"]).hexdigest()},
            ],
        }

    def _dependency(self, runtime, lock):
        return {
            "schema_version": "episode1.dependency-validation.v1", "status": "pass",
            "runtime": runtime, "lock_sha256": lock, "lock_package_count": 1,
            "installed_package_count": 1, "bootstrap_allowlist": [],
            "inventory": [{"name": runtime, "version": "1"}],
            "active_dependency_checks": 1, "allowed_dependency_mismatches": (
                [] if runtime == "vllm" else [{
                    "package": "torch", "dependency": "nvidia-nccl-cu13",
                    "required": "==2.29.7", "marker": 'sys_platform == "linux"',
                    "installed": "2.30.7",
                }]
            ),
            "errors": [], "python_version": "3.12.13", "platform": "linux-x86_64",
            "bootstrap_manifest_sha256": None,
        }

    def _attestation_inputs(self):
        locks = self._runtime_locks()
        manifest = self._manifest(locks)
        manifest_sha = hashlib.sha256(_canonical_json_bytes(manifest)).hexdigest()
        report = {
            "schema_version": "episode1.cpu-smoke.v1", "status": "pass",
            "manifest_sha256": manifest_sha, "platform": "linux/amd64",
            "python_version": "3.12.13", "materials": manifest["materials"],
            "system_inventory": [
                {"name": "python3.12", "version": "3.12.13", "architecture": "amd64"}
            ],
            "dependencies": [
                self._dependency("vllm", manifest["runtimes"][0]["lock_sha256"]),
                self._dependency("sglang", manifest["runtimes"][1]["lock_sha256"]),
            ],
            "host_keys_present": False, "gpu_validation": "not_run",
        }
        image_digest = "sha256:" + "a" * 64
        plan = {"runtime_builds": [
            {"runtime": "vllm", "derived_image_digest": image_digest},
            {"runtime": "sglang", "derived_image_digest": image_digest},
        ]}
        bounds = {"oci_archive_bytes": 10, "oci_layers": 2}
        attestation = {
            "schema_version": "episode1.image-attestation.v2",
            "classification": "cpu_build_evidence",
            "build_manifest_sha256": manifest_sha,
            "image_manifest_digest": image_digest,
            "config_digest": "sha256:" + "b" * 64,
            "layer_digests": ["sha256:" + "c" * 64],
            "oci_archive_sha256": "d" * 64,
            "final_filesystem_sha256": "e" * 64,
            "local_build_receipt_sha256": "f" * 64,
            "resource_bounds": bounds,
            "cpu_report_sha256": hashlib.sha256(_canonical_json_bytes(report)).hexdigest(),
            "attestation_digests": {
                "https://slsa.dev/provenance/v0.2": "sha256:" + "1" * 64,
                "https://spdx.dev/Document": "sha256:" + "2" * 64,
            },
            "cpu_report": report,
            "gpu_validation": "not_run",
            "registry_publication": "not_performed",
        }
        return plan, manifest, manifest_sha, bounds, locks, attestation

    def _verify(self, plan, manifest, manifest_sha, bounds, locks, attestation):
        _verify_image_attestation(
            plan, json.dumps(attestation).encode(), build_manifest=manifest,
            build_manifest_sha256=manifest_sha, expected_resource_bounds=bounds,
            runtime_lock_bytes=locks,
        )

    def test_image_attestation_accepts_closed_inspector_cpu_evidence(self) -> None:
        self._verify(*self._attestation_inputs())

    def test_image_attestation_rejects_unbound_or_open_evidence(self) -> None:
        for mutation, message in (
            (lambda item: item.update(classification="unbound_cpu_build_inspection"), "selected CPU"),
            (lambda item: item.update(local_build_receipt_sha256=None), "selected CPU"),
            (lambda item: item.update(resource_bounds={}), "selected CPU"),
            (lambda item: item.update(extra="open"), "open or incomplete"),
        ):
            inputs = self._attestation_inputs()
            mutation(inputs[-1])
            with self.subTest(message=message), self.assertRaisesRegex(ProductionCompositionError, message):
                self._verify(*inputs)

    def test_image_attestation_rejects_resealed_report_with_wrong_selected_lock(self) -> None:
        plan, manifest, manifest_sha, bounds, locks, attestation = self._attestation_inputs()
        attestation["cpu_report"]["dependencies"][0]["lock_sha256"] = "9" * 64
        attestation["cpu_report_sha256"] = hashlib.sha256(
            _canonical_json_bytes(attestation["cpu_report"])
        ).hexdigest()
        with self.assertRaisesRegex(ProductionCompositionError, "selected runtime"):
            self._verify(plan, manifest, manifest_sha, bounds, locks, attestation)

    def test_image_attestation_rejects_resealed_bogus_dependency_inventory(self) -> None:
        plan, manifest, manifest_sha, bounds, locks, attestation = self._attestation_inputs()
        dependency = attestation["cpu_report"]["dependencies"][0]
        dependency["inventory"] = [{"name": "vllm", "version": "999"}]
        attestation["cpu_report_sha256"] = hashlib.sha256(
            _canonical_json_bytes(attestation["cpu_report"])
        ).hexdigest()
        with self.assertRaisesRegex(ProductionCompositionError, "selected runtime"):
            self._verify(plan, manifest, manifest_sha, bounds, locks, attestation)

    def test_image_attestation_rejects_report_digest_mismatch(self) -> None:
        inputs = self._attestation_inputs()
        inputs[-1]["cpu_report_sha256"] = "0" * 64
        with self.assertRaisesRegex(ProductionCompositionError, "embedded report bytes"):
            self._verify(*inputs)


if __name__ == "__main__":
    unittest.main()
