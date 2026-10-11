from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from runpod_benchmark.episode1 import (
    CHAT_TEMPLATE_SHA256,
    MODEL_REVISION,
    canonical_json,
    sha256_json,
)
from runpod_benchmark.episode1_orchestrator import Episode1Orchestrator, RuntimeHandle
from runpod_benchmark.episode1_remote import Episode1CellDriver
from test_episode1_orchestrator import (
    Capture,
    Guard,
    Provider,
    Runtime,
    NOW,
    approved_plan,
    run_args,
    telemetry_factory,
)


def _sse(value: object) -> bytes:
    return f"data: {json.dumps(value, separators=(',', ':'))}\n\n".encode()


class _LoopbackServer:
    def __init__(self, responses: dict[str, tuple[str, int, int, str]]) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(inner_self) -> None:
                size = int(inner_self.headers.get("Content-Length", "0"))
                request = json.loads(inner_self.rfile.read(size))
                content = request["messages"][0]["content"]
                text, input_tokens, output_tokens, finish_reason = responses[content]
                chunks = (
                    _sse({"choices": [{"delta": {"role": "assistant"}, "finish_reason": None}]}),
                    _sse({"choices": [{"delta": {"content": text}, "finish_reason": finish_reason}]}),
                    _sse({"choices": [], "usage": {
                        "prompt_tokens": input_tokens,
                        "completion_tokens": output_tokens,
                    }}),
                    b"data: [DONE]\n\n",
                )
                inner_self.send_response(200)
                inner_self.send_header("Content-Type", "text/event-stream")
                inner_self.end_headers()
                for chunk in chunks:
                    inner_self.wfile.write(chunk)
                    inner_self.wfile.flush()

            def log_message(self, *_args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return int(self.server.server_port)

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise RuntimeError("loopback SSE server did not stop")


class _TunnelBinding:
    def __init__(self, port: int) -> None:
        self.local_port = port
        self.cancel_event = threading.Event()
        self.ready = True
        self.process = None

    def start(self, *, deadline_monotonic: float) -> None:
        del deadline_monotonic


def _prompt_evidence() -> tuple[dict, dict[str, list[int]], dict[str, tuple[str, int, int, str]]]:
    token_ids: dict[str, list[int]] = {}
    responses: dict[str, tuple[str, int, int, str]] = {}
    fixed = []
    for count in (512, 2048):
        content = f"fixed-{count}"
        ids = list(range(count))
        token_ids[content] = ids
        responses[content] = ("fixed-output", count, 128, "length")
        fixed.append({
            "target_input_tokens": count,
            "messages": [{"role": "user", "content": content}],
            "token_ids": ids,
            "token_ids_sha256": sha256_json(ids),
        })
    quality = []
    for index in range(24):
        content = f"quality-{index + 1:02d}"
        gold = canonical_json({
            "priority": ("low", "medium", "high")[index // 8],
            "service": ("billing", "storage", "network", "identity")[index % 4],
            "ticket": f"LAB-{index + 1:03d}",
        })
        ids = [index + 1]
        token_ids[content] = ids
        responses[content] = (gold, 1, 1, "stop")
        quality.append({
            "task_id": f"task-{index + 1:02d}",
            "messages": [{"role": "user", "content": content}],
            "gold_json": gold,
            "token_ids": ids,
            "token_ids_sha256": sha256_json(ids),
        })
    evidence = {
        "model_revision": MODEL_REVISION,
        "chat_template_sha256": CHAT_TEMPLATE_SHA256,
        "asset_sha256": {"synthetic": "a" * 64},
        "fixed": fixed,
        "natural_quality": quality,
    }
    return evidence, token_ids, responses


class _RotatingProductionCells:
    def __init__(self) -> None:
        self.evidence, self.token_ids, self.responses = _prompt_evidence()
        self.driver: Episode1CellDriver | None = None
        self.server: _LoopbackServer | None = None
        self.block_id: str | None = None
        self.server_count = 0

    def start(self, *, deadline_monotonic: float) -> None:
        del deadline_monotonic

    def _rotate(self, block_id: str) -> None:
        if self.server is not None:
            self.server.close()
        self.server = _LoopbackServer(self.responses)
        self.server.start()
        self.server_count += 1
        tunnel = _TunnelBinding(self.server.port)

        def ids(messages):
            return self.token_ids[messages[0]["content"]]

        asset_hash = sha256_json(self.evidence["asset_sha256"])
        with patch("runpod_benchmark.episode1_remote.PROMPT_EVIDENCE_SHA256",
                   sha256_json(self.evidence)), patch(
            "runpod_benchmark.episode1_remote.TOKENIZER_ASSET_MANIFEST_SHA256", asset_hash
        ):
            self.driver = Episode1CellDriver(
                endpoint_url=f"http://127.0.0.1:{self.server.port}/v1/chat/completions",
                model="episode1-loopback", prompt_evidence=self.evidence,
                input_token_counter=lambda messages: len(ids(messages)),
                input_token_ids=ids,
                output_token_counter=lambda text: 128 if text == "fixed-output" else 1,
                tunnel=tunnel,
            )
        self.block_id = block_id

    def run_cell(self, **kwargs):
        block_id = str(kwargs["block"]["block_id"])
        if block_id != self.block_id:
            self._rotate(block_id)
        assert self.driver is not None
        return self.driver.run_cell(**kwargs)

    def close(self, *, deadline_monotonic: float) -> None:
        del deadline_monotonic
        if self.server is not None:
            self.server.close()
            self.server = None


class _FreshRuntime(Runtime):
    def start(self, allocation, block, plan, *, deadline_monotonic):
        del allocation, plan, deadline_monotonic
        self.starts += 1
        return RuntimeHandle(
            f"process-{self.starts}", block["runtime"], block["block_id"],
            process_pid=10_000 + self.starts, process_start_ticks=20_000 + self.starts,
        )


class _RecordingCapture(Capture):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[dict] = []
        self.request_lifecycles: list[dict] = []

    def request(self, value):
        self.requests.append(dict(value))

    def request_lifecycle(self, value):
        self.request_lifecycles.append(dict(value))


class Episode1OrchestrationLoopbackTests(unittest.TestCase):
    def test_real_driver_executes_complete_orchestrated_schedule(self):
        plan, receipt, plan_bytes, material, source = approved_plan()
        provider, capture, cells = Provider(), _RecordingCapture(), _RotatingProductionCells()
        runtime = _FreshRuntime()
        runner = Episode1Orchestrator(
            provider=provider, guard=Guard(), runtime=runtime, cells=cells,
            capture=capture, utc_now=lambda: NOW, monitor_poll_seconds=.01,
            telemetry_factory=telemetry_factory,
        )
        result = runner.run(**run_args(plan, receipt, plan_bytes, material, source))
        self.assertEqual(result, {
            "completed_blocks": 6, "startup_retries": 0, "warmups": 72,
            "measured_requests": 528, "deletion_verified": True,
        })
        self.assertEqual(runtime.starts, 6)
        self.assertEqual(cells.server_count, 6)
        self.assertEqual(len(capture.requests), 600)
        self.assertEqual(sum(record["warmup"] for record in capture.requests), 72)
        self.assertEqual(sum(not record["warmup"] for record in capture.requests), 528)
        self.assertTrue(all(record["status"] == "success" for record in capture.requests))
        self.assertTrue(all(
            record["evidence_class"] == "provider_candidate" for record in capture.requests
        ))
        self.assertEqual(len(capture.request_lifecycles), 1_800)
        self.assertEqual(
            {event["stage"] for event in capture.request_lifecycles},
            {"scheduled", "dispatched", "finalized"},
        )
        self.assertTrue(provider.deleted)
        self.assertIn("deletion-verified", capture.events)


if __name__ == "__main__":
    unittest.main()
