from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from runpod_benchmark.playground import (
    PlaygroundValidationError,
    run_config,
    sanitized_config,
    validate_config,
    validate_profiles,
    without_raw_text,
)
from runpod_benchmark.streaming import StreamingError


def profiles(url: str = "http://127.0.0.1:18081/v1/chat/completions"):
    return validate_profiles([{
        "id": "local", "label": "Local", "url": url, "runtime_id": "vllm",
        "model": "fixture-model", "supported_optional_fields": ["top_k", "seed", "stop"],
        "context_length": 4096,
    }])


def config(*, repetitions: int = 1):
    return {
        "schema_version": "episode1.quick-test.v1", "mode": "single",
        "prompt": {"system": "Be exact.", "user": "Explain TTFT."},
        "lanes": [{"id": "lane-1", "profile_id": "local", "label": "Local"}],
        "sampling": {"maximum_output_tokens": 32, "temperature": 0, "top_p": 1, "seed": 7},
        "request_timeout_seconds": 5, "repetitions": repetitions, "concurrency": 1,
    }


def test_configuration_is_closed_bounded_and_sanitized():
    checked = validate_config(config(), profiles())
    assert checked["repetitions"] == 1
    safe = sanitized_config(checked)
    assert "Explain TTFT" not in json.dumps(safe)
    assert safe["prompt"]["input_tokens"] is None
    bad = config(); bad["sampling"]["unknown"] = True
    with pytest.raises(PlaygroundValidationError, match="unsupported sampling field"):
        validate_config(bad, profiles())


def test_runner_metrics_and_aggregate_export_do_not_retain_text():
    emitted = []
    def fake_stream(request):
        request["content_callback"]("hello ", 120)
        request["content_callback"]("world", 220)
        return {"text": "hello world", "ttft_ms": 10.0, "e2e_ms": 30.0,
                "output_tokens": 3, "content_span_ms": 100.0,
                "content_event_count": 2, "stop_reason": "stop"}
    result = run_config(config(), profiles(), stream=fake_stream, emit=emitted.append)
    attempt = result["lanes"][0]["attempts"][0]
    assert attempt["generation_tokens_per_second"] == 20.0
    assert attempt["response_text"] == "hello world"
    assert "hello world" not in json.dumps(without_raw_text(result))
    assert [event["text"] for event in emitted if event["type"] == "content"] == ["hello ", "world"]


def test_cancellation_stops_future_repeat_dispatch():
    cancellation = threading.Event(); calls = 0
    def fake_stream(request):
        nonlocal calls
        calls += 1; cancellation.set()
        raise StreamingError("request cancelled")
    result = run_config(config(repetitions=20), profiles(), stream=fake_stream, cancel_event=cancellation)
    assert calls == 1
    assert result["lanes"][0]["attempts"][0]["status"] == "cancelled"


class SSEHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args): pass
    def do_POST(self):
        length = int(self.headers["Content-Length"]); self.rfile.read(length)
        if self.path == "/error":
            self.send_response(500); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        for text in ("one ", "two ", "three"):
            self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {"content": text}, "finish_reason": None}]}).encode() + b"\n\n")
            self.wfile.flush(); time.sleep(0.01)
        final = {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 3, "completion_tokens": 3}}
        self.wfile.write(b"data: " + json.dumps(final).encode() + b"\n\ndata: [DONE]\n\n"); self.wfile.flush()


@pytest.fixture
def sse_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), SSEHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield f"http://127.0.0.1:{server.server_port}"
    finally: server.shutdown(); server.server_close(); thread.join()


def test_local_mock_sse_end_to_end_and_lane_error(sse_server):
    successful = run_config(config(), profiles(sse_server + "/stream"))
    attempt = successful["lanes"][0]["attempts"][0]
    assert attempt["status"] == "completed"
    assert attempt["output_tokens"] == 3
    assert attempt["generation_tokens_per_second"] is not None
    failed = run_config(config(), profiles(sse_server + "/error"))
    assert failed["lanes"][0]["attempts"][0]["status"] == "error"


def test_one_chunk_never_claims_generation_speed():
    def fake_stream(_request):
        return {"text": "x", "ttft_ms": 1.0, "e2e_ms": 2.0, "output_tokens": 1,
                "content_span_ms": 0.0, "content_event_count": 1, "stop_reason": "stop"}
    result = run_config(config(), profiles(), stream=fake_stream)
    assert result["lanes"][0]["attempts"][0]["generation_tokens_per_second"] is None
