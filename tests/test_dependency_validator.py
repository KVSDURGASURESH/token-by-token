import os
from pathlib import Path
import unittest

from runpod_benchmark.dependency_validator import Distribution, Lock, ValidationInputError, parse_lock_bytes, validate


ENV = {"python_version": "3.12", "python_full_version": "3.12.3", "sys_platform": "linux",
       "platform_machine": "x86_64", "platform_system": "Linux", "os_name": "posix",
       "implementation_name": "cpython", "implementation_version": "3.12.3",
       "platform_python_implementation": "CPython", "platform_release": "x", "platform_version": "x"}


def lock(packages):
    return Lock("a" * 64, packages, {k: 1 for k in packages})


class ParserTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("EPISODE1_REAL_LOCK_DIR"), "set EPISODE1_REAL_LOCK_DIR for retained-lock check")
    def test_optional_real_locks_and_expected_pins(self):
        root = Path(os.environ["EPISODE1_REAL_LOCK_DIR"])
        cases = [(root / "vllm.lock", 196, "vllm", "0.29.0",
                  "c7319e5fc782b79780f4a4a1068f9feae6647531ab4b9540bf468f54a09b6b48"),
                 (root / "sglang-wheel.lock", 243, "sglang", "0.5.20",
                  "6cba8a33762d2b224cf1599858e23dbc5c46384a25a4f7d84d0633c5ea848dc6")]
        for path, count, package, version, digest in cases:
            with self.subTest(path=path):
                with open(path, "rb") as stream:
                    parsed = parse_lock_bytes(stream.read())
                self.assertEqual((count, version, digest), (len(parsed.packages), parsed.packages[package], parsed.sha256))
                self.assertTrue(all(n > 0 for n in parsed.hash_counts.values()))

    def test_literal_compiled_lock_grammar(self):
        raw = (b"# generated\n--index-url https://pypi.org/simple\n"
               b"--extra-index-url https://download.pytorch.org/whl/cu130\n--only-binary :all:\n\n"
               b"Demo_Pkg==1.0+cu130 \\\n    --hash=sha256:" + b"a" * 64 + b"\n    # via root\n")
        parsed = parse_lock_bytes(raw)
        self.assertEqual({"demo-pkg": "1.0+cu130"}, parsed.packages)

    def test_rejects_unsafe_or_unfrozen_forms(self):
        prefix = b"--index-url https://pypi.org/simple\n--only-binary :all:\n"
        bad = [b"-e git+https://x/y.git\n", b"x @ https://x/x.whl\n", b"x==1.tar.gz\n",
               b"x==1 \\\n", b"--trusted-host pypi.org\n"]
        for tail in bad:
            with self.subTest(tail=tail):
                with self.assertRaises(ValidationInputError): parse_lock_bytes(prefix + tail)

    def test_requires_binary_policy_and_https_index(self):
        stanza = b"x==1 \\\n    --hash=sha256:" + b"a" * 64 + b"\n"
        for raw in [b"--index-url https://pypi.org/simple\n" + stanza,
                    b"--only-binary :all:\n" + stanza]:
            with self.assertRaises(ValidationInputError): parse_lock_bytes(raw)


class ValidationTests(unittest.TestCase):
    def _vllm(self, *, nccl="2.29.7", extras=()):
        packages = {"vllm": "0.29.0", "torch": "2.13.0+cu130", "triton": "3.7.1", "nvidia-nccl-cu13": nccl}
        dists = [Distribution("vllm", "0.29.0", ("torch==2.13.0", "ghost; python_version < '3'")),
                 Distribution("torch", "2.13.0+cu130", ("nvidia-nccl-cu13==2.29.7 ; sys_platform == 'linux'", "triton==3.7.1")),
                 Distribution("triton", "3.7.1"), Distribution("nvidia-nccl-cu13", nccl)] + list(extras)
        return packages, dists

    def test_vllm_passes_and_inactive_marker_is_ignored(self):
        packages, dists = self._vllm()
        result = validate(runtime="vllm", lock=lock(packages), distributions=dists, marker_environment=ENV)
        self.assertEqual("pass", result["status"])
        self.assertEqual([], result["allowed_dependency_mismatches"])

    def test_inventory_rejects_missing_unexpected_and_wrong_version(self):
        packages, dists = self._vllm(extras=(Distribution("surprise", "1"),))
        dists = [d for d in dists if d.name != "triton"]
        dists[0] = Distribution("vllm", "0.28.0")
        codes = {e["code"] for e in validate(runtime="vllm", lock=lock(packages), distributions=dists,
                                               marker_environment=ENV)["errors"]}
        self.assertTrue({"missing_package", "unexpected_package", "version_mismatch"}.issubset(codes))

    def test_bootstrap_allowlist_is_exact_and_cannot_overlap_lock(self):
        packages, dists = self._vllm(extras=(Distribution("pip", "25.1"),))
        self.assertEqual("pass", validate(runtime="vllm", lock=lock(packages), distributions=dists,
                                           bootstrap_allowlist={"pip": "25.1"}, marker_environment=ENV)["status"])
        self.assertEqual("fail", validate(runtime="vllm", lock=lock(packages), distributions=dists,
                                           bootstrap_allowlist={"pip": "25.0"}, marker_environment=ENV)["status"])
        self.assertEqual("fail", validate(runtime="vllm", lock=lock(packages), distributions=dists,
                                           bootstrap_allowlist={"torch": "2.13.0+cu130", "pip": "25.1"}, marker_environment=ENV)["status"])

    def test_vllm_rejects_any_dependency_mismatch(self):
        packages, dists = self._vllm(nccl="2.30.7")
        packages["nvidia-nccl-cu13"] = "2.30.7"
        result = validate(runtime="vllm", lock=lock(packages), distributions=dists, marker_environment=ENV)
        self.assertIn("dependency_mismatch_set", {e["code"] for e in result["errors"]})

    def test_sglang_accepts_exact_single_torch_nccl_exception(self):
        packages = {"sglang": "0.5.20", "sglang-kernel": "0.4.7", "torch": "2.13.0+cu130",
                    "triton": "3.7.1", "nvidia-nccl-cu13": "2.30.7"}
        dists = [Distribution("sglang", "0.5.20", ("torch==2.13.0; extra == 'all'",), ("all",)),
                 Distribution("sglang-kernel", "0.4.7"),
                 Distribution("torch", "2.13.0+cu130", ("nvidia-nccl-cu13==2.29.7 ; sys_platform == 'linux'", "triton==3.7.1")),
                 Distribution("triton", "3.7.1"), Distribution("nvidia-nccl-cu13", "2.30.7")]
        result = validate(runtime="sglang", lock=lock(packages), distributions=dists, marker_environment=ENV)
        self.assertEqual("pass", result["status"])
        self.assertEqual(1, len(result["allowed_dependency_mismatches"]))
        # Removing the mismatch or changing its marker is fail-closed.
        dists[2] = Distribution("torch", "2.13.0+cu130", ("nvidia-nccl-cu13==2.30.7 ; sys_platform == 'linux'", "triton==3.7.1"))
        self.assertEqual("fail", validate(runtime="sglang", lock=lock(packages), distributions=dists, marker_environment=ENV)["status"])

    def test_extras_propagate_to_transitive_dependency(self):
        packages = {"vllm": "0.29.0", "torch": "2.13.0+cu130", "triton": "3.7.1", "nvidia-nccl-cu13": "2.29.7", "child": "1", "leaf": "1"}
        dists = [Distribution("vllm", "0.29.0", ("child[fast]==1",)),
                 Distribution("child", "1", ("leaf==2; extra == 'fast'",), ("fast",)), Distribution("leaf", "1"),
                 Distribution("torch", "2.13.0+cu130", ("nvidia-nccl-cu13==2.29.7; sys_platform == 'linux'", "triton==3.7.1")),
                 Distribution("triton", "3.7.1"), Distribution("nvidia-nccl-cu13", "2.29.7")]
        result = validate(runtime="vllm", lock=lock(packages), distributions=dists, marker_environment=ENV)
        self.assertIn("dependency_mismatch_set", {e["code"] for e in result["errors"]})

    def test_requested_extra_must_be_declared(self):
        packages = {"sglang": "0.5.20", "sglang-kernel": "0.4.7", "torch": "2.13.0+cu130",
                    "triton": "3.7.1", "nvidia-nccl-cu13": "2.30.7"}
        dists = [Distribution("sglang", "0.5.20", ("torch==2.13.0; extra == 'all'",)),
                 Distribution("sglang-kernel", "0.4.7"),
                 Distribution("torch", "2.13.0+cu130", ("nvidia-nccl-cu13==2.29.7; sys_platform == 'linux'", "triton==3.7.1")),
                 Distribution("triton", "3.7.1"), Distribution("nvidia-nccl-cu13", "2.30.7")]
        result = validate(runtime="sglang", lock=lock(packages), distributions=dists, marker_environment=ENV)
        self.assertIn("undeclared_requested_extra", {e["code"] for e in result["errors"]})

    def test_disconnected_package_base_requirement_is_checked(self):
        packages, dists = self._vllm(extras=(Distribution("detached", "1", ("missing==1",)),))
        packages["detached"] = "1"
        result = validate(runtime="vllm", lock=lock(packages), distributions=dists, marker_environment=ENV)
        self.assertIn("active_dependency_missing", {e["code"] for e in result["errors"]})

    def test_extra_fixed_point_does_not_duplicate_mismatch(self):
        packages = {"sglang": "0.5.20", "sglang-kernel": "0.4.7", "torch": "2.13.0+cu130",
                    "triton": "3.7.1", "nvidia-nccl-cu13": "2.30.7", "late": "1"}
        dists = [Distribution("sglang", "0.5.20", ("torch==2.13.0", "late[feature]==1"), ("all",)),
                 Distribution("sglang-kernel", "0.4.7"), Distribution("late", "1", ("torch[debug]==2.13.0; extra == 'feature'",), ("feature",)),
                 Distribution("torch", "2.13.0+cu130", ("nvidia-nccl-cu13==2.29.7; sys_platform == 'linux'", "triton==3.7.1"), ("debug",)),
                 Distribution("triton", "3.7.1"), Distribution("nvidia-nccl-cu13", "2.30.7")]
        result = validate(runtime="sglang", lock=lock(packages), distributions=dists, marker_environment=ENV)
        self.assertEqual("pass", result["status"])
        self.assertEqual(1, len(result["allowed_dependency_mismatches"]))


if __name__ == "__main__":
    unittest.main()
