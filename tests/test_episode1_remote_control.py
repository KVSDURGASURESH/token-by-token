from __future__ import annotations

import io
import math
import socket
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from runpod_benchmark.episode1_remote_control import (
    RemoteControlError,
    _load_one_json,
    _receive_until_eof,
    _request_deadline,
    client,
    main,
)


class RemoteControlProtocolTests(unittest.TestCase):
    def test_help_is_local_and_does_not_read_stdin_or_open_control_socket(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--help"]), 0)
        self.assertIn("usage: episode1-control", output.getvalue())

    def test_json_rejects_duplicate_and_nonfinite_values(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(RemoteControlError):
                _load_one_json(io.BytesIO(raw))

    def test_request_deadline_is_remote_monotonic_and_closed(self):
        now = time.monotonic()
        deadline = _request_deadline({
            "operation_timeout_seconds": .2,
            "operation_deadline_monotonic": now + .1,
        })
        self.assertGreater(deadline, now)
        self.assertLessEqual(deadline, now + .11)
        for bad in (True, math.nan, math.inf, now - 1, now + 121):
            with self.subTest(bad=bad), self.assertRaises(RemoteControlError):
                _request_deadline({
                    "operation_timeout_seconds": 1,
                    "operation_deadline_monotonic": bad,
                })

    def test_request_deadline_never_renews_original_absolute_deadline(self):
        with patch(
            "runpod_benchmark.episode1_remote_control.time.monotonic",
            side_effect=[100.0],
        ):
            self.assertEqual(_request_deadline({
                "operation_timeout_seconds": 10,
                "operation_deadline_monotonic": 105.0,
            }), 105.0)

    def test_socket_receive_uses_whole_operation_deadline(self):
        reader, writer = socket.socketpair()

        def drip() -> None:
            try:
                for byte in b"1234567890":
                    writer.send(bytes([byte]))
                    time.sleep(.03)
            except OSError:
                pass
            finally:
                writer.close()

        thread = threading.Thread(target=drip)
        thread.start()
        started = time.monotonic()
        try:
            with self.assertRaisesRegex(RemoteControlError, "deadline"):
                _receive_until_eof(reader, started + .08)
        finally:
            reader.close()
            thread.join(timeout=1)
        self.assertLess(time.monotonic() - started, .25)

    def test_client_does_not_reset_budget_on_slow_response(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "control.sock"
            ready = threading.Event()

            def server() -> None:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                    listener.bind(str(path))
                    listener.listen(1)
                    ready.set()
                    connection, _ = listener.accept()
                    with connection:
                        while connection.recv(65536):
                            pass
                        try:
                            for byte in b'{"ok":true,"result":{}}':
                                connection.send(bytes([byte]))
                                time.sleep(.02)
                        except OSError:
                            pass

            thread = threading.Thread(target=server)
            thread.start()
            self.assertTrue(ready.wait(1))
            started = time.monotonic()
            with self.assertRaisesRegex(RemoteControlError, "deadline"):
                client("status", {
                    "operation_timeout_seconds": .08,
                    "operation_deadline_monotonic": started + .08,
                }, path)
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())
            self.assertLess(time.monotonic() - started, .25)

    def test_client_rejects_expired_deadline_before_opening_socket(self):
        with patch(
            "runpod_benchmark.episode1_remote_control.time.monotonic", return_value=100.0
        ), patch("runpod_benchmark.episode1_remote_control.socket.socket") as socket_factory:
            with self.assertRaisesRegex(RemoteControlError, "outside the closed bound"):
                client("start", {"operation_deadline_monotonic": 99.0})
        socket_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
