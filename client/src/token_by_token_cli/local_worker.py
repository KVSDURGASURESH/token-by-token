"""Bounded invocation of the opt-in local AgentBench worker executable."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
import time
import uuid

from .contracts import validate_document
from .errors import ClientError


MAX_REPLY = 64 * 1024


def _invoke(worker: Path, arguments: list[str], *, request: dict[str, object] | None = None, timeout: int = 30) -> dict[str, object]:
    if not worker.is_file() or not os.access(worker, os.X_OK):
        raise ClientError("WORKER_PATH", "worker must be an executable file")
    environment = {key: os.environ[key] for key in ("PATH", "TMPDIR", "LANG", "SYSTEMROOT") if key in os.environ}
    payload = json.dumps(request, sort_keys=True, separators=(",", ":")).encode() if request is not None else b""
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            [str(worker), *arguments], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=environment, start_new_session=(os.name == "posix"),
        )
        assert process.stdin is not None and process.stdout is not None and process.stderr is not None
        process.stdin.write(payload)
        process.stdin.close()
        streams = {process.stdout: bytearray(), process.stderr: bytearray()}
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            for stream in streams:
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map():
                if time.monotonic() >= deadline:
                    raise TimeoutError("worker timed out")
                for key, _ in selector.select(min(0.2, max(0, deadline - time.monotonic()))):
                    chunk = os.read(key.fileobj.fileno(), min(4096, MAX_REPLY + 1 - len(streams[key.fileobj])))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    streams[key.fileobj].extend(chunk)
                    if len(streams[key.fileobj]) > MAX_REPLY:
                        raise ValueError("worker output exceeded limit")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("worker timed out")
        process.wait(timeout=remaining)
        stdout = bytes(streams[process.stdout])
        stderr = bytes(streams[process.stderr])
    except (OSError, TimeoutError, subprocess.TimeoutExpired, ValueError) as error:
        if process is not None:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            process.wait()
        raise ClientError("WORKER_FAILED", "local worker could not finish") from error
    finally:
        if process is not None:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
    if process.returncode != 0:
        raise ClientError("WORKER_FAILED", "local worker rejected or failed the request")
    try:
        reply = json.loads(stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ClientError("WORKER_REPLY", "local worker returned invalid JSON") from error
    if not isinstance(reply, dict):
        raise ClientError("WORKER_REPLY", "local worker returned an invalid document")
    return reply


def run_local(worker: Path, output: Path, *, episode: int = 1) -> dict[str, object]:
    worker = Path(worker).resolve()
    output = Path(output)
    if output.exists() or not output.name.endswith(".tbt.json") or not output.parent.is_dir():
        raise ClientError("OUTPUT_PATH", "output must be a new .tbt.json file in an existing directory")
    capability = _invoke(worker, ["capabilities", "--json"])
    validate_document("local-capabilities.v1", capability)
    if episode != capability["episode"]:
        raise ClientError("UNAVAILABLE_EPISODE", "local worker does not support this episode")
    combination = capability["combinations"][0]
    request = {
        "schema_version": "local-run-request.v1", "episode": episode,
        "model": combination["model"], "gpu": combination["gpu"],
        "load_profile": combination["load_profile"], "request_id": uuid.uuid4().hex,
    }
    validate_document("local-run-request.v1", request)
    with tempfile.TemporaryDirectory(prefix=".tbt-local-", dir=output.parent) as temporary:
        candidate = Path(temporary) / "candidate.tbt.json"
        reply = _invoke(worker, ["run", "--request", "-", "--output", str(candidate.absolute())], request=request, timeout=60)
        validate_document("local-result.v1", reply)
        validate_document("public-result.v1", reply["result"])
        if reply["result"]["valid_requests"] > reply["result"]["attempted_requests"]:
            raise ClientError("WORKER_REPLY", "valid requests exceed attempted requests")
        if any(not math.isfinite(value) for value in reply["result"]["metrics"].values()):
            raise ClientError("WORKER_REPLY", "local metrics must be finite")
        if reply["result"]["run_id"] != request["request_id"] or reply["result"]["episode"] != episode:
            raise ClientError("WORKER_REPLY", "local result does not match the request")
        try:
            if candidate.stat().st_size > MAX_REPLY:
                raise ValueError("oversized result")
            written = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as error:
            raise ClientError("WORKER_REPLY", "local worker did not write a valid result") from error
        if written != reply:
            raise ClientError("WORKER_REPLY", "worker output and written result differ")
        try:
            os.link(candidate, output)
        except OSError as error:
            raise ClientError("OUTPUT_PATH", "could not publish local result") from error
        return reply
