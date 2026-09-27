from __future__ import annotations

import hashlib
import unittest

from runpod_benchmark.episode1_orchestrator import LifecycleError
from runpod_benchmark.runpod_v2 import Response, RunpodV2Provider
from test_episode1_orchestrator import approved_plan


OWNERSHIP_MARKER = "synthetic-ownership-marker"
NAME = "episode1-candidate-1-run"
KEY_FINGERPRINT = "SHA256:" + "A" * 43


class ScriptedTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, path, *, query=None, json_body=None, deadline_monotonic):
        self.calls.append((method, path, query, json_body, deadline_monotonic))
        if not self.responses:
            raise AssertionError(f"unexpected provider request: {method} {path}")
        return self.responses.pop(0)


def pod(plan, *, name=NAME, status="RUNNING", pod_id="pod-1", public_port=22022):
    value = {
        "id": pod_id,
        "name": name,
        "image": "registry.example/episode1@" + plan["runtime_builds"][0]["derived_image_digest"],
        "gpu": {"id": plan["allocation"]["gpu"], "count": plan["allocation"]["gpu_count"]},
        "cloud": plan["allocation"]["cloud_type"],
        "disk": plan["allocation"]["container_disk_gb"],
        "mounts": ({"persistent": {
            "size": plan["allocation"]["volume_gb"],
            "path": plan["allocation"]["volume_mount_path"],
        }} if plan["allocation"]["volume_gb"] else {}),
        "dataCenterId": plan["allocation"]["data_center_id"],
        "ports": ["22/tcp"],
        "env": {RunpodV2Provider.OWNERSHIP_ENV: hashlib.sha256(OWNERSHIP_MARKER.encode()).hexdigest()},
        "status": status,
    }
    if status == "RUNNING":
        value.update({
            "runtime": {"ports": [{"private": 22, "public": public_port, "type": "tcp", "ip": "192.0.2.4"}]},
            "ssh": {"direct": {"host": "192.0.2.4", "port": public_port}},
        })
    return value


def provider(plan, responses):
    transport = ScriptedTransport(responses)
    journal = []
    adapter = RunpodV2Provider(
        transport,
        approved_image_reference="registry.example/episode1@" + plan["runtime_builds"][0]["derived_image_digest"],
        approved_authorized_key_fingerprint=KEY_FINGERPRINT,
        persist_owned=journal.append,
        monotonic=lambda: 10.0,
        sleep=lambda _: None,
    )
    adapter._test_journal = journal
    adapter._test_cleanup = []
    adapter.bind_cleanup_owner(adapter._test_cleanup.append)
    return adapter, transport


class RunpodV2Tests(unittest.TestCase):
    def test_create_separates_container_and_assigned_public_ssh_ports(self):
        plan = approved_plan()[0]
        adapter, transport = provider(plan, [
            Response(201, pod(plan, status="PENDING")),
            Response(200, pod(plan, public_port=31415)),
        ])
        allocation = adapter.create_allocation(
            unique_name=NAME, ownership_token=OWNERSHIP_MARKER, plan=plan, deadline_monotonic=20.0
        )
        self.assertEqual((22, 31415), (allocation.container_ssh_port, allocation.ssh_public_port))
        create_body = transport.calls[0][3]
        self.assertEqual(["22/tcp"], create_body["ports"])
        self.assertEqual(plan["plan_sha256"], create_body["env"][RunpodV2Provider.PLAN_ENV])
        self.assertEqual(KEY_FINGERPRINT, create_body["env"][RunpodV2Provider.AUTHORIZED_KEY_FINGERPRINT_ENV])
        self.assertNotIn("31415", repr(create_body))

    def test_successful_create_binds_id_before_readiness_failure(self):
        plan = approved_plan()[0]
        adapter, _transport = provider(plan, [
            Response(201, pod(plan, status="PENDING")),
            Response(200, pod(plan, name="mutated-name")),
        ])
        with self.assertRaisesRegex(LifecycleError, "immutable ownership"):
            adapter.create_allocation(
                unique_name=NAME, ownership_token=OWNERSHIP_MARKER, plan=plan, deadline_monotonic=20.0
            )
        self.assertEqual({"pod-1"}, set(adapter._owned))
        self.assertEqual(["pod-1"], [item.private_id for item in adapter._test_journal])
        self.assertEqual(["pod-1"], [item.private_id for item in adapter._test_cleanup])

    def test_recovery_follows_short_page_and_rejects_cursor_loop(self):
        plan = approved_plan()[0]
        page1 = {"pods": [], "pagination": {"nextCursor": "next", "hasNextPage": True}}
        page2 = {"pods": [pod(plan)], "pagination": {"nextCursor": None, "hasNextPage": False}}
        adapter, transport = provider(plan, [Response(200, page1), Response(200, page2), Response(200, pod(plan))])
        adapter.bind_recovery(plan, OWNERSHIP_MARKER)
        recovered = adapter.recover_exact_name(NAME, deadline_monotonic=20.0)
        self.assertEqual(["pod-1"], [item.private_id for item in recovered])
        self.assertEqual("next", transport.calls[1][2]["cursor"])

        loop = {"pods": [], "pagination": {"nextCursor": "same", "hasNextPage": True}}
        adapter, _transport = provider(plan, [Response(200, loop), Response(200, loop)])
        adapter.bind_recovery(plan, OWNERSHIP_MARKER)
        with self.assertRaisesRegex(LifecycleError, "cursor"):
            adapter.recover_exact_name(NAME, deadline_monotonic=20.0)

    def test_direct_ssh_must_match_runtime_port_evidence(self):
        plan = approved_plan()[0]
        invalid = pod(plan)
        invalid["ssh"]["direct"]["port"] = 22023
        adapter, _transport = provider(plan, [Response(201, pod(plan, status="PENDING")), Response(200, invalid)])
        with self.assertRaisesRegex(LifecycleError, "disagree"):
            adapter.create_allocation(
                unique_name=NAME, ownership_token=OWNERSHIP_MARKER, plan=plan, deadline_monotonic=20.0
            )

    def test_deletion_proof_requires_fresh_direct_404_and_full_inventory_absence(self):
        plan = approved_plan()[0]
        adapter, transport = provider(plan, [
            Response(201, pod(plan, status="PENDING")), Response(200, pod(plan)),
            Response(204, None),
            Response(200, {"pods": [], "pagination": {"nextCursor": None, "hasNextPage": False}}),
            Response(404, None),
        ])
        allocation = adapter.create_allocation(
            unique_name=NAME, ownership_token=OWNERSHIP_MARKER, plan=plan, deadline_monotonic=20.0
        )
        self.assertTrue(adapter.delete_allocation(allocation, deadline_monotonic=20.0))
        self.assertTrue(adapter.inventory_absent(allocation, deadline_monotonic=20.0))
        self.assertTrue(adapter.direct_not_found(allocation, deadline_monotonic=20.0))
        self.assertEqual(["POST", "GET", "DELETE", "GET", "GET"], [call[0] for call in transport.calls])


if __name__ == "__main__":
    unittest.main()
