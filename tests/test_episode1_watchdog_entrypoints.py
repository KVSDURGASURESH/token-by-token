from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class EntrypointLoaderTests(unittest.TestCase):
    def _run_entrypoint(self, module_name: str, *, matching_clock: bool) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            source_root = work / "adapter-source"
            adapter_package = source_root / "adapters"
            adapter_package.mkdir(parents=True)
            (adapter_package / "__init__.py").write_text("", encoding="utf-8")
            marker = work / "adapter-imported"
            adapter_source = adapter_package / "inert.py"
            adapter_source.write_text(
                textwrap.dedent(
                    f"""\
                    from pathlib import Path
                    import runpod_benchmark.episode1_execution

                    Path({str(marker)!r}).write_text("imported", encoding="utf-8")

                    class Provider:
                        def close(self):
                            return True

                    def build():
                        return Provider()
                    """
                ),
                encoding="utf-8",
            )
            # The temporary adapter root models the installed source tree.  A
            # symlink keeps the test from copying or modifying the real package.
            (source_root / "runpod_benchmark").symlink_to(
                ROOT / "src" / "runpod_benchmark", target_is_directory=True
            )
            code = textwrap.dedent(
                """\
                import hashlib
                import importlib
                from pathlib import Path
                import sys
                from types import SimpleNamespace

                root = Path(sys.argv[1])
                module_name = sys.argv[2]
                adapter_source = Path(sys.argv[3])
                marker = Path(sys.argv[4])
                matching_clock = sys.argv[5] == "match"
                sys.path.insert(0, str(root / "scripts"))
                entrypoint = importlib.import_module(module_name)
                digest = hashlib.sha256(adapter_source.read_bytes()).hexdigest()
                entrypoint.read_permit = lambda path: SimpleNamespace(
                    clock_domain="test-boot:monotonic", adapter_sha256=digest
                )
                entrypoint.observe_clock_domain = lambda: (
                    "test-boot:monotonic" if matching_clock else "other-boot:monotonic"
                )
                calls = []
                if module_name == "watchdog_entry":
                    entrypoint.run_guard = lambda **kwargs: calls.append(kwargs)
                    sys.argv = [module_name, "--role", "primary",
                        "--state-directory", str(marker.parent / "state"),
                        "--guard-directory", str(marker.parent / "guard"),
                        "--adapter", "adapters.inert:build",
                        "--adapter-source", str(adapter_source),
                        "--heartbeat-seconds", "1", "--poll-timeout-seconds", "1",
                        "--retry-delay", "0"]
                else:
                    entrypoint.restart_cleanup = lambda **kwargs: calls.append(kwargs)
                    sys.argv = [module_name,
                        "--state-directory", str(marker.parent / "state"),
                        "--plan-sha256", "a" * 64,
                        "--adapter", "adapters.inert:build",
                        "--adapter-source", str(adapter_source),
                        "--retry-delay", "0"]
                if matching_clock:
                    assert entrypoint.main() == 0
                    assert marker.read_text(encoding="utf-8") == "imported"
                    assert len(calls) == 1
                    assert calls[0]["provider"].__class__.__module__ == "adapters.inert"
                else:
                    try:
                        entrypoint.main()
                    except entrypoint.WatchdogError as error:
                        assert "clock domain changed" in str(error)
                    else:
                        raise AssertionError("clock mismatch was accepted")
                    assert not marker.exists(), "adapter imported before the clock gate"
                    assert calls == []
                """
            )
            environment = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": str(work / "home"),
                "LC_ALL": "C",
            }
            return subprocess.run(
                [sys.executable, "-I", "-c", code, str(ROOT), module_name,
                 str(adapter_source), str(marker), "match" if matching_clock else "mismatch"],
                cwd=work,
                env=environment,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )

    def test_watchdog_and_restart_load_digest_bound_adapter_in_clean_interpreter(self):
        for module_name in ("watchdog_entry", "restart_cleanup_entry"):
            with self.subTest(module_name=module_name):
                result = self._run_entrypoint(module_name, matching_clock=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_clock_gate_precedes_adapter_import_for_both_entrypoints(self):
        for module_name in ("watchdog_entry", "restart_cleanup_entry"):
            with self.subTest(module_name=module_name):
                result = self._run_entrypoint(module_name, matching_clock=False)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
