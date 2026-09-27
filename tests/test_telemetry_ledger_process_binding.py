import unittest

from runpod_benchmark import episode1_capture as capture


def ledger_for(process_start_sha256: str):
    return [
        ({"event": "block-start"}, {
            "block_id": "block-1", "runtime": "vllm-0.29.0",
            "process_start_identity_sha256": process_start_sha256,
        }),
        ({"event": "block-stop"}, {"block_id": "block-1"}),
    ]


class TelemetryLedgerProcessBindingTests(unittest.TestCase):
    def test_matching_pid_start_is_accepted(self):
        identity=(4242,8080)
        digest=capture.sha(capture.canonical({"pid":identity[0],"start_ticks":identity[1]}))
        capture._verify_telemetry_ledger_processes(
            {("block-1","vllm-0.29.0"):identity},ledger_for(digest))

    def test_different_pid_start_is_rejected_even_when_each_artifact_is_valid(self):
        ledger_digest=capture.sha(capture.canonical({"pid":4242,"start_ticks":8080}))
        with self.assertRaisesRegex(capture.IntegrityError,"differs from successful block ledger"):
            capture._verify_telemetry_ledger_processes(
                {("block-1","vllm-0.29.0"):(5252,9090)},ledger_for(ledger_digest))

    def test_pre_readiness_retry_uses_only_successful_process(self):
        successful=capture.sha(capture.canonical({"pid":333,"start_ticks":444}))
        ledger=[
            # Real orchestrator order: block-start is absent when readiness did
            # not succeed, but cleanup evidence for that failed attempt remains.
            ({"event":"startup-failed"},{"block_id":"block-1"}),
            ({"event":"failed-start-cleanup"},{"block_id":"block-1"}),
            ({"event":"block-start"},{"block_id":"block-1","runtime":"vllm-0.29.0",
                "process_start_identity_sha256":successful}),
            ({"event":"block-stop"},{"block_id":"block-1"}),
        ]
        capture._verify_telemetry_ledger_processes(
            {("block-1","vllm-0.29.0"):(333,444)},ledger)
        with self.assertRaises(capture.IntegrityError):
            capture._verify_telemetry_ledger_processes(
                {("block-1","vllm-0.29.0"):(111,222)},ledger)


if __name__ == "__main__":
    unittest.main()
