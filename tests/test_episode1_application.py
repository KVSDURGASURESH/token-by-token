from __future__ import annotations

import unittest

from runpod_benchmark.episode1_application import RunContext
from test_episode1_orchestrator import NOW, approved_plan, run_args


class RunContextTests(unittest.TestCase):
    def _context(self) -> tuple[RunContext, dict]:
        plan, receipt, plan_bytes, material, source = approved_plan()
        arguments = run_args(plan, receipt, plan_bytes, material, source)
        context = RunContext.create(
            plan=arguments["plan"],
            authorization_receipt=arguments["authorization_receipt"],
            plan_file_bytes=arguments["plan_file_bytes"],
            material_file_bytes=arguments["material_file_bytes"],
            material_files=arguments["material_files"],
            observed_source_commit=arguments["observed_source_commit"],
            authorization_source_bytes=arguments["authorization_source_bytes"],
            unique_name=arguments["unique_name"],
            telemetry_series=("native-queue", "system-rss"),
            monotonic=lambda: 100.0,
            utc_now=lambda: NOW,
            run_id="run-context-test",
            clock_domain="integration-clock",
            boot_id="integration-boot",
        )
        return context, arguments

    def test_context_binds_exact_inputs_and_deadlines(self):
        context, arguments = self._context()
        contract = context.capture_contract()
        self.assertEqual(contract.plan_sha256, arguments["plan"]["plan_sha256"])
        self.assertEqual(contract.original_t0_monotonic_ns, 100_000_000_000)
        self.assertEqual(
            contract.hard_deadline_monotonic_ns - contract.original_t0_monotonic_ns,
            int(arguments["plan"]["budget"]["maximum_lifetime_seconds"] * 1_000_000_000),
        )
        self.assertEqual(sum(contract.request_counts.values()), 600)
        self.assertEqual(contract.telemetry_series, ("native-queue", "system-rss"))

    def test_plan_and_receipt_views_are_detached(self):
        context, _arguments = self._context()
        plan = context.plan
        receipt = context.authorization_receipt
        plan["candidate_id"] = "changed"
        receipt["plan_sha256"] = "0" * 64
        self.assertEqual(context.plan["candidate_id"], "candidate-1")
        self.assertNotEqual(context.authorization_receipt["plan_sha256"], "0" * 64)

    def test_rejects_name_not_bound_to_candidate_before_execution(self):
        plan, receipt, plan_bytes, material, source = approved_plan()
        arguments = run_args(plan, receipt, plan_bytes, material, source)
        arguments["unique_name"] = "episode1-wrong-run"
        with self.assertRaisesRegex(ValueError, "not bound"):
            RunContext.create(
                plan=arguments["plan"],
                authorization_receipt=arguments["authorization_receipt"],
                plan_file_bytes=arguments["plan_file_bytes"],
                material_file_bytes=arguments["material_file_bytes"],
                material_files=arguments["material_files"],
                observed_source_commit=arguments["observed_source_commit"],
                authorization_source_bytes=arguments["authorization_source_bytes"],
                unique_name=arguments["unique_name"],
                telemetry_series=("native-queue",),
                monotonic=lambda: 100.0,
                utc_now=lambda: NOW,
            )

    def test_accepts_platform_clock_domain_identifiers(self):
        context, arguments = self._context()
        for clock_domain in (
            "darwin-kern-boottime:123:456:monotonic",
            "linux-boot-id:12345678-1234-1234-1234-123456789abc:monotonic",
        ):
            rebuilt = RunContext.create(
                plan=arguments["plan"],
                authorization_receipt=arguments["authorization_receipt"],
                plan_file_bytes=arguments["plan_file_bytes"],
                material_file_bytes=arguments["material_file_bytes"],
                material_files=arguments["material_files"],
                observed_source_commit=arguments["observed_source_commit"],
                authorization_source_bytes=arguments["authorization_source_bytes"],
                unique_name=arguments["unique_name"],
                telemetry_series=context.telemetry_series,
                monotonic=lambda: 100.0,
                utc_now=lambda: NOW,
                clock_domain=clock_domain,
            )
            self.assertEqual(rebuilt.clock_domain, clock_domain)


if __name__ == "__main__":
    unittest.main()
