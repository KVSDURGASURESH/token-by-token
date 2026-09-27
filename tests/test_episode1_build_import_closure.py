import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build = load("episode1_build_closure", SCRIPTS / "episode1_build.py")
smoke = load("episode1_cpu_smoke_closure", SCRIPTS / "episode1_cpu_smoke.py")


class ImportClosureTests(unittest.TestCase):
    def fixture(self, files):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        paths = set()
        for name, text in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            paths.add(name)
        self.addCleanup(tmp.cleanup)
        return root, paths

    def test_eager_init_transitive_closure_passes(self):
        root, paths = self.fixture({
            "src/runpod_benchmark/__init__.py": "from . import eager\n",
            "src/runpod_benchmark/eager.py": "from .core import value\n",
            "src/runpod_benchmark/core.py": "value = 1\n",
        })
        result = build.validate_import_closure(root, paths)
        self.assertEqual(result["modules"], ["runpod_benchmark", "runpod_benchmark.core",
                                             "runpod_benchmark.eager"])

    def test_source_size_is_bounded_before_read(self):
        root, paths = self.fixture({"src/runpod_benchmark/__init__.py": ""})
        source = root / "src/runpod_benchmark/__init__.py"
        with source.open("wb") as stream:
            stream.truncate(2 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(build.BuildError, "python_material_too_large"):
            build.validate_import_closure(root, paths)

    def test_missing_relative_import_fails(self):
        root, paths = self.fixture({
            "src/runpod_benchmark/__init__.py": "",
            "src/runpod_benchmark/control.py": "from .missing import value\n",
        })
        with self.assertRaisesRegex(build.BuildError, "unresolved_local_import:runpod_benchmark.missing"):
            build.validate_import_closure(root, paths)

    def test_missing_eager_init_import_fails(self):
        root, paths = self.fixture({
            "src/runpod_benchmark/__init__.py": "from . import absent\n",
        })
        with self.assertRaisesRegex(build.BuildError, "runpod_benchmark.absent"):
            build.validate_import_closure(root, paths)

    def test_nested_module_requires_package_initializer(self):
        root, paths = self.fixture({
            "src/runpod_benchmark/__init__.py": "",
            "src/runpod_benchmark/sub/control.py": "value = 1\n",
        })
        with self.assertRaisesRegex(build.BuildError, "runpod_benchmark.sub"):
            build.validate_import_closure(root, paths)

    def test_literal_dynamic_local_import_is_in_closure(self):
        root, paths = self.fixture({
            "src/runpod_benchmark/__init__.py": "",
            "src/runpod_benchmark/control.py":
                "import importlib as il\nmodule = il.import_module('runpod_benchmark.worker')\n",
            "src/runpod_benchmark/worker.py": "value = 1\n",
        })
        build.validate_import_closure(root, paths)
        (root / "src/runpod_benchmark/worker.py").unlink()
        paths.remove("src/runpod_benchmark/worker.py")
        with self.assertRaisesRegex(build.BuildError, "runpod_benchmark.worker"):
            build.validate_import_closure(root, paths)

    def test_nonliteral_dynamic_import_fails_closed(self):
        root, paths = self.fixture({
            "src/runpod_benchmark/__init__.py": "",
            "src/runpod_benchmark/control.py": "from importlib import import_module\nimport_module(name)\n",
        })
        with self.assertRaisesRegex(build.BuildError, "unresolved_dynamic_import"):
            build.validate_import_closure(root, paths)

    def test_declared_entrypoint_must_be_staged(self):
        root, paths = self.fixture({"src/runpod_benchmark/__init__.py": ""})
        with self.assertRaisesRegex(build.BuildError, "missing_cpu_startup_module"):
            build.validate_import_closure(root, paths,
                                          entry_module="runpod_benchmark.episode1_remote_control")

    def test_required_materials_cover_control_and_protocol(self):
        self.assertIn("src/runpod_benchmark/episode1.py", build.REQUIRED)
        self.assertIn("src/runpod_benchmark/episode1_remote_control.py", build.REQUIRED)
        self.assertIn("src/runpod_benchmark/native_probe_hardening.py", build.REQUIRED)
        self.assertIn("runtime/episode1/cpu-startup.json", build.REQUIRED)

    def test_builder_contract_is_closed_bounded_and_fixed(self):
        valid = json.dumps({"schema_version": "episode1.cpu-startup.v1",
                            "module": "runpod_benchmark.episode1_remote_control",
                            "argv": ["--help"]})
        root, paths = self.fixture({"runtime/episode1/cpu-startup.json": valid})
        self.assertEqual(build.cpu_startup_contract(root, paths)["argv"], ["--help"])
        (root / "runtime/episode1/cpu-startup.json").write_text(valid[:-1] + ',"argv":[]}')
        with self.assertRaisesRegex(build.BuildError, "duplicate_json_key"):
            build.cpu_startup_contract(root, paths)
        (root / "runtime/episode1/cpu-startup.json").write_bytes(b" " * 4097)
        with self.assertRaisesRegex(build.BuildError, "too_large"):
            build.cpu_startup_contract(root, paths)


class CpuStartupTests(unittest.TestCase):
    def fixture(self, with_contract=True):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        package = root / "runpod_benchmark"
        package.mkdir()
        (package / "__init__.py").write_text("import os\nassert 'RUNPOD_API_KEY' not in os.environ\n")
        (package / "episode1_remote_control.py").write_text(
            "import argparse, os\n"
            "assert 'RUNPOD_API_KEY' not in os.environ\n"
            "p=argparse.ArgumentParser(); p.parse_args()\n")
        if with_contract:
            contract = root / "materials/runtime/episode1/cpu-startup.json"
            contract.parent.mkdir(parents=True)
            contract.write_text(json.dumps({"schema_version": "episode1.cpu-startup.v1",
                                             "module": "runpod_benchmark.episode1_remote_control",
                                             "argv": ["--help"]}))
        self.addCleanup(tmp.cleanup)
        return root

    def test_package_import_and_declared_help_startup(self):
        old = os.environ.get("RUNPOD_API_KEY")
        os.environ["RUNPOD_API_KEY"] = "must-not-propagate"
        try:
            smoke.verify_control_startup(self.fixture())
        finally:
            if old is None:
                os.environ.pop("RUNPOD_API_KEY", None)
            else:
                os.environ["RUNPOD_API_KEY"] = old

    def test_missing_contract_fails(self):
        with self.assertRaisesRegex(ValueError, "cpu_startup_contract"):
            smoke.verify_control_startup(self.fixture(with_contract=False))

    def test_success_requires_usage_text(self):
        root = self.fixture()
        (root / "runpod_benchmark/episode1_remote_control.py").write_text("")
        with self.assertRaisesRegex(ValueError, "cpu_startup_usage_missing"):
            smoke.verify_control_startup(root)

    def test_contract_duplicate_key_fails(self):
        root = self.fixture()
        (root / "materials/runtime/episode1/cpu-startup.json").write_text(
            '{"schema_version":"episode1.cpu-startup.v1","module":"runpod_benchmark.episode1_remote_control",'
            '"module":"runpod_benchmark.episode1_remote_control","argv":["--help"]}')
        with self.assertRaisesRegex(ValueError, "duplicate_json_key"):
            smoke.verify_control_startup(root)

    def test_contract_size_is_bounded_before_parse(self):
        root = self.fixture()
        (root / "materials/runtime/episode1/cpu-startup.json").write_bytes(b" " * 4097)
        with self.assertRaisesRegex(ValueError, "too_large"):
            smoke.verify_control_startup(root)

    def test_control_command_has_wall_timeout(self):
        with self.assertRaisesRegex(ValueError, "control_startup_timeout"):
            smoke.control_command([sys.executable, "-c", "import time;time.sleep(2)"],
                                  cwd=str(self.fixture(False)), timeout=0.05)

    def test_normal_leader_exit_reaps_background_group(self):
        root = self.fixture(False)
        pidfile = root / "child.pid"
        code = ("import pathlib,subprocess,sys;"
                "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
                f"pathlib.Path({str(pidfile)!r}).write_text(str(p.pid))")
        with self.assertRaisesRegex(ValueError, "control_startup_descendants"):
            smoke.control_command([sys.executable, "-c", code], cwd=str(root), timeout=1)
        pid = int(pidfile.read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)


if __name__ == "__main__":
    unittest.main()
