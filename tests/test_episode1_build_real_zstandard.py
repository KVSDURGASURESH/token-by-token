import io
import tempfile
import unittest
from pathlib import Path
import tarfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import zstandard

import episode1_build as build


def ar_member(name, raw):
    header = ((name + "/").encode().ljust(16) + b"0".ljust(12) + b"0".ljust(6) +
              b"0".ljust(6) + b"100644".ljust(8) + str(len(raw)).encode().ljust(10) + b"`\n")
    return header + raw + (b"\n" if len(raw) % 2 else b"")


class RealZstandardTest(unittest.TestCase):
    def test_actual_zstandard_control_tar(self):
        control = b"Package: python3.12\nVersion: 3.12.1-1\nArchitecture: amd64\n"
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w:") as archive:
            member = tarfile.TarInfo("./control")
            member.size = len(control)
            archive.addfile(member, io.BytesIO(control))
        compressed = zstandard.ZstdCompressor().compress(tar_buffer.getvalue())
        deb = (b"!<arch>\n" + ar_member("debian-binary", b"2.0\n") +
               ar_member("control.tar.zst", compressed) + ar_member("data.tar.zst", b""))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "python3.12.deb"
            path.write_bytes(deb)
            self.assertEqual(build.deb_control(path), {
                "name": "python3.12", "version": "3.12.1-1", "architecture": "amd64"
            })

    def test_corrupt_zstandard_fails_closed(self):
        deb = (b"!<arch>\n" + ar_member("debian-binary", b"2.0\n") +
               ar_member("control.tar.zst", b"not-zstandard") + ar_member("data.tar.zst", b""))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.deb"
            path.write_bytes(deb)
            with self.assertRaisesRegex(build.BuildError, "invalid_deb_control"):
                build.deb_control(path)


if __name__ == "__main__":
    unittest.main()
