from __future__ import annotations

import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from token_by_token_cli.selftest import run_selftest


class OfflineViolation(AssertionError):
    pass


class OfflineNetworkTests(unittest.TestCase):
    def test_selftest_attempts_no_socket_or_dns_operation(self) -> None:
        violations: list[str] = []

        def blocked(name: str):
            def fail(*_args: object, **_kwargs: object) -> None:
                violations.append(name)
                raise OfflineViolation(name)
            return fail

        patches = [
            patch.object(socket.socket, name, blocked(name))
            for name in ("connect", "connect_ex", "send", "sendto", "sendmsg")
            if hasattr(socket.socket, name)
        ] + [
            patch.object(socket, name, blocked(name))
            for name in ("create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex")
        ]
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {
                "HTTPS_PROXY": "http://127.0.0.1:9",
                "HTTP_PROXY": "http://127.0.0.1:9",
                "TOKEN_BY_TOKEN_SERVICE_URL": "https://private.invalid",
                "TOKEN_BY_TOKEN_TOKEN": "never-print-this",
            },
            clear=False,
        ):
            for active in patches:
                active.start()
            try:
                report = run_selftest(Path(directory) / "offline.tbt.zip", episode=2, users=4, seed=42, offline=True, stop_requested=lambda: False)
            finally:
                for active in reversed(patches):
                    active.stop()
        self.assertEqual(report.classification, "synthetic_mock")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
