import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_publication_privacy.py"
SPEC = importlib.util.spec_from_file_location("check_publication_privacy", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PublicationPrivacyTests(unittest.TestCase):
    def test_current_template_passes_snapshot_scan(self):
        self.assertEqual(MODULE.check(ROOT), ())
        self.assertEqual(MODULE.check(ROOT, files_only=True), ())

    def test_reports_categories_and_locations_without_values(self):
        credential = "gh" + "p_" + "A" * 32
        assigned_value = "high-entropy-" + "B" * 24
        private_path = "/" + "Users" + "/private-person/workspace/result.json"
        corporate_email = "person" + "@" + "company.invalid-corp.com"
        private_host = "https://" + "service" + ".internal" + ":8443/v1"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "candidate.txt").write_text(
                "\n".join(
                    (
                        credential,
                        private_path,
                        corporate_email,
                        private_host,
                        'password = "' + assigned_value + '"',
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                status = MODULE.main(["--root", str(root)])
            rendered = stdout.getvalue() + stderr.getvalue()
            self.assertEqual(status, 1)
            for category in (
                "credential-token",
                "credential-assignment",
                "private-home-path",
                "email-address",
                "private-host",
            ):
                self.assertIn(f"category={category}", rendered)
            self.assertIn("file=candidate.txt", rendered)
            self.assertIn("line=1", rendered)
            for sensitive_value in (
                credential,
                assigned_value,
                private_path,
                corporate_email,
                private_host,
            ):
                self.assertNotIn(sensitive_value, rendered)

    def test_allows_documentation_examples_public_identifiers_and_integrity(self):
        text = "\n".join(
            (
                "https://github.com/KVSDURGASURESH/token-by-token",
                "12345+public-handle@users.noreply.github.com",
                "maintainer@example.com",
                "http://192.0.2.10:8000/v1",
                "api_key = REPLACE_ME",
                "model_revision = " + "a" * 64,
                '"integrity": "sha512-ghp_' + "A" * 40 + '",',
                r'pattern = r"\\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{20,}\\b"',
            )
        )
        self.assertEqual(MODULE.scan_text("package-lock.json", text), set())

    def test_history_scans_only_commits_reachable_from_head(self):
        private_path = "/" + "home" + "/private-person/workspace/evidence.json"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            corporate_email = "person" + "@" + "company.invalid-corp.com"
            env = {
                **os.environ,
                "GIT_AUTHOR_NAME": "Public Author",
                "GIT_AUTHOR_EMAIL": corporate_email,
                "GIT_COMMITTER_NAME": "Public Author",
                "GIT_COMMITTER_EMAIL": corporate_email,
            }
            document = root / "journal.md"
            document.write_text(private_path + "\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "journal.md"], check=True, env=env)
            subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "private"], check=True, env=env)
            document.write_text("sanitized\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "commit", "-qam", "sanitize"], check=True, env=env)
            self.assertEqual(MODULE.check(root), ())
            findings = MODULE.check(root, history=True)
            self.assertTrue(any(item.category == "private-home-path" for item in findings))
            self.assertTrue(any(item.category == "email-address" for item in findings))
            rendered = "\n".join(item.render() for item in findings)
            self.assertIn("commit=", rendered)
            self.assertIn("journal.md", rendered)
            self.assertNotIn(private_path, rendered)
            self.assertNotIn(corporate_email, rendered)


if __name__ == "__main__":
    unittest.main()
