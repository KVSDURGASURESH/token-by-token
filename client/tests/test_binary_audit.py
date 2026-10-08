from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from client.scripts.audit_binary import audit_binary
from client.scripts.build_binary import clean_build_environment, load_auditor
from token_by_token_cli.errors import ClientError


class BinaryAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.binary = self.root / "token-by-token"
        self.binary.write_bytes(b"public-client")
        self.extracted_root = self.root / "extracted"
        self.extracted_root.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_inventory(self, modules: list[str], resources: list[str] | None = None) -> Path:
        path = self.root / "analysis.json"
        path.write_text(json.dumps({"modules": modules, "resources": resources or []}), encoding="utf-8")
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

    def test_audit_rejects_private_markers_in_extracted_tree(self) -> None:
        (self.extracted_root / "payload.bin").write_bytes(b"safe-prefix private-benchmark-tool --profile private safe-suffix")
        with self.assertRaisesRegex(ClientError, "FORBIDDEN_BINARY_CONTENT"):
            audit_binary(self.binary, self.write_inventory(["token_by_token_cli.cli"]), self.extracted_root)

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


if __name__ == "__main__":
    unittest.main()
