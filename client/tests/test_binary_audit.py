from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from client.scripts.audit_binary import REQUIRED_MODULES, REQUIRED_RESOURCES, audit_binary
from client.scripts.build_binary import clean_build_environment, load_auditor, local_install_command
from token_by_token_cli.errors import ClientError


class BinaryAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.binary = self.root / "token-by-token"
        self.binary.write_bytes(b"public-client")
        self.extracted_root = self.root / "extracted"
        self.extracted_root.mkdir()
        for index, module in enumerate(sorted(REQUIRED_MODULES)):
            (self.extracted_root / f"{index:04d}-{module}").write_bytes(b"public module")
        for index, resource in enumerate(sorted(REQUIRED_RESOURCES)):
            path = self.extracted_root / f"{index + 100:04d}-{resource}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"public resource")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_inventory(self, modules: list[str], resources: list[str] | None = None) -> Path:
        path = self.root / "analysis.json"
        path.write_text(
            json.dumps(
                {
                    "modules": sorted(REQUIRED_MODULES | set(modules)),
                    "resources": sorted(REQUIRED_RESOURCES | set(resources or [])),
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_audit_accepts_public_client_inventory_and_content(self) -> None:
        (self.extracted_root / "payload.bin").write_bytes(b"token-by-token synthetic_mock")
        audit_binary(self.binary, self.write_inventory(["token_by_token_cli.cli", "jsonschema"]), self.extracted_root)

    def test_audit_rejects_private_module_inventory(self) -> None:
        inventory = self.write_inventory(["token_by_token_cli.cli", "private_runtime.episode_runner"])
        with self.assertRaisesRegex(ClientError, "FORBIDDEN_BUILD_INPUT"):
            audit_binary(self.binary, inventory, self.extracted_root)

    def test_audit_source_does_not_publish_private_tool_identifier(self) -> None:
        private_identifier = bytes.fromhex("6167656e7462656e6368").decode("ascii")
        source = (Path(__file__).resolve().parents[1] / "scripts" / "audit_binary.py").read_text(encoding="utf-8")
        self.assertNotIn(private_identifier, source.lower())

    def test_audit_rejects_hashed_private_tool_identifier(self) -> None:
        private_identifier = bytes.fromhex("6167656e7462656e6368")
        (self.extracted_root / "payload.bin").write_bytes(b"safe-prefix " + private_identifier + b" safe-suffix")
        with self.assertRaisesRegex(ClientError, "FORBIDDEN_BINARY_CONTENT"):
            audit_binary(self.binary, self.write_inventory(["token_by_token_cli.cli"]), self.extracted_root)

    def test_audit_rejects_private_resource_inventory(self) -> None:
        inventory = self.write_inventory(["token_by_token_cli.cli"], ["configs/combos/private.yaml"])
        with self.assertRaisesRegex(ClientError, "FORBIDDEN_BUILD_INPUT"):
            audit_binary(self.binary, inventory, self.extracted_root)

    def test_audit_rejects_modules_and_resources_outside_the_public_allowlist(self) -> None:
        with self.assertRaisesRegex(ClientError, "FORBIDDEN_BUILD_INPUT"):
            audit_binary(
                self.binary,
                self.write_inventory(["token_by_token_cli.cli", "unapproved_plugin.client"]),
                self.extracted_root,
            )
        with self.assertRaisesRegex(ClientError, "FORBIDDEN_BUILD_INPUT"):
            audit_binary(
                self.binary,
                self.write_inventory(["token_by_token_cli.cli"], ["unapproved_plugin/config.json"]),
                self.extracted_root,
            )

    def test_audit_rejects_private_markers_in_extracted_tree(self) -> None:
        (self.extracted_root / "payload.bin").write_bytes(b"safe-prefix private-benchmark-tool --profile private safe-suffix")
        with self.assertRaisesRegex(ClientError, "FORBIDDEN_BINARY_CONTENT"):
            audit_binary(self.binary, self.write_inventory(["token_by_token_cli.cli"]), self.extracted_root)

    def test_audit_rejects_credentials_profiles_and_private_organization(self) -> None:
        private_organization = bytes.fromhex("6d697261737461636b6c616273")
        payloads = (
            bytes.fromhex("6768705f303132333435363738396162636465666768696a6b6c6d6e6f70"),
            b"--profile organization-secret-serving-profile",
            private_organization,
        )
        for index, payload in enumerate(payloads):
            with self.subTest(index=index):
                candidate = self.extracted_root / f"payload-{index}.bin"
                candidate.write_bytes(payload)
                with self.assertRaisesRegex(ClientError, "FORBIDDEN_BINARY_CONTENT"):
                    audit_binary(self.binary, self.write_inventory(["token_by_token_cli.cli"]), self.extracted_root)
                candidate.unlink()

    def test_audit_rejects_private_serving_optimization_terms(self) -> None:
        private_terms = (
            bytes.fromhex("65787472615f6275666665725f6c617a79"),
            bytes.fromhex("6d616d62612d66756c6c2d6d656d6f72792d726174696f"),
            bytes.fromhex("747269746f6e2067646e"),
            bytes.fromhex("6c616e67756167652d6f6e6c79206d6f6465"),
        )
        for index, term in enumerate(private_terms):
            with self.subTest(index=index):
                candidate = self.extracted_root / f"private-term-{index}.bin"
                candidate.write_bytes(term)
                with self.assertRaisesRegex(ClientError, "FORBIDDEN_BINARY_CONTENT"):
                    audit_binary(self.binary, self.write_inventory(["token_by_token_cli.cli"]), self.extracted_root)
                candidate.unlink()

    def test_audit_does_not_echo_sensitive_matched_bytes(self) -> None:
        marker = b"private-benchmark-tool secret-value"
        (self.extracted_root / "payload.bin").write_bytes(marker)
        with self.assertRaises(ClientError) as raised:
            audit_binary(self.binary, self.write_inventory(["token_by_token_cli.cli"]), self.extracted_root)
        self.assertNotIn("secret-value", str(raised.exception))

    def test_clean_build_environment_retains_platform_tool_path(self) -> None:
        environment = clean_build_environment(self.root, self.root / "venv" / "bin")
        self.assertIsNotNone(shutil.which("arch", path=environment["PATH"]))

    def test_build_script_loads_auditor_from_client_root(self) -> None:
        client_root = Path(__file__).resolve().parents[1]
        self.assertIs(load_auditor(client_root), audit_binary)

    def test_local_package_install_reuses_locked_build_environment(self) -> None:
        command = local_install_command(self.root / "venv" / "bin" / "python")
        self.assertEqual(
            command,
            [
                str(self.root / "venv" / "bin" / "python"),
                "-m",
                "pip",
                "install",
                "--no-build-isolation",
                "--no-deps",
                ".",
            ],
        )


if __name__ == "__main__":
    unittest.main()
