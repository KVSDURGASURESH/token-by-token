from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


HERE = Path(__file__).resolve().parent
FROZEN = Path(os.environ.get("EPISODE1_ASSEMBLY_FROZEN", str(HERE.parent))).resolve()
sys.path[:0] = [str(HERE), str(FROZEN / "scripts"), str(FROZEN / "src"), str(FROZEN / "tests")]

import test_execute_episode1_cli_preflight_integration as fixture_module
import execute_episode1 as cli
import episode1_build as build
from runpod_benchmark.episode1 import canonical_json, sha256_json
from runpod_benchmark.episode1_production import PRODUCTION_TELEMETRY_SERIES
import runpod_benchmark.episode1_production as production
import runpod_benchmark.bounded_runpod_transport as transport_module
import runpod_benchmark.episode1_remote as remote_module
from test_episode1_orchestration_loopback import _prompt_evidence

# The reusable fixture computes its source root relative to its original test
# file. This overlay keeps the frozen sources immutable at their original path.
fixture_module.FROZEN = FROZEN


class BatchEncodingFixture:
    def __init__(self, values: list[int]) -> None:
        # The adapter must normalize a one-row BatchEncoding, not preserve the
        # batch dimension or return this wrapper.
        self.input_ids = [list(values)]


class TokenizerFixture:
    def __init__(self, evidence: dict[str, object]) -> None:
        items = list(evidence["fixed"]) + list(evidence["natural_quality"])
        self._tokens = {
            canonical_json(item["messages"]): list(item["token_ids"])
            for item in items
        }

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        if tokenize is not True or add_generation_prompt is not True:
            raise AssertionError("adapter changed the reviewed chat-template invocation")
        return BatchEncodingFixture(self._tokens[canonical_json(list(messages))])

    def encode(self, text: str, *, add_special_tokens: bool):
        if add_special_tokens is not False or not isinstance(text, str):
            raise AssertionError("adapter changed output-token normalization")
        return [index for index, _part in enumerate(text.split(), start=1)]


class FakeBroker:
    instances: list["FakeBroker"] = []

    def __init__(self, bearer_token: str, **kwargs) -> None:
        if bearer_token != "fixture-api-token" or not callable(kwargs.get("response_factory")):
            raise AssertionError("unexpected bounded transport construction")
        self.closed = 0
        self.requested = 0
        self.instances.append(self)

    def request(self, *args, **kwargs):
        self.requested += 1
        raise AssertionError("assembly proof must never perform a provider request")

    def close(self, *, deadline_monotonic=None) -> bool:
        self.closed += 1
        return True


class AssemblyFixture(fixture_module.Fixture):
    """The prior real-gate fixture with the reviewed adapter and prompt bytes."""

    def __init__(self, parent: Path) -> None:
        original_write = fixture_module.write
        self.generated_prompt = _prompt_evidence()[0]

        def selected_write(root: Path, relative: str, raw: bytes) -> None:
            if relative == cli.PROVIDER_ADAPTER and b"fixture adapter must never execute" in raw:
                # copytree already installed the real bound production adapter.
                return
            if relative == "private/prompt-evidence.json":
                raw = fixture_module.canonical_bytes(self.generated_prompt)
            original_write(root, relative, raw)

        with mock.patch.object(fixture_module, "write", side_effect=selected_write):
            super().__init__(parent)

    def argv(self) -> list[str]:
        argv = super().argv()
        argv[0] = "run"
        return argv


class ExecuteEpisode1CliAssemblyTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeBroker.instances.clear()
        self.temp = tempfile.TemporaryDirectory(prefix="episode1-cli-assembly-")
        self.fixture = AssemblyFixture(Path(self.temp.name))
        self.prompt = self.fixture.generated_prompt
        self.identity = Path(self.temp.name) / "id_ed25519"
        self.known_hosts = Path(self.temp.name) / "known_hosts"
        self.identity.write_text("synthetic-private-key-fixture\n")
        self.known_hosts.write_text("[127.0.0.1]:2222 synthetic-host-key-fixture\n")
        self.identity.chmod(0o600)
        self.known_hosts.chmod(0o600)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def external_fixtures(self):
        tokenizer = TokenizerFixture(self.prompt)
        transformers = types.ModuleType("transformers")
        transformers.AutoTokenizer = SimpleNamespace(
            from_pretrained=lambda path, local_files_only: (
                tokenizer if path == "/fixture/tokenizer" and local_files_only is True
                else (_ for _ in ()).throw(AssertionError("unexpected tokenizer load"))
            )
        )
        environment = {
            "RUNPOD_API_KEY": "fixture-api-token",
            "EPISODE1_APPROVED_IMAGE_REFERENCE": "registry.invalid/qwen@sha256:" + "b" * 64,
            "EPISODE1_AUTHORIZED_KEY_FINGERPRINT": "SHA256:" + "A" * 43,
            "EPISODE1_TOKENIZER_DIRECTORY": "/fixture/tokenizer",
            "EPISODE1_LOCAL_PORT": "18080",
            "EPISODE1_SSH_IDENTITY_FILE": str(self.identity),
            "EPISODE1_SSH_KNOWN_HOSTS_FILE": str(self.known_hosts),
        }
        return transformers, environment

    def test_real_cli_gates_and_real_component_builder_reach_only_stubbed_execution_body(self) -> None:
        transformers, environment = self.external_fixtures()
        observed: dict[str, object] = {}

        def execution_body(**components):
            # This is the sole orchestration boundary stub. All pure gates,
            # source loading, adapter execution, and component construction are real.
            context = components["context"]
            provider = components["provider"]
            evidence = components["private_evidence_directory"]
            self.assertEqual(tuple(PRODUCTION_TELEMETRY_SERIES), tuple(context.telemetry_series))
            self.assertTrue(callable(components["runtime_factory"]))
            self.assertTrue(callable(components["cell_factory"]))
            self.assertTrue(callable(components["telemetry_factory"]))
            self.assertEqual(1.0, components["monitor_poll_seconds"])

            expected_authority = evidence.parent / f".{evidence.name}.watchdog-state" / "authority.json"
            self.assertEqual(expected_authority, provider._authority_path)
            self.assertEqual(expected_authority, provider._permit_path.with_name("authority.json"))

            allocation = SimpleNamespace(
                private_id="fixture-owned-id", ssh_host="127.0.0.1", ssh_public_port=2222
            )
            runtime = components["runtime_factory"](allocation)
            cell = components["cell_factory"](allocation)
            self.assertEqual("fixture-owned-id", next(iter({allocation.private_id})))
            self.assertIsNotNone(runtime)
            for item in (self.prompt["fixed"][0], self.prompt["fixed"][1], self.prompt["natural_quality"][0]):
                normalized = cell.input_token_ids(item["messages"])
                self.assertIs(type(normalized), list)
                self.assertEqual(item["token_ids"], normalized)
                self.assertEqual(len(item["token_ids"]), cell.input_token_counter(item["messages"]))

            block = context.plan["blocks"][0]
            telemetry = components["telemetry_factory"](
                context.plan, block, "run-attempt-1",
                f"{block['block_id']}-attempt-1", 1, allocation, SimpleNamespace()
            )
            self.assertEqual(
                tuple(PRODUCTION_TELEMETRY_SERIES),
                tuple(spec.series_id for spec in telemetry.specs),
            )
            self.assertEqual(context.clock_domain, telemetry.native_clock_domain)
            observed.update(
                authority=str(expected_authority),
                tokens=[len(item["token_ids"]) for item in self.prompt["fixed"]],
                telemetry=len(telemetry.specs),
            )
            return SimpleNamespace(summary={"status": "assembly_stub_complete"})

        output = io.StringIO()
        with (
            self.fixture.reduced_build_policy(),
            mock.patch.object(cli, "observe_clock_domain", return_value="synthetic-local-boot-domain"),
            mock.patch.dict(os.environ, environment, clear=False),
            mock.patch.dict(sys.modules, {"transformers": transformers}),
            mock.patch.object(transport_module, "BoundedRunpodTransport", FakeBroker),
            mock.patch.object(remote_module, "PROMPT_EVIDENCE_SHA256", sha256_json(self.prompt)),
            mock.patch.object(
                remote_module, "TOKENIZER_ASSET_MANIFEST_SHA256",
                sha256_json(self.prompt["asset_sha256"]),
            ),
            mock.patch.object(production, "execute_episode1", side_effect=execution_body),
            contextlib.redirect_stdout(output),
        ):
            status = cli.main(self.fixture.argv())

        result = json.loads(output.getvalue())
        self.assertEqual(0, status)
        self.assertEqual("run", result["mode"])
        self.assertEqual("assembly_stub_complete", result["status"])
        self.assertEqual([512, 2048], observed["tokens"])
        self.assertEqual(len(PRODUCTION_TELEMETRY_SERIES), observed["telemetry"])
        self.assertEqual(1, len(FakeBroker.instances))
        self.assertEqual(0, FakeBroker.instances[0].requested)
        self.assertEqual(1, FakeBroker.instances[0].closed)

    def test_invalid_real_factory_return_closes_constructed_broker_before_rejection(self) -> None:
        transformers, environment = self.external_fixtures()
        original_load = production._load_adapter

        def load_with_return_fault(prepared):
            module = original_load(prepared)
            real_factory = module.build_episode1_components

            def invalid_factory(**kwargs):
                components = dict(real_factory(**kwargs))
                components["monitor_poll_seconds"] = 0.0
                return components

            module.build_episode1_components = invalid_factory
            return module

        execution = mock.Mock(side_effect=AssertionError("invalid components reached execution"))
        with (
            self.fixture.reduced_build_policy(),
            mock.patch.object(cli, "observe_clock_domain", return_value="synthetic-local-boot-domain"),
            mock.patch.dict(os.environ, environment, clear=False),
            mock.patch.dict(sys.modules, {"transformers": transformers}),
            mock.patch.object(transport_module, "BoundedRunpodTransport", FakeBroker),
            mock.patch.object(remote_module, "PROMPT_EVIDENCE_SHA256", sha256_json(self.prompt)),
            mock.patch.object(
                remote_module, "TOKENIZER_ASSET_MANIFEST_SHA256",
                sha256_json(self.prompt["asset_sha256"]),
            ),
            mock.patch.object(production, "_load_adapter", side_effect=load_with_return_fault),
            mock.patch.object(production, "execute_episode1", execution),
        ):
            with self.assertRaisesRegex(
                production.ProductionCompositionError, "monitor poll is invalid"
            ):
                cli.main(self.fixture.argv())

        execution.assert_not_called()
        self.assertEqual(1, len(FakeBroker.instances))
        self.assertEqual(0, FakeBroker.instances[0].requested)
        self.assertEqual(1, FakeBroker.instances[0].closed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
