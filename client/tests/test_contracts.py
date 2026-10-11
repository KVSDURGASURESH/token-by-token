from __future__ import annotations

import copy
import unittest

from token_by_token_cli.contracts import episode_manifest, validate_document
from token_by_token_cli.errors import ClientError


class ContractTests(unittest.TestCase):
    def test_every_episode_has_a_valid_public_manifest(self) -> None:
        for number in range(17):
            with self.subTest(number=number):
                document = episode_manifest(number)
                validate_document("episode-manifest.v1", document)
                self.assertEqual(document["episode"], number)
                self.assertEqual(document["selftest"]["classification"], "synthetic_mock")

    def test_manifest_rejects_unknown_control(self) -> None:
        document = copy.deepcopy(episode_manifest(2))
        document["allowed_parameters"]["speculative_drafts"] = {"type": "integer"}
        with self.assertRaisesRegex(ClientError, "UNKNOWN_PROPERTY"):
            validate_document("episode-manifest.v1", document)

    def test_manifest_rejects_unknown_nested_control_property(self) -> None:
        document = copy.deepcopy(episode_manifest(2))
        document["allowed_parameters"]["users"]["endpoint"] = "https://example.invalid"
        with self.assertRaisesRegex(ClientError, "UNKNOWN_PROPERTY"):
            validate_document("episode-manifest.v1", document)

    def test_manifest_requires_explicit_mock_classification(self) -> None:
        document = copy.deepcopy(episode_manifest(2))
        del document["selftest"]["classification"]
        with self.assertRaisesRegex(ClientError, "INVALID_CONTRACT"):
            validate_document("episode-manifest.v1", document)

    def test_out_of_catalog_episode_fails_cleanly(self) -> None:
        with self.assertRaisesRegex(ClientError, "UNKNOWN_EPISODE"):
            episode_manifest(17)


if __name__ == "__main__":
    unittest.main()
