from __future__ import annotations

import http.server
import json
import multiprocessing
import os
import signal
import socket
import time
import unittest

from runpod_benchmark.bounded_runpod_transport import (
    BoundedRunpodTransport,
    TransportDeadlineExceeded,
    TransportInvalidResponseError,
    TransportLateResponseError,
    TransportNetworkError,
    TransportProtocolError,
    TransportResponseError,
    TransportWorkerError,
)


SECRET = "test-token-must-not-appear"


class _QuietServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, _request, _client_address):
        pass


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *args):
        pass

    def _json(self, status, body):
        encoded = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if self.path == "/v2/json?a=1&z=2":
            self._json(200, {"ok": True})
        elif self.path == "/v2/status":
            self._json(503, {"error": "busy"})
        elif self.path == "/v2/redirect":
            self.send_response(302)
            self.send_header("Location", "/v2/json")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path == "/v2/non-json":
            body = b"not-json"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/v2/html-error":
            body = b"<html>upstream failed</html>"
            self.send_response(502)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/v2/empty-500":
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path == "/v2/exact-invalid-limit":
            body = b"x" * 32
            self.send_response(502)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/v2/truncated":
            body = b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "100")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            self.close_connection = True
        elif self.path == "/v2/conflicting-framing":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "2")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self.wfile.write(b"2\r\n{}\r\n0\r\n\r\n")
            self.wfile.flush()
        elif self.path == "/v2/chunked":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self.wfile.write(b"B\r\n{\"ok\":true}\r\n0\r\n\r\n")
            self.wfile.flush()
        elif self.path == "/v2/oversize":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "1000")
            self.end_headers()
        elif self.path == "/v2/oversize-stream":
            body = b'{' + (b'"x"' * 100) + b'}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/v2/nonfinite-json":
            body = b'{"value":NaN}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/v2/duplicate-key-json":
            body = b'{"value":1,"value":2}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/v2/slow-headers":
            time.sleep(1.0)
            self._json(200, {"late": True})
        elif self.path == "/v2/drip":
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            for byte in body:
                self.wfile.write(bytes([byte]))
                self.wfile.flush()
                time.sleep(0.08)
        elif self.path == "/v2/drop":
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
        else:
            self._json(404, {"error": "missing"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        parsed = json.loads(body)
        self._json(
            201,
            {
                "auth_ok": self.headers.get("Authorization") == "Bearer " + SECRET,
                "body": parsed,
            },
        )

    def do_DELETE(self):
        if self.path == "/v2/pods/example":
            self.send_response(204)
            self.end_headers()
        else:
            self._json(404, {"error": "missing"})


def _serve(ready):
    server = _QuietServer(("127.0.0.1", 0), _Handler)
    ready.send(server.server_address[1])
    ready.close()
    server.serve_forever(poll_interval=0.05)


def _hang(_spec):
    while True:
        time.sleep(10)


def _ignore_term_and_hang(_spec):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        time.sleep(10)


def _crash(_spec):
    os._exit(7)


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        context = multiprocessing.get_context("spawn")
        receive, send = context.Pipe(duplex=False)
        cls.server_process = context.Process(target=_serve, args=(send,), name="loopback-http-test")
        cls.server_process.start()
        send.close()
        if not receive.poll(5):
            raise RuntimeError("loopback server did not start")
        cls.port = receive.recv()
        receive.close()
        cls.origin = f"http://127.0.0.1:{cls.port}/v2"

    @classmethod
    def tearDownClass(cls):
        cls.server_process.terminate()
        cls.server_process.join(2)
        if cls.server_process.is_alive():
            cls.server_process.kill()
            cls.server_process.join(2)

    def transport(self, **kwargs):
        return BoundedRunpodTransport.for_loopback_test(SECRET, self.origin, **kwargs)

    def assert_sanitized(self, exc):
        self.assertNotIn(SECRET, str(exc))

    def test_success_query_post_and_delete_204(self):
        with self.transport() as transport:
            response = transport.request(
                "GET", "/json", query={"z": "2", "a": "1"}, deadline_monotonic=time.monotonic() + 2
            )
            self.assertEqual((response.status, response.body), (200, {"ok": True}))
            response = transport.request(
                "POST", "/pods", json_body={"name": "example"}, deadline_monotonic=time.monotonic() + 2
            )
            self.assertEqual(response.status, 201)
            self.assertEqual(response.body, {"auth_ok": True, "body": {"name": "example"}})
            response = transport.request(
                "DELETE", "/pods/example", deadline_monotonic=time.monotonic() + 2
            )
            self.assertEqual((response.status, response.body), (204, None))

    def test_error_status_is_returned_without_retry(self):
        with self.transport() as transport:
            response = transport.request("GET", "/status", deadline_monotonic=time.monotonic() + 2)
            self.assertEqual((response.status, response.body), (503, {"error": "busy"}))

    def test_redirect_is_rejected(self):
        with self.transport() as transport:
            with self.assertRaises(TransportProtocolError) as caught:
                transport.request("GET", "/redirect", deadline_monotonic=time.monotonic() + 2)
            self.assert_sanitized(caught.exception)

    def test_non_json_is_rejected(self):
        with self.transport() as transport:
            with self.assertRaises(TransportInvalidResponseError) as caught:
                transport.request("GET", "/non-json", deadline_monotonic=time.monotonic() + 2)
            self.assert_sanitized(caught.exception)
            self.assertIsInstance(caught.exception, TransportResponseError)
            self.assertEqual(caught.exception.validation_error, "invalid_body")
            self.assertEqual(caught.exception.stage, "invalid_json")
            self.assertEqual(caught.exception.response.status, 200)
            self.assertEqual(caught.exception.response.body, None)
            self.assertEqual(caught.exception.response.raw_body, b"not-json")

    def test_html_error_and_empty_500_retain_exact_failed_responses(self):
        with self.transport() as transport:
            with self.assertRaises(TransportResponseError) as html:
                transport.request("GET", "/html-error", deadline_monotonic=time.monotonic() + 2)
            self.assertIsInstance(html.exception, TransportProtocolError)
            self.assertEqual(html.exception.validation_error, "invalid_body")
            self.assertEqual(html.exception.response.status, 502)
            self.assertEqual(html.exception.response.raw_body, b"<html>upstream failed</html>")
            self.assertIsNone(html.exception.response.body)

            with self.assertRaises(TransportResponseError) as empty:
                transport.request("GET", "/empty-500", deadline_monotonic=time.monotonic() + 2)
            self.assertEqual(empty.exception.stage, "empty_body")
            self.assertEqual(empty.exception.response.status, 500)
            self.assertEqual(empty.exception.response.raw_body, b"")
            self.assertIsNone(empty.exception.response.body)

    def test_exact_body_limit_is_retained_but_oversize_is_not_fabricated(self):
        with self.transport(max_response_bytes=32) as transport:
            with self.assertRaises(TransportResponseError) as caught:
                transport.request(
                    "GET", "/exact-invalid-limit",
                    deadline_monotonic=time.monotonic() + 2,
                )
            self.assertEqual(caught.exception.response.raw_body, b"x" * 32)
        with self.transport(max_response_bytes=31) as transport:
            with self.assertRaises(TransportProtocolError) as caught:
                transport.request(
                    "GET", "/exact-invalid-limit",
                    deadline_monotonic=time.monotonic() + 2,
                )
            self.assertNotIsInstance(caught.exception, TransportResponseError)

    def test_truncated_and_ambiguous_framing_never_fabricate_response(self):
        with self.transport() as transport:
            for path in ("/truncated", "/conflicting-framing"):
                with self.subTest(path=path):
                    with self.assertRaises(TransportProtocolError) as caught:
                        transport.request(
                            "GET", path, deadline_monotonic=time.monotonic() + 2
                        )
                    self.assertNotIsInstance(caught.exception, TransportResponseError)

    def test_single_chunked_framing_remains_supported(self):
        with self.transport() as transport:
            response = transport.request(
                "GET", "/chunked", deadline_monotonic=time.monotonic() + 2
            )
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, {"ok": True})
        self.assertEqual(response.raw_body, b'{"ok":true}')

    def test_sink_facing_path_catches_typed_observation_without_success(self):
        retained = []
        with self.transport() as transport:
            try:
                transport.request(
                    "GET", "/html-error", deadline_monotonic=time.monotonic() + 2
                )
            except TransportResponseError as exc:
                retained.append({
                    "validation_error": exc.validation_error,
                    "status": exc.response.status,
                    "raw_body": exc.response.raw_body,
                    "completed_monotonic_ns": exc.response.completed_monotonic_ns,
                })
            else:
                self.fail("invalid provider response was presented as success")
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0]["validation_error"], "invalid_body")
        self.assertEqual(retained[0]["status"], 502)
        self.assertEqual(retained[0]["raw_body"], b"<html>upstream failed</html>")
        self.assertGreater(retained[0]["completed_monotonic_ns"], 0)

    def test_post_decode_deadline_retains_response_and_reaps_worker(self):
        decode_cutoff = None

        def slow_factory(status, body, raw_body, completed_monotonic_ns):
            if decode_cutoff is not None:
                # Cross the operation's I/O deadline only after the complete
                # response reached decoding, retaining time for worker reap.
                time.sleep(max(0.0, decode_cutoff - time.monotonic()))
            from runpod_benchmark.bounded_runpod_transport import Response
            return Response(status, body, raw_body, completed_monotonic_ns)

        with self.transport(
            cleanup_reserve_seconds=0.25,
            response_factory=slow_factory,
        ) as transport:
            # Worker creation is outside the post-decode behavior under test.
            # Prove the loopback worker is responsive before timing that stage.
            transport.request(
                "GET", "/json", query={"a": "1", "z": "2"},
                deadline_monotonic=time.monotonic() + 2,
            )
            started = time.monotonic()
            decode_cutoff = started + 0.77
            with self.assertRaises(TransportLateResponseError) as caught:
                transport.request(
                    "GET", "/json", query={"a": "1", "z": "2"}, deadline_monotonic=started + 1.0
                )
            self.assertIsInstance(caught.exception, TransportResponseError)
            self.assertIsInstance(caught.exception, TransportDeadlineExceeded)
            self.assertEqual(caught.exception.validation_error, "late_response")
            self.assertEqual(caught.exception.stage, "post_decode_deadline")
            self.assertEqual(caught.exception.response.status, 200)
            self.assertEqual(caught.exception.response.body, {"ok": True})
            self.assertEqual(caught.exception.response.raw_body, b'{"ok":true}')
            self.assertTrue(caught.exception.worker_reaped)
            self.assertLess(time.monotonic() - started, 1.10)

    def test_declared_oversize_is_rejected(self):
        with self.transport(max_response_bytes=32) as transport:
            with self.assertRaises(TransportProtocolError) as caught:
                transport.request("GET", "/oversize", deadline_monotonic=time.monotonic() + 2)
            self.assert_sanitized(caught.exception)

    def test_streamed_oversize_is_rejected(self):
        with self.transport(max_response_bytes=32) as transport:
            with self.assertRaises(TransportProtocolError):
                transport.request("GET", "/oversize-stream", deadline_monotonic=time.monotonic() + 2)

    def test_nonfinite_json_is_rejected(self):
        with self.transport() as transport:
            with self.assertRaises(TransportProtocolError):
                transport.request("GET", "/nonfinite-json", deadline_monotonic=time.monotonic() + 2)

    def test_duplicate_json_keys_are_rejected(self):
        with self.transport() as transport:
            with self.assertRaises(TransportProtocolError):
                transport.request("GET", "/duplicate-key-json", deadline_monotonic=time.monotonic() + 2)

    def test_slow_headers_hit_whole_operation_deadline(self):
        with self.transport(cleanup_reserve_seconds=0.5) as transport:
            started = time.monotonic()
            with self.assertRaises(TransportDeadlineExceeded) as caught:
                transport.request("GET", "/slow-headers", deadline_monotonic=started + 0.2)
            self.assertTrue(caught.exception.worker_reaped)
            self.assertLess(time.monotonic() - started, 1.0)
            self.assert_sanitized(caught.exception)

    def test_slow_drip_hit_whole_operation_deadline(self):
        with self.transport(cleanup_reserve_seconds=0.5) as transport:
            started = time.monotonic()
            with self.assertRaises(TransportDeadlineExceeded) as caught:
                transport.request("GET", "/drip", deadline_monotonic=started + 0.25)
            self.assertTrue(caught.exception.worker_reaped)
            self.assertLess(time.monotonic() - started, 1.1)

    def test_dropped_connection_is_sanitized(self):
        with self.transport() as transport:
            with self.assertRaises(TransportNetworkError) as caught:
                transport.request("GET", "/drop", deadline_monotonic=time.monotonic() + 2)
            self.assert_sanitized(caught.exception)

    def test_injected_hung_operation_is_reaped_and_poisoned(self):
        transport = BoundedRunpodTransport(SECRET, _operation=_hang, cleanup_reserve_seconds=0.5)
        try:
            started = time.monotonic()
            with self.assertRaises(TransportDeadlineExceeded) as caught:
                transport.request("GET", "/pods", deadline_monotonic=started + 0.15)
            self.assertEqual(caught.exception.outcome, "unresolved")
            self.assertTrue(caught.exception.worker_reaped)
            self.assertLess(time.monotonic() - started, 0.9)
            with self.assertRaises(TransportWorkerError):
                transport.request("GET", "/pods", deadline_monotonic=time.monotonic() + 1)
        finally:
            transport.close()

    @unittest.skipUnless(hasattr(signal, "SIGKILL"), "requires POSIX process signals")
    def test_term_ignoring_worker_is_killed_within_caller_cleanup_reserve(self):
        transport = BoundedRunpodTransport(
            SECRET,
            _operation=_ignore_term_and_hang,
            cleanup_reserve_seconds=0.15,
        )
        try:
            started = time.monotonic()
            with self.assertRaises(TransportDeadlineExceeded) as caught:
                transport.request(
                    "GET", "/pods", deadline_monotonic=started + 0.35
                )
            self.assertTrue(caught.exception.worker_reaped)
            self.assertLess(time.monotonic() - started, 0.50)
            self.assertFalse(transport._process.is_alive())
        finally:
            transport.close()

    @unittest.skipUnless(hasattr(signal, "SIGSTOP"), "requires POSIX process suspension")
    def test_stalled_broker_cannot_block_large_ipc_send_past_deadline(self):
        transport = BoundedRunpodTransport(
            SECRET,
            max_request_bytes=1024 * 1024,
            cleanup_reserve_seconds=0.10,
        )
        try:
            transport._connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
            os.kill(transport._process.pid, signal.SIGSTOP)
            started = time.monotonic()
            with self.assertRaises(TransportDeadlineExceeded) as caught:
                transport.request(
                    "POST",
                    "/pods",
                    json_body={"padding": "x" * (512 * 1024)},
                    deadline_monotonic=started + 0.20,
                )
            self.assertTrue(caught.exception.worker_reaped)
            self.assertGreater(time.monotonic() - started, 0.05)
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertFalse(transport._process.is_alive())
        finally:
            transport.close()

    def test_injected_worker_crash_is_reported_without_payload(self):
        transport = BoundedRunpodTransport(SECRET, _operation=_crash)
        try:
            with self.assertRaises(TransportWorkerError) as caught:
                transport.request("GET", "/pods", deadline_monotonic=time.monotonic() + 2)
            self.assert_sanitized(caught.exception)
        finally:
            transport.close()

    def test_closed_input_surface_and_redacted_repr(self):
        transport = self.transport()
        try:
            self.assertNotIn(SECRET, repr(transport))
            with self.assertRaises(ValueError):
                transport.request("PATCH", "/pods", deadline_monotonic=time.monotonic() + 1)
            with self.assertRaises(ValueError):
                transport.request("GET", "//example.test/escape", deadline_monotonic=time.monotonic() + 1)
            with self.assertRaises(ValueError):
                transport.request("GET", "/pods?x=1", deadline_monotonic=time.monotonic() + 1)
            with self.assertRaises(ValueError):
                transport.request("POST", "/pods", json_body={"x": float("nan")}, deadline_monotonic=time.monotonic() + 1)
        finally:
            transport.close()
        with self.assertRaises(ValueError):
            BoundedRunpodTransport(SECRET, _origin="https://example.test/v2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
