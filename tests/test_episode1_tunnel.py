from __future__ import annotations

import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from runpod_benchmark import episode1_remote as remote


FAKE_SSH = r'''
import json, os, signal, socket, sys
a=sys.argv[1:]; path=a[a.index('-S')+1]
if '-M' in a:
    if 'ignore-term' in a: signal.signal(signal.SIGTERM, signal.SIG_IGN)
    listener=socket.socket(socket.AF_UNIX); listener.bind(path); listener.listen(5)
    forwards=[]
    while True:
        connection,_=listener.accept()
        with connection:
            request=json.loads(connection.recv(8192))
            if request['action']=='check':
                pid=os.getpid()+int('wrong-pid' in a)
                response={'code':0,'stderr':'Master running (pid=%d)\r\n'%pid}
            else:
                try:
                    host,port,remote_host,remote_port=request['forward'].split(':')
                    assert host=='127.0.0.1' and remote_host=='127.0.0.1' and remote_port=='8000'
                    forward=socket.socket(); forward.bind((host,int(port))); forward.listen(5)
                    forwards.append(forward); response={'code':0,'stderr':''}
                except (OSError, AssertionError): response={'code':1,'stderr':'forward rejected'}
            connection.sendall(json.dumps(response).encode())
else:
    client=socket.socket(socket.AF_UNIX); client.connect(path)
    action=a[a.index('-O')+1]
    request={'action':action}
    if action=='forward': request['forward']=a[a.index('-L')+1]
    client.sendall(json.dumps(request).encode())
    response=json.loads(client.recv(8192)); client.close()
    sys.stderr.write(response['stderr']); sys.exit(response['code'])
'''


class TunnelTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.fake = root / "fake_ssh.py"
        self.fake.write_text(FAKE_SSH)
        self.fake.chmod(0o600)
        key, known = root / "key", root / "known"
        for path in (key, known):
            path.write_text("fixture")
            path.chmod(0o600)
        config = remote.SshConfig("192.0.2.1", 22, "root", key, known)
        self.executor = remote.SshRemoteExecutor(config)
        self.tunnel = None
        self.process = None

    def tearDown(self):
        if self.tunnel is not None and self.tunnel.process is not None:
            self.tunnel.close(deadline_monotonic=time.monotonic() + 1)
        self.directory.cleanup()

    @staticmethod
    def port():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def fake_argv(self, mode="normal"):
        return patch.object(
            remote.SshConfig,
            "base_argv",
            side_effect=lambda: [
                sys.executable, "-u", str(self.fake), mode, "root@fixture"
            ],
        )

    def start(self, port=None):
        self.tunnel = remote.SshTunnel(self.executor, local_port=port or self.port())
        self.tunnel.start(deadline_monotonic=time.monotonic() + 5)
        self.process = self.tunnel.process

    def assert_gone(self, process):
        self.assertIsNotNone(process.returncode)
        with self.assertRaises(ProcessLookupError):
            os.killpg(process.pid, 0)

    def test_forward_acknowledgement_binds_master_and_loopback(self):
        with self.fake_argv():
            self.start()
        self.assertTrue(self.tunnel.ready)
        with socket.create_connection(("127.0.0.1", self.tunnel.local_port), timeout=.1):
            pass
        control = self.tunnel._control_directory
        self.tunnel.close(deadline_monotonic=time.monotonic() + 1)
        self.assert_gone(self.process)
        self.assertFalse(Path(control).exists())

    def test_unrelated_listener_cannot_satisfy_readiness(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen()
            with self.fake_argv(), self.assertRaisesRegex(remote.RemoteExecutionError, "rejected"):
                self.start(listener.getsockname()[1])
        self.assertIsNone(self.tunnel.process)
        self.assertFalse(self.tunnel.ready)

    def test_control_response_from_wrong_pid_rejected(self):
        with self.fake_argv("wrong-pid"), self.assertRaisesRegex(
            remote.RemoteExecutionError, "owned master"
        ):
            self.start()
        self.assertIsNone(self.tunnel.process)

    def test_master_death_cancels_active_tunnel(self):
        with self.fake_argv():
            self.start()
        os.killpg(self.process.pid, signal.SIGKILL)
        self.assertTrue(self.tunnel.cancel_event.wait(.5))
        self.assertFalse(self.tunnel.ready)
        self.tunnel.close(deadline_monotonic=time.monotonic() + 1)
        self.assert_gone(self.process)

    def test_cleanup_never_grants_fresh_deadline(self):
        with self.fake_argv("ignore-term"):
            self.start()
        started = time.monotonic()
        self.tunnel.close(deadline_monotonic=started + .08)
        self.assertLess(time.monotonic() - started, .13)
        self.assert_gone(self.process)

    def test_exhausted_start_deadline_never_spawns(self):
        self.tunnel = remote.SshTunnel(self.executor, local_port=self.port())
        with patch.object(remote.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(remote.RemoteExecutionError, "reserve"):
                self.tunnel.start(deadline_monotonic=time.monotonic() + .05)
        spawn.assert_not_called()

    def test_executor_and_tunnel_share_exact_clock(self):
        clock = lambda: time.monotonic()
        executor = remote.SshRemoteExecutor(self.executor.config, monotonic=clock)
        tunnel = remote.SshTunnel(executor, local_port=self.port())
        self.assertIs(tunnel.monotonic, clock)
        with self.assertRaisesRegex(ValueError, "same monotonic clock"):
            remote.SshTunnel(executor, local_port=self.port(), monotonic=time.monotonic)

    def test_invalid_port_is_rejected(self):
        for port in (True, 1.5, 0, 65536):
            with self.assertRaises(ValueError):
                remote.SshTunnel(self.executor, local_port=port)
        with self.assertRaises(ValueError):
            remote.SshTunnel(self.executor, local_port=5000, remote_port=22)


if __name__ == "__main__":
    unittest.main()
