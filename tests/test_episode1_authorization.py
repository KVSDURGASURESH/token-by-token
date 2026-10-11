from __future__ import annotations

import hashlib
import json
import unittest
from datetime import datetime, timezone

from runpod_benchmark.episode1 import canonical_json
from runpod_benchmark.episode1_authorization import AuthorizationError, verify_authorization_receipt
from runpod_benchmark.episode1_execution import compile_execution_candidate, spend_approval_phrase, watchdog_risk_phrase
from test_episode1_execution import inputs, protocol

MATERIAL_BYTES = b"print('bound execution material')\n"


def fixture():
    files = [{"path": "src/example.py", "sha256": hashlib.sha256(MATERIAL_BYTES).hexdigest()}]
    aggregate = hashlib.sha256(canonical_json(files).encode()).hexdigest()
    material = (canonical_json({
        "aggregate_sha256": aggregate,
        "classification": "execution_material_hashes",
        "files": files,
    }) + "\n").encode()
    values = inputs()
    values["material_sha256"] = aggregate
    plan = compile_execution_candidate(protocol(), values)
    plan_bytes = (canonical_json(plan) + "\n").encode()
    source = (canonical_json({
        "schema_version": "episode1.owner-approval-record.v1",
        "source_channel": "codex_user_message",
        "plan_sha256": plan["plan_sha256"],
        "approved_at": "2026-09-22T12:09:00Z",
        "spend_approval": spend_approval_phrase(plan),
        "watchdog_risk_approval": watchdog_risk_phrase(plan),
    }) + "\n").encode()
    receipt = {
        "schema_version": "episode1.authorization-receipt.v1",
        "plan_sha256": plan["plan_sha256"],
        "plan_file_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "material_file_sha256": hashlib.sha256(material).hexdigest(),
        "material_sha256": aggregate,
        "source_commit": plan["source_commit"],
        "approved_at": "2026-09-22T12:09:00Z",
        "source_kind": "retained_owner_record",
        "source_reference_sha256": hashlib.sha256(source).hexdigest(),
        "spend_approval": spend_approval_phrase(plan),
        "watchdog_risk_approval": watchdog_risk_phrase(plan),
    }
    return plan, plan_bytes, material, source, receipt


def observed(plan):
    return {
        "material_files": {"src/example.py": MATERIAL_BYTES},
        "observed_source_commit": plan["source_commit"],
    }


class AuthorizationTests(unittest.TestCase):
    def test_exact_external_receipt_verifies(self):
        plan, plan_bytes, material, source, receipt = fixture()
        digest = verify_authorization_receipt(
            plan, receipt, plan_file_bytes=plan_bytes, material_file_bytes=material,
            **observed(plan),
            source_record_bytes=source,
            verification_time=datetime(2026, 9, 22, 12, 10, tzinfo=timezone.utc),
        )
        self.assertEqual(len(digest), 64)

    def test_changed_bytes_or_inline_source_fail_closed(self):
        plan, plan_bytes, material, source, receipt = fixture()
        with self.assertRaisesRegex(AuthorizationError, "material file bytes"):
            verify_authorization_receipt(
                plan, receipt, plan_file_bytes=plan_bytes, material_file_bytes=material + b"x",
                **observed(plan),
                source_record_bytes=source,
                verification_time=datetime(2026, 9, 22, 12, 10, tzinfo=timezone.utc),
            )
        receipt["source_kind"] = "command_line"
        with self.assertRaisesRegex(AuthorizationError, "external owner"):
            verify_authorization_receipt(
                plan, receipt, plan_file_bytes=plan_bytes, material_file_bytes=material,
                **observed(plan),
                source_record_bytes=source,
                verification_time=datetime(2026, 9, 22, 12, 10, tzinfo=timezone.utc),
            )

    def test_open_or_changed_approval_receipt_fails(self):
        plan, plan_bytes, material, source, receipt = fixture()
        receipt["extra"] = True
        with self.assertRaisesRegex(AuthorizationError, "schema"):
            verify_authorization_receipt(
                plan, receipt, plan_file_bytes=plan_bytes, material_file_bytes=material,
                **observed(plan),
                source_record_bytes=source,
                verification_time=datetime(2026, 9, 22, 12, 10, tzinfo=timezone.utc),
            )
        receipt.pop("extra")
        receipt["spend_approval"] += " "
        with self.assertRaisesRegex(ValueError, "does not exactly match"):
            verify_authorization_receipt(
                plan, receipt, plan_file_bytes=plan_bytes, material_file_bytes=material,
                **observed(plan),
                source_record_bytes=source,
                verification_time=datetime(2026, 9, 22, 12, 10, tzinfo=timezone.utc),
            )

    def test_plan_parse_source_binding_and_future_time_fail_closed(self):
        plan, plan_bytes, material, source, receipt = fixture()
        changed_plan = dict(plan)
        changed_plan["candidate_id"] = "different"
        changed_bytes = (canonical_json(changed_plan) + "\n").encode()
        receipt["plan_file_sha256"] = hashlib.sha256(changed_bytes).hexdigest()
        with self.assertRaisesRegex(AuthorizationError, "parse to the verified plan"):
            verify_authorization_receipt(
                plan, receipt, plan_file_bytes=changed_bytes, material_file_bytes=material,
                **observed(plan),
                source_record_bytes=source,
                verification_time=datetime(2026, 9, 22, 12, 10, tzinfo=timezone.utc),
            )
        receipt["plan_file_sha256"] = hashlib.sha256(plan_bytes).hexdigest()
        with self.assertRaisesRegex(AuthorizationError, "external source bytes"):
            verify_authorization_receipt(
                plan, receipt, plan_file_bytes=plan_bytes, material_file_bytes=material,
                **observed(plan),
                source_record_bytes=source + b"x",
                verification_time=datetime(2026, 9, 22, 12, 10, tzinfo=timezone.utc),
            )
        with self.assertRaisesRegex(AuthorizationError, "after the pre-create"):
            verify_authorization_receipt(
                plan, receipt, plan_file_bytes=plan_bytes, material_file_bytes=material,
                **observed(plan),
                source_record_bytes=source,
                verification_time=datetime(2026, 9, 22, 12, 8, tzinfo=timezone.utc),
            )

    def test_arbitrary_source_bytes_cannot_authorize_receipt_strings(self):
        plan, plan_bytes, material, _source, receipt = fixture()
        source = b'{"note":"approval words exist only in the independent receipt"}\n'
        receipt["source_reference_sha256"] = hashlib.sha256(source).hexdigest()
        with self.assertRaisesRegex(AuthorizationError, "source record schema"):
            verify_authorization_receipt(
                plan, receipt, plan_file_bytes=plan_bytes, material_file_bytes=material,
                **observed(plan),
                source_record_bytes=source,
                verification_time=datetime(2026, 9, 22, 12, 10, tzinfo=timezone.utc),
            )

    def test_material_paths_bytes_classification_and_head_are_exact(self):
        plan, plan_bytes, material, source, receipt = fixture()
        base = dict(
            plan_file_bytes=plan_bytes, material_file_bytes=material,
            source_record_bytes=source,
            verification_time=datetime(2026, 9, 22, 12, 10, tzinfo=timezone.utc),
        )
        with self.assertRaisesRegex(AuthorizationError, "material bytes"):
            verify_authorization_receipt(
                plan, receipt, material_files={"src/example.py": b"changed"},
                observed_source_commit=plan["source_commit"], **base,
            )
        with self.assertRaisesRegex(AuthorizationError, "source HEAD"):
            verify_authorization_receipt(
                plan, receipt, material_files={"src/example.py": MATERIAL_BYTES},
                observed_source_commit="0" * 40, **base,
            )
        manifest = json.loads(material)
        manifest["classification"] = "arbitrary"
        changed = (canonical_json(manifest) + "\n").encode()
        receipt["material_file_sha256"] = hashlib.sha256(changed).hexdigest()
        with self.assertRaisesRegex(AuthorizationError, "classification"):
            verify_authorization_receipt(
                plan, receipt, material_file_bytes=changed,
                material_files={"src/example.py": MATERIAL_BYTES},
                observed_source_commit=plan["source_commit"],
                plan_file_bytes=plan_bytes, source_record_bytes=source,
                verification_time=datetime(2026, 9, 22, 12, 10, tzinfo=timezone.utc),
            )

    def test_noncanonical_material_paths_fail_closed(self):
        plan, plan_bytes, material, source, receipt = fixture()
        for bad_path in ("../src/example.py", "src/./example.py", "src\\example.py"):
            manifest = json.loads(material)
            manifest["files"][0]["path"] = bad_path
            manifest["aggregate_sha256"] = hashlib.sha256(
                canonical_json(manifest["files"]).encode()
            ).hexdigest()
            changed = (canonical_json(manifest) + "\n").encode()
            receipt["material_file_sha256"] = hashlib.sha256(changed).hexdigest()
            with self.subTest(path=bad_path), self.assertRaisesRegex(AuthorizationError, "path"):
                verify_authorization_receipt(
                    plan, receipt, plan_file_bytes=plan_bytes,
                    material_file_bytes=changed, material_files={bad_path: MATERIAL_BYTES},
                    observed_source_commit=plan["source_commit"], source_record_bytes=source,
                    verification_time=datetime(2026, 9, 22, 12, 10, tzinfo=timezone.utc),
                )


if __name__ == "__main__":
    unittest.main()
