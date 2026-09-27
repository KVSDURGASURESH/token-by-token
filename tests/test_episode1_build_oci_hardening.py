import io
import json
import tarfile
import tempfile
import unittest
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import episode1_build as b
import test_episode1_build as fixtures

MT_LAYER = "application/vnd.oci.image.layer.v1.tar"
MT_CONFIG = "application/vnd.oci.image.config.v1+json"
MT_MANIFEST = "application/vnd.oci.image.manifest.v1+json"


def descriptor(raw, media):
    return {"mediaType": media, "digest": "sha256:" + b.digest(raw), "size": len(raw)}


def layer(entries):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as archive:
        for name, kind, data in entries:
            member = tarfile.TarInfo(name)
            if kind == "file":
                member.size = len(data); archive.addfile(member, io.BytesIO(data))
            elif kind == "symlink":
                member.type = tarfile.SYMTYPE; member.linkname = data; archive.addfile(member)
            elif kind == "directory":
                member.type = tarfile.DIRTYPE; archive.addfile(member)
            else:
                raise AssertionError(kind)
    return out.getvalue()


def pax_layer(name, data=b"payload", headers=None):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w", format=tarfile.PAX_FORMAT) as archive:
        member = tarfile.TarInfo(name); member.size = len(data)
        member.pax_headers = headers or {}
        archive.addfile(member, io.BytesIO(data))
    return out.getvalue()


def mutate(base, output, extra_layers=(), *, extra_first=False, completeness=None):
    with tarfile.open(base) as archive:
        blobs = {b.tar_name(m.name, directory=m.isdir(), allow_root=True): archive.extractfile(m).read()
                 for m in archive if m.isfile()}
    index = json.loads(blobs["index.json"])
    old_image = index["manifests"][0]
    image = json.loads(blobs["blobs/sha256/" + old_image["digest"][7:]])
    config = json.loads(blobs["blobs/sha256/" + image["config"]["digest"][7:]])
    additions = []
    for raw in extra_layers:
        item = descriptor(raw, MT_LAYER); blobs["blobs/sha256/" + item["digest"][7:]] = raw; additions.append(item)
    image["layers"] = additions + image["layers"] if extra_first else image["layers"] + additions
    diffs = ["sha256:" + b.digest(raw) for raw in extra_layers]
    config["rootfs"]["diff_ids"] = diffs + config["rootfs"]["diff_ids"] if extra_first else config["rootfs"]["diff_ids"] + diffs
    config_raw = b.canonical(config); image["config"] = descriptor(config_raw, MT_CONFIG)
    blobs["blobs/sha256/" + image["config"]["digest"][7:]] = config_raw
    image_raw = b.canonical(image); image_desc = descriptor(image_raw, MT_MANIFEST)
    blobs["blobs/sha256/" + image_desc["digest"][7:]] = image_raw
    att = json.loads(blobs["blobs/sha256/" + index["manifests"][1]["digest"][7:]])
    att["subject"] = image_desc; new_att_layers = []
    for old in att["layers"]:
        statement = json.loads(blobs["blobs/sha256/" + old["digest"][7:]])
        for subject in statement["subject"]: subject["digest"]["sha256"] = image_desc["digest"][7:]
        if completeness is not None and statement["predicateType"].endswith("/v0.2"):
            statement["predicate"]["metadata"]["completeness"]["parameters"] = completeness
        raw = b.canonical(statement); item = descriptor(raw, "application/vnd.in-toto+json")
        blobs["blobs/sha256/" + item["digest"][7:]] = raw; new_att_layers.append(item)
    att["layers"] = new_att_layers
    att_raw = b.canonical(att); att_desc = descriptor(att_raw, MT_MANIFEST)
    blobs["blobs/sha256/" + att_desc["digest"][7:]] = att_raw
    blobs["index.json"] = b.canonical({"schemaVersion": 2, "manifests": [image_desc, att_desc]})
    with tarfile.open(output, "w") as archive:
        for name, raw in blobs.items():
            member = tarfile.TarInfo(name); member.size = len(raw); archive.addfile(member, io.BytesIO(raw))


class OciHardeningTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        manifest = fixtures.fixture(self.root); self.manifest = manifest
        policy = {r["runtime"]: {"lock_sha256": r["lock_sha256"], "package_count": 1,
                                  "required": {r["runtime"]: "1.0"}} for r in manifest["runtimes"]}
        self.policy = mock.patch.object(b, "RUNTIME_POLICY", policy); self.policy.start()
        self.base, self.manifest_sha = fixtures.oci(self.root)
    def tearDown(self):
        self.policy.stop(); self.temp.cleanup()
    def inspect_mutation(self, layers=(), **kwargs):
        path = self.root / ("mutated-%d.tar" % len(list(self.root.glob("mutated-*.tar"))))
        mutate(self.base, path, layers, **kwargs); return b.inspect_oci(path, self.manifest_sha)
    def test_non_directory_ancestor_and_internal_alias_rejected(self):
        with self.assertRaisesRegex(b.BuildError, "non_directory_image_ancestor"):
            self.inspect_mutation([layer([("opt/episode1", "symlink", "/tmp/elsewhere")])], extra_first=True)
        with self.assertRaisesRegex(b.BuildError, "unsafe_archive_path"):
            self.inspect_mutation([layer([("usr/local/bin/./uv", "file", b"evil")])])
    def test_normal_tar_root_and_directory_spelling_are_canonical(self):
        result = self.inspect_mutation([layer([("./var/lib/example/", "directory", b"")])])
        self.assertRegex(result["final_filesystem_sha256"], r"^[0-9a-f]{64}$")
    def test_required_file_cannot_be_retyped_as_directory(self):
        with self.assertRaisesRegex(b.BuildError, "final_image_material_mismatch"):
            self.inspect_mutation([layer([("usr/local/bin/uv/", "directory", b"")])])
    def test_negative_final_facts_are_recomputed(self):
        paths = ["etc/ssh/ssh_host_rsa_key", "root/.ssh/authorized_keys", "root/.cache/uv/wheel"]
        for path in paths:
            with self.subTest(path=path), self.assertRaisesRegex(b.BuildError, "forbidden_final"):
                self.inspect_mutation([layer([(path, "file", b"secret")])])
    def test_whiteout_removes_lower_forbidden_file(self):
        result = self.inspect_mutation([
            layer([("etc/ssh/ssh_host_rsa_key", "file", b"secret")]),
            layer([("etc/ssh/.wh.ssh_host_rsa_key", "file", b"")]),
        ])
        self.assertEqual("unbound_cpu_build_inspection", result["classification"])
    def test_opaque_removes_only_lower_tree_and_preserves_same_layer_nodes(self):
        tree = {"a": {"type": "directory"}, "a/old": {"type": "file", "sha256": "1" * 64},
                "elsewhere": {"type": "file", "sha256": "2" * 64}}
        new = {"type": "file", "sha256": "3" * 64, "mode": 0o600, "uid": 0, "gid": 0}
        b._apply_layer(tree, [("a/new", new)], [], ["a"])
        self.assertNotIn("a/old", tree); self.assertIs(tree["a/new"], new); self.assertIn("elsewhere", tree)
        b._apply_layer(tree, [("fresh", new)], [], [""])
        self.assertEqual({"fresh"}, set(tree))
    def test_completeness_requires_exact_boolean_true(self):
        with self.assertRaisesRegex(b.BuildError, "incomplete_build_provenance"):
            self.inspect_mutation(completeness="yes")
    def test_resource_bounds_fail_closed(self):
        with mock.patch.dict(b.RESOURCE_BOUNDS, {"oci_archive_bytes": 1}):
            with self.assertRaisesRegex(b.BuildError, "resource_bound_exceeded"):
                b.inspect_oci(self.base, self.manifest_sha)
        with mock.patch.dict(b.RESOURCE_BOUNDS, {"oci_layer_uncompressed_bytes": 1}):
            with self.assertRaisesRegex(b.BuildError, "resource_bound_exceeded"):
                b.inspect_oci(self.base, self.manifest_sha)
        with mock.patch.dict(b.RESOURCE_BOUNDS, {"context_member_bytes": 1}):
            with self.assertRaisesRegex(b.BuildError, "resource_bound_exceeded"):
                b.check_budget("context", 1, 2, 2)

    def test_retained_evidence_bound_is_checked_before_extract(self):
        original = tarfile.TarFile.extractfile
        def guarded(archive, member):
            if getattr(member, "name", "").lstrip("./") in {
                    "opt/episode1/manifest.json", "opt/episode1/build-evidence/cpu-smoke.json",
                    "locks/vllm.lock", "locks/sglang.lock"} and member.size > 1:
                raise AssertionError("oversized retained evidence was opened")
            return original(archive, member)
        with mock.patch.dict(b.RESOURCE_BOUNDS, {"oci_evidence_bytes": 1}), \
                mock.patch.object(tarfile.TarFile, "extractfile", guarded):
            with self.assertRaisesRegex(b.BuildError, "oversized_image_evidence"):
                b.inspect_oci(self.base, self.manifest_sha)

    def test_pax_extension_is_bounded_before_internal_read(self):
        raw = pax_layer("var/lib/large-pax", headers={"comment": "x" * 512})
        with mock.patch.dict(b.RESOURCE_BOUNDS, {"oci_tar_extension_bytes": 64}):
            with self.assertRaisesRegex(b.BuildError, "tar_extension_metadata_too_large"):
                self.inspect_mutation([raw])

    def test_chained_small_pax_extensions_have_aggregate_bound(self):
        raw = pax_layer("var/lib/chained-pax", headers={"comment": "small"})
        # The fixture's first two blocks are its PAX header and padded PAX data.
        chained = raw[:1024] * 2 + raw[1024:]
        with mock.patch.dict(b.RESOURCE_BOUNDS, {"oci_tar_extensions": 1}):
            with self.assertRaisesRegex(b.BuildError, "tar_extension_metadata_too_large"):
                self.inspect_mutation([chained])

    def test_root_tar_entry_counts_toward_outer_budget(self):
        rooted = self.root / "rooted.tar"
        with tarfile.open(self.base) as source, tarfile.open(rooted, "w") as target:
            root = tarfile.TarInfo("./"); root.type = tarfile.DIRTYPE; target.addfile(root)
            for member in source:
                target.addfile(member, source.extractfile(member) if member.isfile() else None)
        with mock.patch.dict(b.RESOURCE_BOUNDS, {"oci_outer_members": 0}):
            with self.assertRaisesRegex(b.BuildError, "resource_bound_exceeded"):
                b.inspect_oci(rooted, self.manifest_sha)

    def test_xattrs_are_bound_and_unmodeled_acl_is_rejected(self):
        plain = self.inspect_mutation([pax_layer("var/lib/metadata")])
        xattr = self.inspect_mutation([pax_layer(
            "var/lib/metadata", headers={"SCHILY.xattr.user.example": "bound"})])
        self.assertNotEqual(plain["final_filesystem_sha256"], xattr["final_filesystem_sha256"])
        with self.assertRaisesRegex(b.BuildError, "unsupported_image_node_metadata"):
            self.inspect_mutation([pax_layer(
                "var/lib/metadata", headers={"SCHILY.acl.access": "user::rw-"})])

    def test_prepare_checks_budget_before_creating_context(self):
        context = self.root / "bounded-context"
        with mock.patch.dict(b.RESOURCE_BOUNDS, {"context_member_bytes": 1}):
            with self.assertRaisesRegex(b.BuildError, "resource_bound_exceeded"):
                b.prepare(self.manifest, self.root, context)
        self.assertFalse(context.exists())

    def test_copy_exact_rejects_growth_and_truncation(self):
        for raw, declared in ((b"ab", 1), (b"", 1)):
            with self.subTest(raw=raw, declared=declared), \
                    self.assertRaisesRegex(b.BuildError, "material_changed_while_copying"):
                b.copy_exact(io.BytesIO(raw), io.BytesIO(), declared)

    def test_snapshot_rechecks_current_file_size(self):
        context = self.root / "snapshot-context"
        b.prepare(self.manifest, self.root, context)
        payload = context / "payload/uv"
        with payload.open("r+b") as stream:
            stream.truncate(b.RESOURCE_BOUNDS["context_member_bytes"] + 1)
        with self.assertRaisesRegex(b.BuildError, "resource_bound_exceeded"):
            b.context_snapshot(context)
    def test_sealed_local_receipt_binds_archive_and_invocation(self):
        manifest = fixtures.fixture(self.root)
        body = {"schema_version": "episode1.build-receipt.v1", "manifest_sha256": self.manifest_sha,
                "context_receipt_sha256": "1" * 64, "context_snapshot_sha256": "2" * 64,
                "oci_archive_sha256": b.hashfile(self.base), "metadata_sha256": "3" * 64,
                "actual_argv_sha256": "4" * 64,
                "invocation": {**b.BUILD_INVOCATION, "sbom_generator": manifest["builder"]["sbom_generator"]},
                "builder_identity_sha256": {k: manifest["builder"][k] for k in
                    ("docker_version_sha256", "buildx_version_sha256", "builder_inspect_sha256")},
                "resource_bounds": b.RESOURCE_BOUNDS, "trust": "unsigned_local_observation"}
        receipt = b.sealed(body)
        result = b.inspect_oci(self.base, self.manifest_sha, receipt)
        self.assertEqual(receipt["artifact_sha256"], result["local_build_receipt_sha256"])
        receipt["oci_archive_sha256"] = "9" * 64
        with self.assertRaisesRegex(b.BuildError, "receipt_hash_mismatch"):
            b.inspect_oci(self.base, self.manifest_sha, receipt)


if __name__ == "__main__": unittest.main()
