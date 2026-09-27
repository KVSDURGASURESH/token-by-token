import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
FIXTURES = ROOT / "fixtures" / "episode1"


def load_json(path: Path):
    return json.loads(path.read_text())


def load_prepare_module():
    path = ROOT / "scripts" / "prepare_episode1_fixture.py"
    spec = importlib.util.spec_from_file_location("prepare_episode1_fixture", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Episode1SchemaConformanceTests(unittest.TestCase):
    def validator(self, name: str) -> Draft202012Validator:
        schema = load_json(SCHEMAS / name)
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema)

    def test_generated_and_checked_in_artifacts_match_canonical_schemas(self):
        protocol_validator = self.validator("episode1-protocol.schema.json")
        ledger_validator = self.validator("episode1-phase-ledger.schema.json")
        public_validator = self.validator("episode1-public-aggregate.schema.json")
        observation_validator = self.validator("episode1-observation.schema.json")

        protocol_validator.validate(load_json(FIXTURES / "episode1-planning.json"))
        ledger_validator.validate(load_json(FIXTURES / "phase-ledger.fixture.json"))
        public_validator.validate(load_json(FIXTURES / "public-aggregate.fixture.json"))

        prepare = load_prepare_module()
        with tempfile.TemporaryDirectory() as raw_directory:
            protocol, ledger, _corpus, public = prepare.build(Path(raw_directory))
            protocol_validator.validate(protocol)
            ledger_validator.validate({"classification": "local_fixture", "records": ledger})
            public_validator.validate(public)
            observations = load_json(Path(raw_directory) / "episode1-local-fixture-requests.json")
            self.assertEqual(528, len(observations))
            for observation in observations:
                observation_validator.validate(observation)

        representative = next(item for item in observations if item["status"] == "success")
        reason_codes = {
            "none", "transport", "http_status", "malformed_sse", "missing_usage",
            "token_mismatch", "request_deadline", "cell_deadline", "cancelled_on_drain",
            "tunnel_lost",
            "not_dispatched", "invalid_stop_reason", "truncated", "quality_invalid",
        }
        for reason_code in reason_codes:
            candidate = copy.deepcopy(representative)
            candidate["reason_code"] = reason_code
            observation_validator.validate(candidate)

        provider_observation = copy.deepcopy(representative)
        provider_observation["evidence_class"] = "provider_measurement"
        observation_validator.validate(provider_observation)
        provider_observation["evidence_class"] = "provider_candidate"
        observation_validator.validate(provider_observation)


if __name__ == "__main__":
    unittest.main()
