import gzip
import hashlib
import io
import json
import lzma
import os
import struct
import tarfile
import tempfile
import unittest
import sys
from types import SimpleNamespace
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import episode1_build as build
from packaging.utils import parse_wheel_filename


def ar_member(name, raw):
    encoded = (name + "/").encode().ljust(16)
    header = (encoded + b"0".ljust(12) + b"0".ljust(6) + b"0".ljust(6) +
              b"100644".ljust(8) + str(len(raw)).encode().ljust(10) + b"`\n")
    return header + raw + (b"\n" if len(raw) % 2 else b"")


def control_tar(package="python3.12", version="3.12.1-1", architecture="amd64", mode="w:gz"):
    control = f"Package: {package}\nVersion: {version}\nArchitecture: {architecture}\n".encode()
    tar_raw = io.BytesIO()
    with tarfile.open(fileobj=tar_raw, mode=mode) as archive:
        info = tarfile.TarInfo("./control")
        info.size = len(control)
        archive.addfile(info, io.BytesIO(control))
    return tar_raw.getvalue()


def fake_deb(package="python3.12", version="3.12.1-1", architecture="amd64"):
    return (b"!<arch>\n" + ar_member("debian-binary", b"2.0\n") +
            ar_member("control.tar.gz", control_tar(package, version, architecture)) +
            ar_member("data.tar.gz", gzip.compress(b"")))


class InputValidationTest(unittest.TestCase):
    def test_uv_requires_amd64_elf_version_and_official_versioned_origin(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "uv"
            header = bytearray(64)
            header[:7] = b"\x7fELF\x02\x01\x01"
            struct.pack_into("<H", header, 16, 3)
            struct.pack_into("<H", header, 18, 62)
            path.write_bytes(header + b"release uv 0.12.3\0")
            url = "https://github.com/astral-sh/uv/releases/download/0.12.3/uv-x86_64-unknown-linux-gnu.tar.gz"
            build.validate_uv_binary(path, "0.12.3", url)
            bad = bytearray(path.read_bytes()); struct.pack_into("<H", bad, 18, 183); path.write_bytes(bad)
            with self.assertRaisesRegex(build.BuildError, "invalid_uv_elf"):
                build.validate_uv_binary(path, "0.12.3", url)

    def test_deb_metadata_is_read_from_control_archive(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "package.deb"
            path.write_bytes(fake_deb())
            self.assertEqual(build.deb_control(path),
                             {"name": "python3.12", "version": "3.12.1-1", "architecture": "amd64"})
            path.write_bytes(b"not a deb")
            with self.assertRaisesRegex(build.BuildError, "invalid_deb_archive"):
                build.deb_control(path)

    def test_deb_requires_envelope_and_rejects_duplicate_or_oversized_control(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "package.deb"
            control = control_tar()
            path.write_bytes(b"!<arch>\n" + ar_member("debian-binary", b"1.0\n") +
                             ar_member("control.tar.gz", control) + ar_member("data.tar.gz", b""))
            with self.assertRaisesRegex(build.BuildError, "invalid_deb_archive"):
                build.deb_control(path)
            path.write_bytes(b"!<arch>\n" + ar_member("debian-binary", b"2.0\n") +
                             ar_member("control.tar.gz", control))
            with self.assertRaisesRegex(build.BuildError, "invalid_deb_archive"):
                build.deb_control(path)
            path.write_bytes(fake_deb() + ar_member("control.tar.xz", b"x"))
            with self.assertRaisesRegex(build.BuildError, "missing_deb_control"):
                build.deb_control(path)
            path.write_bytes(fake_deb() + ar_member("data.tar.xz", b""))
            with self.assertRaisesRegex(build.BuildError, "invalid_deb_archive"):
                build.deb_control(path)
            oversized = 16 * 1024 * 1024 + 1
            header = (b"control.tar.gz/".ljust(16) + b"0".ljust(12) + b"0".ljust(6) +
                      b"0".ljust(6) + b"100644".ljust(8) + str(oversized).encode().ljust(10) + b"`\n")
            path.write_bytes(b"!<arch>\n" + header)
            with self.assertRaisesRegex(build.BuildError, "oversized_deb_control"):
                build.deb_control(path)
            compressed_bomb = lzma.compress(b"x" * (build.MAX_DEB_CONTROL_DECOMPRESSED + 1))
            path.write_bytes(b"!<arch>\n" + ar_member("debian-binary", b"2.0\n") +
                             ar_member("control.tar.xz", compressed_bomb) +
                             ar_member("data.tar.xz", b""))
            with self.assertRaisesRegex(build.BuildError, "oversized_deb_control"):
                build.deb_control(path)
            compressed_bomb = gzip.compress(b"x" * (build.MAX_DEB_CONTROL_DECOMPRESSED + 1))
            path.write_bytes(b"!<arch>\n" + ar_member("debian-binary", b"2.0\n") +
                             ar_member("control.tar.gz", compressed_bomb) +
                             ar_member("data.tar.gz", b""))
            with self.assertRaisesRegex(build.BuildError, "oversized_deb_control"):
                build.deb_control(path)

    def test_control_tar_zst_requires_pinned_python_decoder_and_bounds_output(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "package.deb"
            path.write_bytes(b"!<arch>\n" + ar_member("debian-binary", b"2.0\n") +
                             ar_member("control.tar.zst", b"fixture-zstd") + ar_member("data.tar.zst", b""))
            class Reader(io.BytesIO):
                pass
            class Decompressor:
                def __init__(self, *, max_window_size):
                    self.max_window_size = max_window_size
                def stream_reader(self, source):
                    self.source = source.read()
                    return Reader(control_tar(mode="w:"))
            fake_module = type("Zstandard", (), {"ZstdDecompressor": Decompressor})
            with mock.patch.object(build, "trusted_zstandard", return_value=fake_module):
                self.assertEqual(build.deb_control(path)["name"], "python3.12")
            with mock.patch.object(build, "trusted_zstandard",
                                   side_effect=build.BuildError("zstandard_dependency_unavailable")):
                with self.assertRaisesRegex(build.BuildError, "zstandard_dependency_unavailable"):
                    build.deb_control(path)
            class OversizedDecompressor(Decompressor):
                def stream_reader(self, source):
                    return Reader(b"x" * (build.MAX_DEB_CONTROL_DECOMPRESSED + 1))
            oversized_module = type("Zstandard", (), {"ZstdDecompressor": OversizedDecompressor})
            with mock.patch.object(build, "trusted_zstandard", return_value=oversized_module):
                with self.assertRaisesRegex(build.BuildError, "oversized_deb_control"):
                    build.deb_control(path)

    def test_zstandard_loader_requires_pinned_venv_distribution_and_module(self):
        root = Path(sys.prefix) / "lib/python3.12/site-packages"
        distribution = SimpleNamespace(version=build.ZSTANDARD_VERSION,
                                       locate_file=lambda _: root)
        spec = SimpleNamespace(origin=str(root / "zstandard/__init__.py"))
        module = SimpleNamespace(__version__=build.ZSTANDARD_VERSION)
        with mock.patch.object(build.importlib.metadata, "distribution", return_value=distribution), \
             mock.patch.object(build.importlib.util, "find_spec", return_value=spec), \
             mock.patch.object(build.importlib, "import_module", return_value=module):
            self.assertIs(build.trusted_zstandard(), module)
        distribution.version = "0.24.0"
        with mock.patch.object(build.importlib.metadata, "distribution", return_value=distribution):
            with self.assertRaisesRegex(build.BuildError, "zstandard_dependency_unavailable"):
                build.trusted_zstandard()
        distribution.version = build.ZSTANDARD_VERSION
        distribution.locate_file = lambda _: Path(self.temp_dir.name)
        with mock.patch.object(build.importlib.metadata, "distribution", return_value=distribution):
            with self.assertRaisesRegex(build.BuildError, "untrusted_zstandard_dependency"):
                build.trusted_zstandard()

    def test_retained_lock_hash_count_and_roots(self):
        lock_root = ROOT / "runtime" / "episode1" / "locks"
        for runtime, filename in (("vllm", "vllm.lock"), ("sglang", "sglang-wheel.lock")):
            path = lock_root / filename
            raw = path.read_bytes()
            locked = build.lock_packages(raw)
            build.validate_runtime_lock(runtime, raw, locked)
        changed = Path(self.temp_dir.name) / "changed.lock"
        changed.write_bytes((lock_root / "vllm.lock").read_bytes() + b"\n# changed\n")
        with self.assertRaisesRegex(build.BuildError, "unexpected_runtime_lock"):
            raw = changed.read_bytes()
            build.validate_runtime_lock("vllm", raw, build.lock_packages(raw))

    def test_wheel_tags_match_cpython312_manylinux_x86_64(self):
        good = parse_wheel_filename("demo-1.0-cp312-cp312-manylinux_2_34_x86_64.whl")[3]
        native = parse_wheel_filename("demo-1.0-cp312-cp312-manylinux_2_39_x86_64.whl")[3]
        abi3 = parse_wheel_filename("demo-1.0-cp39-abi3-manylinux2014_x86_64.whl")[3]
        universal = parse_wheel_filename("demo-1.0-py3-none-any.whl")[3]
        bad_python = parse_wheel_filename("demo-1.0-cp313-cp313-manylinux_2_34_x86_64.whl")[3]
        bad_arch = parse_wheel_filename("demo-1.0-cp312-cp312-manylinux_2_34_aarch64.whl")[3]
        too_new = parse_wheel_filename("demo-1.0-cp312-cp312-manylinux_2_40_x86_64.whl")[3]
        self.assertTrue(all(build.compatible_target_wheel(x) for x in (good, native, abi3, universal)))
        self.assertFalse(build.compatible_target_wheel(bad_python))
        self.assertFalse(build.compatible_target_wheel(bad_arch))
        self.assertFalse(build.compatible_target_wheel(too_new))

    def test_git_head_loose_and_prepare_boundary_comparison(self):
        root = Path(self.temp_dir.name) / "checkout"
        (root / ".git/refs/heads").mkdir(parents=True)
        commit = "a" * 40
        (root / ".git/HEAD").write_text("ref: refs/heads/main\n")
        (root / ".git/refs/heads/main").write_text(commit + "\n")
        self.assertEqual(build.git_head(root), commit)

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
