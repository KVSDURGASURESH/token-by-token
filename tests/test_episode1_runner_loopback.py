import contextlib
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from runpod_benchmark.episode1 import CELLS, paired_block_schedule
from runpod_benchmark.episode1_runner import run_fixture_cell
from runpod_benchmark.streaming import StreamingError


def event(value):
    return f"data: {json.dumps(value)}\n\n".encode()


class Handler(BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append(body)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        text = " ".join(["x"] * 128)
        for chunk in (
            event({"choices": [{"delta": {"role": "assistant"}, "finish_reason": None}]}),
            event({"choices": [{"delta": {"content": text}, "finish_reason": "length"}]}),
            event({"choices": [], "usage": {"completion_tokens": 128}}),
            b"data: [DONE]\n\n",
        ):
            self.wfile.write(chunk)
            self.wfile.flush()

    def log_message(self, *_args):
        return


@contextlib.contextmanager
def endpoint():
    Handler.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class Episode1RunnerLoopbackTests(unittest.TestCase):
    def test_runs_frozen_cell_and_sends_runtime_dialect_controls(self):
        cell = CELLS[0]
        specs = [{
            "request_id": f"fixture-{index + 1:02d}",
            "messages": [{"role": "user", "content": " ".join(["p"] * 512)}],
            "quality_task_id": None,
            "gold_json": None,
        } for index in range(cell["requests"])]
        with endpoint() as url:
            records, summary = run_fixture_cell(
                endpoint_url=url,
                model="fixture",
                block=paired_block_schedule()[0],
                cell=cell,
                requests=specs,
                input_token_counter=lambda messages: len(messages[0]["content"].split()),
                output_token_counter=lambda text: len(text.split()),
            )
        self.assertEqual(len(records), 32)
        self.assertEqual(summary["counts"]["transport_success"], 32)
        self.assertEqual(summary["counts"]["slo_qualified"], 32)
        self.assertEqual(len(Handler.seen), 32)
        self.assertNotIn("max_tokens", Handler.seen[0])
        self.assertEqual(Handler.seen[0]["max_completion_tokens"], 128)
        self.assertIs(Handler.seen[0]["ignore_eos"], True)
        self.assertEqual(Handler.seen[0]["top_k"], 0)
        self.assertEqual(Handler.seen[0]["repetition_penalty"], 1)

    def test_prevalidates_every_prompt_before_transport(self):
        calls = []
        cell = CELLS[0]
        specs = [{
            "request_id": f"fixture-{index + 1:02d}",
            "messages": [{"role": "user", "content": "ok"}],
            "quality_task_id": None, "gold_json": None,
        } for index in range(cell["requests"])]
        counts = iter([512] * 31 + [511])
        with self.assertRaisesRegex(ValueError, "exact input"):
            run_fixture_cell(
                endpoint_url="http://127.0.0.1:8000/v1/chat/completions",
                model="fixture", block=paired_block_schedule()[0], cell=cell, requests=specs,
                input_token_counter=lambda _messages: next(counts),
                output_token_counter=lambda _text: 128,
                stream=lambda request: calls.append(request),
            )
        self.assertEqual(calls, [])

    def test_prevalidates_request_identity_before_transport(self):
        calls = []
        cell = {**CELLS[0], "requests": 1}
        specs = [{"request_id": "not allowed/", "messages": [{"role": "user", "content": "ok"}], "quality_task_id": None, "gold_json": None}]
        with self.assertRaisesRegex(ValueError, "request_id"):
            run_fixture_cell(
                endpoint_url="http://127.0.0.1:8000/v1/chat/completions",
                model="fixture", block=paired_block_schedule()[0], cell=cell, requests=specs,
                input_token_counter=lambda _messages: 512,
                output_token_counter=lambda _text: 128,
                stream=lambda request: calls.append(request),
            )
        self.assertEqual(calls, [])

    def test_token_mismatch_fails_attempt_and_stops_new_dispatch(self):
        cell = CELLS[0]
        specs = [{
            "request_id": f"fixture-{index + 1:02d}",
            "messages": [{"role": "user", "content": "ok"}],
            "quality_task_id": None, "gold_json": None,
        } for index in range(cell["requests"])]
        def fake_stream(_request):
            return {
                "text": "x", "output_tokens": 128, "stop_reason": "length",
                "actual_send_ns": 1_000_000, "first_content_ns": 1_000_001,
                "last_content_ns": 1_000_002, "terminal_ns": 1_000_003,
                "content_event_count": 1, "inter_chunk_gaps_ns": [],
            }
        ticks = iter(range(1, 1000))
        records, summary = run_fixture_cell(
            endpoint_url="http://127.0.0.1:8000/v1/chat/completions",
            model="fixture", block=paired_block_schedule()[0], cell=cell, requests=specs,
            input_token_counter=lambda _messages: 512,
            output_token_counter=lambda _text: 127,
            stream=fake_stream, clock=lambda: next(ticks),
        )
        self.assertEqual(records[0]["reason_code"], "token_mismatch")
        self.assertEqual(records[0]["status"], "sse_failure")
        self.assertEqual(summary["counts"]["unsent"], 31)

    def test_provider_evidence_requires_matching_server_prompt_tokens(self):
        cell = {**CELLS[0], "requests": 2, "concurrency": 1}
        specs = [{
            "request_id": f"provider-{index + 1:02d}",
            "messages": [{"role": "user", "content": "ok"}],
            "quality_task_id": None, "gold_json": None,
        } for index in range(2)]
        captured = []

        def fake_stream(request):
            captured.append(request)
            now = time.monotonic_ns()
            return {
                "text": " ".join(["x"] * 128), "input_tokens": 511,
                "output_tokens": 128, "stop_reason": "length",
                "actual_send_ns": now, "first_content_ns": now + 1,
                "last_content_ns": now + 2, "terminal_ns": now + 3,
                "content_event_count": 1, "inter_chunk_gaps_ns": [],
            }

        records, _summary = run_fixture_cell(
            endpoint_url="http://127.0.0.1:8000/v1/chat/completions",
            model="fixture", block=paired_block_schedule()[0], cell=cell, requests=specs,
            input_token_counter=lambda _messages: 512,
            output_token_counter=lambda _text: 128,
            stream=fake_stream, evidence_class="provider_candidate",
        )
        self.assertIs(captured[0]["require_exact_prompt_tokens"], True)
        self.assertEqual(captured[0]["expected_prompt_tokens"], 512)
        self.assertEqual(records[0]["reason_code"], "missing_usage")
        self.assertEqual(records[1]["status"], "unsent")

    def test_natural_request_omits_ignore_eos_and_uses_sglang_top_k(self):
        cell = CELLS[2]
        captured = []
        specs = [{
            "request_id": f"quality-{index + 1:02d}",
            "messages": [{"role": "user", "content": "note"}],
            "quality_task_id": f"quality-{index + 1:02d}",
            "gold_json": json.dumps({"ticket": "LAB-001", "service": "billing", "priority": "high"}),
        } for index in range(cell["requests"])]
        def fake_stream(request):
            captured.append(request)
            now = time.monotonic_ns()
            text = specs[0]["gold_json"]
            return {
                "text": text, "output_tokens": 4, "stop_reason": "eos",
                "actual_send_ns": now, "first_content_ns": now + 1,
                "last_content_ns": now + 2, "terminal_ns": now + 3,
                "content_event_count": 1, "inter_chunk_gaps_ns": [],
            }
        records, _summary = run_fixture_cell(
            endpoint_url="http://127.0.0.1:8000/v1/chat/completions",
            model="fixture", block=paired_block_schedule()[1], cell=cell, requests=specs,
            input_token_counter=lambda _messages: 12,
            output_token_counter=lambda _text: 4,
            stream=fake_stream,
        )
        self.assertEqual(len(records), 24)
        self.assertNotIn("ignore_eos", captured[0])
        self.assertEqual(captured[0]["top_k"], -1)

    def test_refuses_remote_endpoint_before_transport(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            run_fixture_cell(
                endpoint_url="https://example.com/v1/chat/completions",
                model="fixture", block=paired_block_schedule()[0], cell=CELLS[0], requests=[],
                input_token_counter=lambda _messages: 512, output_token_counter=lambda _text: 128,
            )

    def test_partial_failure_does_not_invent_terminal_event(self):
        cell = {**CELLS[0], "requests": 1}
        specs = [{
            "request_id": "partial-01",
            "messages": [{"role": "user", "content": "ok"}],
            "quality_task_id": None,
            "gold_json": None,
        }]
        def fail_after_content(_request):
            now = time.monotonic_ns()
            raise StreamingError(
                "malformed streaming event",
                actual_send_ns=now,
                first_content_ns=now + 1,
                last_content_ns=now + 2,
                content_event_count=1,
                inter_chunk_gaps_ns=(),
            )
        records, _summary = run_fixture_cell(
            endpoint_url="http://127.0.0.1:8000/v1/chat/completions",
            model="fixture", block=paired_block_schedule()[0], cell=cell, requests=specs,
            input_token_counter=lambda _messages: 512,
            output_token_counter=lambda _text: 128,
            stream=fail_after_content,
        )
        self.assertEqual(records[0]["reason_code"], "malformed_sse")
        self.assertIsNotNone(records[0]["f_ns"])
        self.assertIsNotNone(records[0]["l_ns"])
        self.assertIsNone(records[0]["d_ns"])

    def test_dispatch_fact_is_durable_before_unexpected_transport_crash(self):
        cell = {**CELLS[0], "requests": 1, "concurrency": 1}
        lifecycle = []

        def crash(_request):
            raise RuntimeError("simulated client crash after dispatch")

        with self.assertRaisesRegex(RuntimeError, "after dispatch"):
            run_fixture_cell(
                endpoint_url="http://127.0.0.1:8000/v1/chat/completions",
                model="fixture", block=paired_block_schedule()[0], cell=cell,
                requests=[{
                    "request_id": "crash-01", "messages": [{"role": "user", "content": "ok"}],
                    "quality_task_id": None, "gold_json": None,
                }],
                input_token_counter=lambda _messages: 512,
                output_token_counter=lambda _text: 128,
                stream=crash, lifecycle_callback=lifecycle.append,
            )
        self.assertEqual([item["stage"] for item in lifecycle], ["scheduled", "dispatched"])

    def test_tunnel_loss_reason_is_preserved_for_active_and_unsent_attempts(self):
        class TunnelCancellation:
            def __init__(self):
                self.event = threading.Event()

            def is_set(self):
                return self.event.is_set()

            def reason_code(self):
                return "tunnel_lost" if self.event.is_set() else None

        cancellation = TunnelCancellation()
        cell = {**CELLS[0], "requests": 2, "concurrency": 1}
        specs = [{
            "request_id": f"tunnel-{index + 1:02d}",
            "messages": [{"role": "user", "content": "ok"}],
            "quality_task_id": None, "gold_json": None,
        } for index in range(2)]

        def fail(_request):
            cancellation.event.set()
            raise StreamingError("request cancelled", actual_send_ns=time.monotonic_ns())

        records, _summary = run_fixture_cell(
            endpoint_url="http://127.0.0.1:8000/v1/chat/completions",
            model="fixture", block=paired_block_schedule()[0], cell=cell, requests=specs,
            input_token_counter=lambda _messages: 512,
            output_token_counter=lambda _text: 128,
            stream=fail, external_cancel_event=cancellation,
        )
        self.assertEqual([item["reason_code"] for item in records], ["tunnel_lost", "tunnel_lost"])
        self.assertEqual([item["status"] for item in records], ["cancelled", "unsent"])


if __name__ == "__main__":
    unittest.main()
