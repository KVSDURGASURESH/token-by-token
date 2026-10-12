from __future__ import annotations

import json
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stdout

from token_by_token_cli.cli import main
from token_by_token_cli.errors import ClientError
from token_by_token_cli.local_worker import run_local
from token_by_token_cli.local_worker import _invoke


WORKER_SCRIPT = '''#!/usr/bin/env python3
import json, os, pathlib, sys
if "TBT_PRIVATE_CANARY" in os.environ:
    raise SystemExit(9)
if sys.argv[1] == "capabilities":
    print(json.dumps({"schema_version":"local-capabilities.v1","episode":1,"execution_status":"synthetic_diagnostic","combinations":[{"model":"loopback-model","gpu":"none","load_profile":"single"}]}))
elif sys.argv[1] == "run":
    request = json.load(sys.stdin)
    assert set(request) == {"schema_version","episode","model","gpu","load_profile","request_id"}
    result = {"schema_version":"local-result.v1","classification":"synthetic_mock","execution_path":"agentbench_coordinator_worker_loopback_http","result":{"schema_version":"public-result.v1","episode":1,"run_id":request["request_id"],"qualification":"partial","cost_state":"unavailable","attempted_requests":1,"valid_requests":1,"metrics":{"ttft_p50_ms":10.0,"decode_tps_p10":20.0,"output_tokens_per_s":30.0}}}
    pathlib.Path(sys.argv[sys.argv.index("--output")+1]).write_text(json.dumps(result))
    print(json.dumps(result))
else:
    raise SystemExit(9)
'''


class LocalWorkerTests(unittest.TestCase):
    def test_run_local_help_names_required_artifacts(self) -> None:
        displayed = io.StringIO()
        with redirect_stdout(displayed), self.assertRaisesRegex(SystemExit, "0"):
            main(["episode", "1", "run-local", "--help"])
        help_text = displayed.getvalue()
        self.assertIn("reviewed agentbench-worker", help_text)
        self.assertIn("NEW_FILE.tbt.json", help_text)

    def test_bounded_local_transport_and_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker = root / "worker"
            worker.write_text(WORKER_SCRIPT)
            worker.chmod(0o755)
            output = root / "result.tbt.json"
            with mock.patch.dict(os.environ, {"TBT_PRIVATE_CANARY": "secret"}):
                result = run_local(worker, output)
            self.assertEqual(result["classification"], "synthetic_mock")
            self.assertEqual(result["result"]["valid_requests"], 1)
            self.assertEqual(json.loads(output.read_text()), result)
            with self.assertRaisesRegex(ClientError, "OUTPUT_PATH"):
                run_local(worker, output)

    def test_unknown_worker_or_episode_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ClientError, "WORKER_PATH"):
                run_local(root / "missing", root / "out.tbt.json")

    def test_rejected_result_does_not_publish_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker = root / "worker"
            worker.write_text(WORKER_SCRIPT.replace("print(json.dumps(result))", "print('{}')"))
            worker.chmod(0o755)
            output = root / "rejected.tbt.json"
            with self.assertRaises(ClientError):
                run_local(worker, output)
            self.assertFalse(output.exists())

    def test_worker_output_is_bounded_during_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            worker = Path(temporary) / "worker"
            worker.write_text("#!/usr/bin/env python3\nimport sys\nsys.stdout.write('x' * 200000)\n")
            worker.chmod(0o755)
            with self.assertRaisesRegex(ClientError, "WORKER_FAILED"):
                _invoke(worker, ["capabilities", "--json"], timeout=5)

    def test_cli_exposes_only_explicit_local_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker = root / "worker"
            worker.write_text(WORKER_SCRIPT)
            worker.chmod(0o755)
            output = root / "local.tbt.json"
            displayed = io.StringIO()
            with redirect_stdout(displayed):
                status = main(["episode", "1", "run-local", "--worker", str(worker), "--output", str(output), "--format", "json"])
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(displayed.getvalue()), json.loads(output.read_text()))


if __name__ == "__main__":
    unittest.main()
