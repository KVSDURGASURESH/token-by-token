import copy
import gzip
import io
import json
import struct
import tarfile
import tempfile
import unittest
import zipfile
import sys
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import episode1_build as b


def fake_uv():
    header = bytearray(64)
    header[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into("<H", header, 16, 3)
    struct.pack_into("<H", header, 18, 62)
    return bytes(header) + b"uv 0.12.3\0"


def ar_member(name, raw):
    header = ((name + "/").encode().ljust(16) + b"0".ljust(12) + b"0".ljust(6) +
              b"0".ljust(6) + b"100644".ljust(8) + str(len(raw)).encode().ljust(10) + b"`\n")
    return header + raw + (b"\n" if len(raw) % 2 else b"")


def fake_deb(package, version="1.0", architecture="amd64"):
    control = f"Package: {package}\nVersion: {version}\nArchitecture: {architecture}\n".encode()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        member = tarfile.TarInfo("./control"); member.size = len(control)
        archive.addfile(member, io.BytesIO(control))
    return (b"!<arch>\n" + ar_member("debian-binary", b"2.0\n") +
            ar_member("control.tar.gz", buffer.getvalue()) + ar_member("data.tar.gz", gzip.compress(b"")))


def fixture(root):
    def asset(name, data):
        p = root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
        return {"path": name, "sha256": b.digest(data)}
    (root / ".git/refs/heads").mkdir(parents=True, exist_ok=True)
    (root / ".git/HEAD").write_text("ref: refs/heads/main\n")
    (root / ".git/refs/heads/main").write_text("a" * 40 + "\n")
    manifest = {"schema_version": "episode1.build-input.v1", "platform": "linux/amd64",
                "base_image": b.BASE, "source_commit": "a" * 40,
                "builder": {"docker_version_sha256": "b" * 64, "buildx_version_sha256": "c" * 64,
                            "builder_inspect_sha256": "d" * 64, "sbom_generator": "docker.io/example/scanner@sha256:" + "e" * 64},
                "tooling": {"build_tool_sha256": b.hashfile(Path(b.__file__)),
                            "cpu_smoke_sha256": b.hashfile(Path(b.__file__).with_name("episode1_cpu_smoke.py"))},
                "installer": {"version": "0.12.3", "source_url": "https://github.com/astral-sh/uv/releases/download/0.12.3/uv-x86_64-unknown-linux-gnu.tar.gz", **asset("assets/uv", fake_uv())},
                "system_packages": [], "runtimes": [], "materials": []}
    for name in sorted(b.REQUIRED):
        raw = (b.canonical({"schema_version": "episode1.cpu-startup.v1",
                            "module": "runpod_benchmark.episode1_remote_control",
                            "argv": ["--help"]}) if name == b.CPU_STARTUP_CONTRACT else b"# offline fixture\n")
        manifest["materials"].append(asset(name, raw))
    for name in ("python3.12", "python3.12-venv", "openssh-server", "ca-certificates"):
        manifest["system_packages"].append({"name": name, "version": "1.0", "architecture": "amd64",
                                          "source_url": "https://example.invalid/" + name + ".deb",
                                          **asset("assets/" + name + ".deb", fake_deb(name))})
    for name in ("vllm", "sglang"):
        filename = name + "-1.0-py3-none-any.whl"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr(zipfile.ZipInfo(name + "-1.0.dist-info/METADATA", date_time=(1980, 1, 1, 0, 0, 0)), f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n")
        wheel = {"name": name, "version": "1.0", "filename": filename,
                 "index_url": "https://example.invalid/simple", "source_url": "https://example.invalid/" + filename,
                 **asset("assets/" + filename, buffer.getvalue())}
        lock = asset("locks/" + name + ".lock",
                     ("--index-url https://example.invalid/simple\n--only-binary :all:\n" + name + "==1.0 \\\n    --hash=sha256:" + wheel["sha256"] + "\n").encode())
        manifest["runtimes"].append({"runtime": name, "lock_path": lock["path"], "lock_sha256": lock["sha256"], "wheels": [wheel]})
    return manifest


def oci(root, report=None, *, corrupt=False, duplicate=False, bad_config=False,
        no_attestations=False, no_rootfs=False, bad_diff=False, minimal_report=False,
        wrong_subject=False, bad_material=False):
    manifest = fixture(root)
    manifest_sha = b.digest(b.canonical(manifest))
    inventory = [{k: x[k] for k in ("name", "version", "architecture")} for x in manifest["system_packages"]]
    dependencies = []
    for runtime in manifest["runtimes"]:
        rt = runtime["runtime"]; locked = b.lock_packages((root / runtime["lock_path"]).read_bytes())
        dep = {"schema_version": "episode1.dependency-validation.v1", "status": "pass", "runtime": rt,
               "lock_sha256": runtime["lock_sha256"], "lock_package_count": len(locked), "installed_package_count": len(locked),
               "bootstrap_allowlist": [], "inventory": [{"name": n, "version": v["version"]} for n, v in sorted(locked.items())],
               "active_dependency_checks": 1, "allowed_dependency_mismatches": [], "errors": [],
               "python_version": "3.12.3", "platform": "linux-x86_64", "bootstrap_manifest_sha256": None}
        if rt == "sglang": dep["allowed_dependency_mismatches"] = [{"package": "torch", "dependency": "nvidia-nccl-cu13", "required": "==2.29.7", "marker": 'sys_platform == "linux"', "installed": "2.30.7"}]
        dependencies.append(dep)
    report = report or {"schema_version": "episode1.cpu-smoke.v1", "status": "pass", "manifest_sha256": manifest_sha,
                        "platform": "linux/amd64", "python_version": "3.12.3", "materials": manifest["materials"],
                        "system_inventory": inventory, "dependencies": dependencies, "host_keys_present": False, "gpu_validation": "not_run"}
    if minimal_report: report = {"status": "pass", "manifest_sha256": manifest_sha}
    files = {"opt/episode1/build-evidence/cpu-smoke.json": b.canonical(report),
             "opt/episode1/manifest.json": b.canonical(manifest),
             "opt/episode1/cpu_smoke.py": Path(b.__file__).with_name("episode1_cpu_smoke.py").read_bytes(),
             "usr/local/bin/uv": (root / manifest["installer"]["path"]).read_bytes()}
    for item in manifest["materials"]:
        raw = (root / item["path"]).read_bytes(); files["opt/episode1/materials/" + item["path"]] = raw
        if item["path"].startswith("src/"): files["opt/episode1/" + item["path"][4:]] = raw
        if item["path"].endswith("entrypoint.sh"): files["usr/local/bin/episode1-entrypoint"] = raw
        if item["path"].endswith("control.sh"): files["usr/local/bin/episode1-control"] = raw
    files["opt/episode1/build-spec/Dockerfile"] = b.dockerfile_bytes(manifest, manifest_sha)
    if bad_material: files["usr/local/bin/episode1-entrypoint"] = b"altered"
    for rt in manifest["runtimes"]: files["locks/" + rt["runtime"] + ".lock"] = (root / rt["lock_path"]).read_bytes()
    layer_buffer = io.BytesIO()
    with tarfile.open(fileobj=layer_buffer, mode="w") as layer:
        for name, data in files.items():
            member = tarfile.TarInfo(name); member.size = len(data); layer.addfile(member, io.BytesIO(data))
    blobs = {}
    def blob(data, kind):
        sha = b.digest(data); blobs["blobs/sha256/" + sha] = data
        return {"mediaType": kind, "digest": "sha256:" + sha, "size": len(data)}
    layer = blob(layer_buffer.getvalue(), "application/vnd.oci.image.layer.v1.tar")
    cfg = {"architecture": "arm64" if bad_config else "amd64", "os": "linux",
           "config": {"Entrypoint": ["/usr/local/bin/episode1-entrypoint"],
                      "Env": ["PYTHONNOUSERSITE=1", "HUMMING_COMPILER=nvrtc", "PYTHONPATH=/opt/episode1"]},
           "rootfs": {"type": "layers", "diff_ids": ["sha256:" + ("0" * 64 if bad_diff else b.digest(layer_buffer.getvalue()))]}}
    if no_rootfs: del cfg["rootfs"]
    config = blob(b.canonical(cfg), "application/vnd.oci.image.config.v1+json")
    image = blob(b.canonical({"schemaVersion": 2, "config": config, "layers": [layer]}), "application/vnd.oci.image.manifest.v1+json")
    descriptors = [image]
    if not no_attestations:
        att_layers = []
        for kind, predicate in [("https://spdx.dev/Document", {"SPDXID": "SPDXRef-DOCUMENT", "spdxVersion": "SPDX-2.3", "packages": [{"name": "uv"}]}),
                                ("https://slsa.dev/provenance/v0.2", {"buildType": "https://mobyproject.org/buildkit@v1", "metadata": {"completeness": {"parameters": True}}, "materials": [{"digest": {"sha256": b.BASE.split("sha256:")[1]}}]})]:
            statement = {"_type": "https://in-toto.io/Statement/v1", "subject": [{"name": "_", "digest": {"sha256": "f" * 64 if wrong_subject else image["digest"][7:]}}], "predicateType": kind, "predicate": predicate}
            att_layers.append(blob(b.canonical(statement), "application/vnd.in-toto+json"))
        empty = blob(b"{}", "application/vnd.oci.empty.v1+json")
        descriptors.append(blob(b.canonical({"schemaVersion": 2, "artifactType": "application/vnd.docker.attestation.manifest.v1+json", "subject": image, "config": empty, "layers": att_layers}), "application/vnd.oci.image.manifest.v1+json"))
    index = b.canonical({"schemaVersion": 2, "manifests": descriptors})
    path = root / "image.tar"
    with tarfile.open(path, "w") as out:
        for name, data in {"oci-layout": b.canonical({"imageLayoutVersion": "1.0.0"}), "index.json": index, **blobs}.items():
            if corrupt and name.startswith("blobs/"): data += b"x"; corrupt = False
            member = tarfile.TarInfo(name); member.size = len(data); out.addfile(member, io.BytesIO(data))
        if duplicate:
            member = tarfile.TarInfo("index.json"); member.size = len(index); out.addfile(member, io.BytesIO(index))
    return path, manifest_sha



class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name); self.manifest = fixture(self.root)
        # Reduced locks are explicit test fixtures; production policy remains the
        # two content-addressed complete runtime locks tested separately.
        policy = {}
        for runtime in self.manifest["runtimes"]:
            policy[runtime["runtime"]] = {"lock_sha256": runtime["lock_sha256"], "package_count": 1,
                                           "required": {runtime["runtime"]: "1.0"}}
        self.policy = mock.patch.object(b, "RUNTIME_POLICY", policy)
        self.policy.start(); self.addCleanup(self.policy.stop)
    def tearDown(self): self.tmp.cleanup()
    def test_complete_bytes_and_exact_inventory(self):
        self.assertEqual(b.digest(b.canonical(self.manifest)), b.validate_manifest(self.manifest, self.root))
    def test_tampered_wheel(self):
        (self.root / self.manifest["runtimes"][0]["wheels"][0]["path"]).write_bytes(b"bad")
        with self.assertRaisesRegex(b.BuildError, "material_hash"): b.validate_manifest(self.manifest, self.root)
    def test_wheel_not_in_lock(self):
        self.manifest["runtimes"][0]["wheels"][0]["version"] = "2.0"
        with self.assertRaisesRegex(b.BuildError, "wheel_not_bound"): b.validate_manifest(self.manifest, self.root)
    def test_incomplete_selection(self):
        self.manifest["runtimes"][0]["wheels"] = []
        with self.assertRaisesRegex(b.BuildError, "incomplete_selected"): b.validate_manifest(self.manifest, self.root)
    def test_source_symlink(self):
        path = self.root / self.manifest["materials"][0]["path"]; path.unlink(); path.symlink_to(self.root / "assets/uv")
        with self.assertRaisesRegex(b.BuildError, "symlink"): b.validate_manifest(self.manifest, self.root)
    def test_unsafe_path_and_credentials_origin(self):
        self.manifest["installer"]["path"] = "../uv"
        with self.assertRaisesRegex(b.BuildError, "unsafe_relative"): b.validate_manifest(self.manifest, self.root)
        self.manifest["installer"]["path"] = "assets/uv"
        credential_origin = "https://" + "user:" + "password@" + "example.invalid/uv"
        self.manifest["installer"]["source_url"] = credential_origin
        with self.assertRaisesRegex(b.BuildError, "artifact_origin"): b.validate_manifest(self.manifest, self.root)
    def test_tooling_changes_fail(self):
        self.manifest["tooling"]["cpu_smoke_sha256"] = "f" * 64
        with self.assertRaisesRegex(b.BuildError, "tooling_changed"): b.validate_manifest(self.manifest, self.root)
    def test_prepare_offline_context(self):
        output = self.root / "context"; result = b.prepare(self.manifest, self.root, output)
        text = (output / "Dockerfile").read_text()
        self.assertIn("--require-hashes --no-index", text)
        self.assertIn("--mount=type=bind", text); self.assertNotIn("apt-get", text)
        self.assertEqual(result["manifest_sha256"], b.digest(b.canonical(self.manifest)))
        self.assertEqual(0o700, output.stat().st_mode & 0o777)
        self.assertEqual(0o600, (output / "Dockerfile").stat().st_mode & 0o777)
        with self.assertRaisesRegex(b.BuildError, "already_exists"): b.prepare(self.manifest, self.root, output)
    def test_duplicate_json_rejected(self):
        with self.assertRaises(b.BuildError): b.strict_json(b'{"a":1,"a":2}')
        with self.assertRaises(b.BuildError): b.strict_json(b'{"a":NaN}')
    def test_oci_actual_blobs_report_and_config(self):
        result = b.inspect_oci(*oci(self.root))
        self.assertEqual("not_run", result["gpu_validation"])
        self.assertEqual(result["build_manifest_sha256"], result["cpu_report"]["manifest_sha256"])
    def test_oci_tampered_blob(self):
        with self.assertRaisesRegex(b.BuildError, "blob_hash"): b.inspect_oci(*oci(self.root, corrupt=True))
    def test_oci_unbound_report(self):
        with self.assertRaisesRegex(b.BuildError, "unbound_cpu"): b.inspect_oci(oci(self.root)[0], "b" * 64)
    def test_oci_duplicate_member(self):
        with self.assertRaisesRegex(b.BuildError, "unsafe_oci"): b.inspect_oci(*oci(self.root, duplicate=True))
    def test_oci_wrong_platform(self):
        with self.assertRaisesRegex(b.BuildError, "ambiguous_platform"): b.inspect_oci(*oci(self.root, bad_config=True))

    def test_missing_or_unbound_attestations(self):
        for kwargs in ({"no_attestations": True}, {"wrong_subject": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(b.BuildError): b.inspect_oci(*oci(self.root, **kwargs))
    def test_rootfs_required_and_checked(self):
        for kwargs in ({"no_rootfs": True}, {"bad_diff": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(b.BuildError): b.inspect_oci(*oci(self.root, **kwargs))
    def test_report_cannot_be_two_booleans_or_materials_changed(self):
        for kwargs in ({"minimal_report": True}, {"bad_material": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(b.BuildError): b.inspect_oci(*oci(self.root, **kwargs))
    def test_snapshot_is_independent_of_later_directory_mutation(self):
        context = self.root / "context"; b.prepare(self.manifest, self.root, context)
        snapshot, receipt, manifest, snapshot_sha = b.context_snapshot(context)
        with snapshot:
            (context / "Dockerfile").write_bytes(b"mutated")
            with tarfile.open(fileobj=snapshot) as tar:
                self.assertEqual(b.digest(tar.extractfile("Dockerfile").read()), receipt["files"]["Dockerfile"])
            self.assertRegex(snapshot_sha, r"^[0-9a-f]{64}$")
    def test_context_receipt_is_closed_and_exact(self):
        context = self.root / "context"; b.prepare(self.manifest, self.root, context)
        receipt = json.loads((context / "context-receipt.json").read_bytes())
        receipt["extra"] = True; (context / "context-receipt.json").write_bytes(b.canonical(receipt))
        with self.assertRaises(b.BuildError): b.context_snapshot(context)
    def test_unlisted_deb_rejected(self):
        context = self.root / "context"; b.prepare(self.manifest, self.root, context)
        (context / "payload/debs/evil.deb").write_bytes(b"x")
        with self.assertRaisesRegex(b.BuildError, "membership_changed"): b.context_snapshot(context)
    def test_rehashed_dockerfile_is_not_derived_from_plan(self):
        context = self.root / "context"; b.prepare(self.manifest, self.root, context)
        (context / "Dockerfile").write_bytes(b"RUN evil")
        receipt = json.loads((context / "context-receipt.json").read_bytes())
        receipt["files"]["Dockerfile"] = b.digest(b"RUN evil")
        receipt.pop("artifact_sha256")
        receipt = b.sealed(receipt)
        (context / "context-receipt.json").write_bytes(b.canonical(receipt))
        with self.assertRaisesRegex(b.BuildError, "not_derived"): b.context_snapshot(context)


if __name__ == "__main__": unittest.main()
