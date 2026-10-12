import contextlib
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from runpod_benchmark.streaming import StreamingError, stream_chat


def event(value):
    return f"data: {json.dumps(value, ensure_ascii=False)}\n\n".encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    chunks = []
    status = 200

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(size)
        self.send_response(self.status)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for chunk in self.chunks:
            self.wfile.write(chunk)
            self.wfile.flush()
            time.sleep(.002)

    def log_message(self, *_args):
        return


@contextlib.contextmanager
def endpoint(chunks, status=200):
    handler = type("FixtureHandler", (Handler,), {"chunks": chunks, "status": status})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(url):
    return {
        "url": url, "runtime_id": "vllm",
        "runtime_capabilities": {
            "streaming_sse": True, "done_event": True,
            "streamed_usage": True, "exact_completion_tokens": True,
        },
        "model": "fixture", "messages": [{"role": "user", "content": "fixture"}],
        "maximum_output_tokens": 128, "temperature": 0, "top_p": 1, "seed": 20260923,
        "timeout_seconds": 2, "max_response_bytes": 65536,
    }


class Episode1SSELoopbackTests(unittest.TestCase):
    def test_role_empty_split_utf8_multitoken_and_usage_after_content(self):
        prefix = [
            event({"choices": [{"delta": {"role": "assistant"}, "finish_reason": None}]}),
            event({"choices": [{"delta": {}, "finish_reason": None}]}),
            event({"choices": [{"delta": {"content": ""}, "finish_reason": None}]}),
            event({"choices": [{"delta": {"content": "café"}, "finish_reason": None}]}),
            event({"choices": [{"delta": {"content": " done"}, "finish_reason": "length"}]}),
            event({"choices": [], "usage": {"completion_tokens": 4}}),
            b"data: [DONE]\n\n",
        ]
        payload = b"".join(prefix)
        marker = payload.index("é".encode("utf-8")) + 1
        chunks = [payload[:marker], payload[marker:marker + 1], payload[marker + 1:]]
        with endpoint(chunks) as url:
            result = stream_chat(request(url))
        self.assertEqual(result["text"], "café done")
        self.assertEqual(result["output_tokens"], 4)
        self.assertEqual(result["content_event_count"], 2)
        self.assertLessEqual(result["first_content_ns"], result["last_content_ns"])
        self.assertLessEqual(result["last_content_ns"], result["terminal_ns"])

    def test_missing_usage_fails_closed(self):
        chunks = [event({"choices": [{"delta": {"content": "x"}, "finish_reason": "stop"}]}), b"data: [DONE]\n\n"]
        with endpoint(chunks) as url:
            with self.assertRaisesRegex(StreamingError, "streamed usage"):
                stream_chat(request(url))

    def test_exact_prompt_tokens_are_returned_when_required(self):
        chunks = [
            event({"choices": [{"delta": {"content": "x"}, "finish_reason": "stop"}]}),
            event({"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 1}}),
            b"data: [DONE]\n\n",
        ]
        with endpoint(chunks) as url:
            checked = request(url)
            checked["require_exact_prompt_tokens"] = True
            checked["expected_prompt_tokens"] = 7
            result = stream_chat(checked)
        self.assertEqual(result["input_tokens"], 7)

    def test_missing_mismatched_and_conflicting_prompt_usage_fail_closed(self):
        cases = (
            (
                [event({"choices": [{"delta": {"content": "x"}, "finish_reason": "stop"}]}),
                 event({"choices": [], "usage": {"completion_tokens": 1}}), b"data: [DONE]\n\n"],
                "prompt tokens is required",
            ),
            (
                [event({"choices": [{"delta": {"content": "x"}, "finish_reason": "stop"}]}),
                 event({"choices": [], "usage": {"prompt_tokens": 8, "completion_tokens": 1}}), b"data: [DONE]\n\n"],
                "does not match",
            ),
            (
                [event({"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 1}}),
                 event({"choices": [{"delta": {"content": "x"}, "finish_reason": "stop"}]}),
                 event({"choices": [], "usage": {"prompt_tokens": 8, "completion_tokens": 1}}), b"data: [DONE]\n\n"],
                "conflicting prompt",
            ),
        )
        for chunks, message in cases:
            with self.subTest(message=message), endpoint(chunks) as url:
                checked = request(url)
                checked["require_exact_prompt_tokens"] = True
                checked["expected_prompt_tokens"] = 7
                with self.assertRaisesRegex(StreamingError, message):
                    stream_chat(checked)

    def test_completion_token_field_selector_must_be_boolean(self):
        invalid = request("http://127.0.0.1:1/v1/chat/completions")
        invalid["use_max_completion_tokens"] = "true"
        with self.assertRaisesRegex(StreamingError, "must be boolean"):
            stream_chat(invalid)

    def test_partial_content_timing_survives_malformed_terminal_event(self):
        chunks = [
            event({"choices": [{"delta": {"content": "partial"}, "finish_reason": None}]}),
            b"data: {bad json}\n\n",
        ]
        with endpoint(chunks) as url:
            with self.assertRaises(StreamingError) as caught:
                stream_chat(request(url))
        self.assertEqual(caught.exception.content_event_count, 1)
        self.assertIsNotNone(caught.exception.first_content_ns)
        self.assertEqual(caught.exception.first_content_ns, caught.exception.last_content_ns)

    def test_done_received_after_parse_deadline_times_out(self):
        chunks = [b"".join([
            event({"choices": [{"delta": {"content": "x"}, "finish_reason": "stop"}]}),
            event({"choices": [], "usage": {"completion_tokens": 1}}),
            b"data: [DONE]\n\n",
        ])]
        real_loads = json.loads
        def slow_loads(value):
            time.sleep(.04)
            return real_loads(value)
        with endpoint(chunks) as url:
            timed = request(url)
            timed["timeout_seconds"] = .05
            with patch("runpod_benchmark.streaming.json.loads", side_effect=slow_loads):
                with self.assertRaises(StreamingError) as caught:
                    stream_chat(timed)
        self.assertTrue(caught.exception.request_timed_out)
        self.assertIsNotNone(caught.exception.first_content_ns)

    def test_malformed_sse_and_http_failures_are_retained_as_failures(self):
        with endpoint([b"data: {bad json}\n\n"]) as url:
            with self.assertRaisesRegex(StreamingError, "malformed JSON"):
                stream_chat(request(url))
        with endpoint([b"failure"], status=503) as url:
            with self.assertRaisesRegex(StreamingError, "503"):
                stream_chat(request(url))


if __name__ == "__main__":
    unittest.main()
