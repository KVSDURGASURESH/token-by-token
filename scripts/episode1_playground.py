#!/usr/bin/env python3
"""Local Episode 1 quick-test bridge, demo endpoint, and matching CLI client."""

from __future__ import annotations

import argparse
import json
import mimetypes
import pathlib
import queue
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from runpod_benchmark.playground import (  # noqa: E402
    MAX_CONFIG_BYTES,
    SCHEMA_VERSION,
    PlaygroundValidationError,
    public_profiles,
    run_config,
    validate_config,
    validate_profiles,
    without_raw_text,
)
from runpod_benchmark.episode_suite import (  # noqa: E402
    SCHEMA_VERSION as EPISODE_SCHEMA_VERSION,
    public_registry,
    run_episode,
    validate_episode_run,
)
from runpod_benchmark.canonical_launch import (  # noqa: E402
    CanonicalLaunchController,
    CanonicalLaunchError,
)


class State:
    def __init__(self, profiles: dict[str, dict[str, Any]], dashboard: pathlib.Path | None,
                 canonical: CanonicalLaunchController | None = None):
        self.profiles = profiles
        self.dashboard = dashboard
        self.nonce = secrets.token_urlsafe(32)
        self.runs: dict[str, threading.Event] = {}
        self.lock = threading.Lock()
        self.canonical = canonical
        self.metrics_text = "# HELP inference_lab_up Local episode bridge health.\n# TYPE inference_lab_up gauge\ninference_lab_up 1\n"

    def record_episode_metrics(self, result: dict[str, Any]) -> None:
        lines = [
            "# HELP inference_lab_up Local episode bridge health.",
            "# TYPE inference_lab_up gauge", "inference_lab_up 1",
            "# HELP inference_lab_requests_total Requests observed in the latest completed episode run.",
            "# TYPE inference_lab_requests_total gauge",
        ]
        for cell in result.get("cells", []):
            for lane in cell.get("result", {}).get("lanes", []):
                labels = f'episode="{result["episode"]}",suite_round="{cell["suite_round"]}",cell="{cell["cell_id"]}",profile="{lane.get("profile_id", "unknown")}"'
                lines.append(f'inference_lab_requests_total{{{labels},status="attempted"}} {lane.get("attempted", 0)}')
                lines.append(f'inference_lab_requests_total{{{labels},status="successful"}} {lane.get("successful", 0)}')
                for metric_name, metric in lane.get("summary", {}).get("metrics", {}).items():
                    if not metric.get("available") or not metric.get("statistics"):
                        continue
                    safe_name = "".join(char if char.isalnum() or char == "_" else "_" for char in metric_name)
                    for statistic in ("mean", "p50", "p95", "p99"):
                        value = metric["statistics"].get(statistic)
                        if isinstance(value, (int, float)):
                            lines.append(f'inference_lab_{safe_name}{{{labels},statistic="{statistic}"}} {value}')
        for metric_name, metric in result.get("gpu_telemetry", {}).items():
            if isinstance(metric, dict) and metric.get("available") and metric.get("statistics"):
                for statistic in ("mean", "p50", "p95", "p99"):
                    value = metric["statistics"].get(statistic)
                    if isinstance(value, (int, float)):
                        lines.append(f'inference_lab_{metric_name}{{episode="{result["episode"]}",statistic="{statistic}"}} {value}')
        with self.lock:
            self.metrics_text = "\n".join(lines) + "\n"


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def _load_profiles(path: pathlib.Path | None, *, demo: bool, port: int) -> dict[str, dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    if path is not None:
        value = json.loads(path.read_text(encoding="utf-8"))
        raw.extend(value.get("profiles", value) if isinstance(value, dict) else value)
    if demo:
        base = f"http://127.0.0.1:{port}/demo"
        raw.extend([
            {"id": "demo-fast", "label": "Demo / quick lane", "url": f"{base}/fast/v1/chat/completions", "runtime_id": "vllm", "model": "episode1-demo", "supported_optional_fields": ["top_k", "seed", "stop"], "context_length": 4096, "gpu_type": None, "gpu_count": None, "node_count": 1, "parallelism": {"dp": 1, "tp": 1, "pp": 1, "ep": 1}, "runtime_controls": {"prompt_caching": "unknown", "chunked_prefill": "unknown", "continuous_batching": "enabled"}, "gpu_telemetry": "unavailable"},
            {"id": "demo-steady", "label": "Demo / steady lane", "url": f"{base}/steady/v1/chat/completions", "runtime_id": "sglang", "model": "episode1-demo", "supported_optional_fields": ["top_k", "seed", "stop"], "context_length": 4096, "gpu_type": None, "gpu_count": None, "node_count": 1, "parallelism": {"dp": 1, "tp": 1, "pp": 1, "ep": 1}, "runtime_controls": {"prompt_caching": "unknown", "chunked_prefill": "unknown", "continuous_batching": "enabled"}, "gpu_telemetry": "unavailable"},
        ])
    return validate_profiles(raw)


class Handler(BaseHTTPRequestHandler):
    server_version = "Episode1QuickTest/1"

    @property
    def state(self) -> State:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("quick-test: " + format % args + "\n")

    def _host_ok(self) -> bool:
        host = self.headers.get("Host", "").split(":", 1)[0]
        return host in {"127.0.0.1", "localhost", "[::1]"}

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        parsed = urlsplit(origin)
        return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}

    def _authorized(self) -> bool:
        return self._host_ok() and self._origin_ok() and secrets.compare_digest(
            self.headers.get("X-Episode1-Session", ""), self.state.nonce
        )

    def _send_json(self, status: int, value: object) -> None:
        body = _json_bytes(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        declared = self.headers.get("Content-Length")
        if declared is None or not declared.isdigit() or int(declared) > MAX_CONFIG_BYTES:
            raise PlaygroundValidationError("request body length is missing or too large")
        raw = self.rfile.read(int(declared))
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise PlaygroundValidationError("request body must be an object")
        return value

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if self.path == "/metrics":
            with self.state.lock:
                body = self.state.metrics_text.encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not self._host_ok() or not self._origin_ok():
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "forbidden host or origin"})
            return
        if self.path == "/api/capabilities":
            self._send_json(HTTPStatus.OK, {
                "schema_version": SCHEMA_VERSION,
                "session": self.state.nonce,
                "profiles": public_profiles(self.state.profiles),
                "limits": {"repetitions": 20, "concurrency": 4, "context_length_default": 4096},
            })
            return
        if self.path == "/api/episode-suite":
            self._send_json(HTTPStatus.OK, public_registry())
            return
        if self.path == "/api/canonical-status":
            status = self.state.canonical.status() if self.state.canonical else {
                "configured": False, "launch_enabled": False,
                "phase": "not-configured", "supported_episodes": [1],
            }
            self._send_json(HTTPStatus.OK, status)
            return
        self._static()

    def do_POST(self) -> None:
        if self.path.startswith("/demo/"):
            self._demo_stream()
            return
        if not self._authorized():
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "missing or invalid local session"})
            return
        try:
            if self.path == "/api/run":
                self._run_stream(self._body())
            elif self.path == "/api/episode-run":
                self._episode_stream(self._body())
            elif self.path == "/api/canonical-preflight":
                if self.state.canonical is None:
                    raise CanonicalLaunchError("no canonical launch bundle was configured at server start")
                self._send_json(HTTPStatus.OK, self.state.canonical.preflight())
            elif self.path == "/api/canonical-launch":
                if self.state.canonical is None:
                    raise CanonicalLaunchError("no canonical launch bundle was configured at server start")
                self._send_json(HTTPStatus.ACCEPTED, self.state.canonical.launch(self._body().get("approval_phrase")))
            elif self.path == "/api/cancel":
                body = self._body()
                run_id = body.get("run_id")
                with self.state.lock:
                    event = self.state.runs.get(run_id) if isinstance(run_id, str) else None
                if event is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "unknown run"})
                else:
                    event.set()
                    self._send_json(HTTPStatus.OK, {"cancelled": True})
            else:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except (PlaygroundValidationError, CanonicalLaunchError, json.JSONDecodeError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _event(self, value: object) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        self.wfile.write(f"data: {payload}\n\n".encode())
        self.wfile.flush()

    def _run_stream(self, config: dict[str, Any]) -> None:
        checked = validate_config(config, self.state.profiles)
        run_id = "run-" + secrets.token_hex(8)
        cancellation = threading.Event()
        events: queue.Queue[dict[str, Any] | None] = queue.Queue()
        with self.state.lock:
            self.state.runs[run_id] = cancellation

        def worker() -> None:
            try:
                run_config(checked, self.state.profiles, emit=events.put, cancel_event=cancellation)
            except Exception as exc:
                events.put({"type": "fatal", "error": str(exc)[:1024]})
            finally:
                events.put(None)

        threading.Thread(target=worker, daemon=True).start()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self._event({"type": "accepted", "run_id": run_id})
        try:
            while True:
                item = events.get(timeout=checked["request_timeout_seconds"] + 5)
                if item is None:
                    break
                self._event(item)
        except (BrokenPipeError, ConnectionResetError, queue.Empty):
            cancellation.set()
        finally:
            with self.state.lock:
                self.state.runs.pop(run_id, None)

    def _episode_stream(self, config: dict[str, Any]) -> None:
        checked = validate_episode_run(config, self.state.profiles)
        run_id = "episode-" + secrets.token_hex(8)
        cancellation = threading.Event()
        events: queue.Queue[dict[str, Any] | None] = queue.Queue()
        with self.state.lock:
            self.state.runs[run_id] = cancellation

        def worker() -> None:
            try:
                result = run_episode(checked, self.state.profiles, emit=events.put, cancel_event=cancellation)
                self.state.record_episode_metrics(result)
            except Exception as exc:
                events.put({"type": "fatal", "error": str(exc)[:1024]})
            finally:
                events.put(None)

        threading.Thread(target=worker, daemon=True).start()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self._event({"type": "accepted", "run_id": run_id})
        try:
            while True:
                item = events.get(timeout=checked["request_timeout_seconds"] + 5)
                if item is None:
                    break
                self._event(item)
        except (BrokenPipeError, ConnectionResetError, queue.Empty):
            cancellation.set()
        finally:
            with self.state.lock:
                self.state.runs.pop(run_id, None)

    def _demo_stream(self) -> None:
        if not self._host_ok() or not self._origin_ok():
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            return
        try:
            request = self._body()
            messages = request.get("messages")
            prompt = next((item.get("content", "") for item in reversed(messages) if item.get("role") == "user"), "")
            lane = "fast" if "/fast/" in self.path else "steady"
            words = (f"{lane.title()} demo response. The local bridge received your prompt safely. "
                     f"This simulated stream demonstrates runner-side timing without a GPU. Prompt length: {len(prompt)} characters.").split()
            delay = 0.018 if lane == "fast" else 0.034
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            for word in words:
                event = {"choices": [{"delta": {"content": word + " "}, "finish_reason": None}]}
                self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
                self.wfile.flush()
                time.sleep(delay)
            final = {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": max(1, len(prompt.split())), "completion_tokens": len(words)}}
            self.wfile.write(b"data: " + json.dumps(final).encode() + b"\n\ndata: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    def _static(self) -> None:
        root = self.state.dashboard
        if root is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "dashboard build not configured"})
            return
        relative = self.path.split("?", 1)[0].lstrip("/") or "index.html"
        candidate = (root / relative).resolve()
        if root.resolve() not in candidate.parents and candidate != root.resolve():
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "forbidden path"})
            return
        if not candidate.is_file():
            candidate = root / "index.html"
        body = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def serve(args: argparse.Namespace) -> int:
    dashboard = args.dashboard_dir.resolve() if args.dashboard_dir else None
    if dashboard is not None and not (dashboard / "index.html").is_file():
        raise SystemExit(f"dashboard build missing: {dashboard / 'index.html'}")
    profiles = _load_profiles(args.profiles, demo=args.demo, port=args.port)
    canonical = CanonicalLaunchController(
        args.canonical_launch_bundle, ROOT,
        launch_enabled=args.enable_canonical_launch,
    )
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.state = State(profiles, dashboard, canonical)  # type: ignore[attr-defined]
    print(f"Loopback bridge: http://127.0.0.1:{args.port}/", flush=True)
    print("Run `scripts/quick-test request`, `compare`, or `episode` from another terminal.", flush=True)
    print("The public dashboard is informational; request controls are CLI-only.", flush=True)
    print("Local diagnostic only; not benchmark evidence.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _capabilities(base: str) -> dict[str, Any]:
    with urllib.request.urlopen(base.rstrip("/") + "/api/capabilities", timeout=5) as response:
        return json.load(response)


def _make_config(args: argparse.Namespace, mode: str) -> dict[str, Any]:
    if args.config:
        value = json.loads(args.config.read_text(encoding="utf-8"))
        return validate_config(value)
    prompt = args.prompt_file.read_text(encoding="utf-8") if args.prompt_file else args.prompt
    if not prompt:
        raise SystemExit("provide --prompt, --prompt-file, or --config")
    required = 1 if mode == "single" else 2
    if len(args.profile) != required:
        raise SystemExit(f"{mode} requires exactly {required} --profile value(s)")
    return validate_config({
        "schema_version": SCHEMA_VERSION, "mode": mode,
        "prompt": {"system": args.system or "", "user": prompt},
        "lanes": [{"id": f"lane-{index + 1}", "profile_id": profile, "label": profile} for index, profile in enumerate(args.profile)],
        "sampling": {"maximum_output_tokens": args.max_output_tokens, "temperature": args.temperature, "top_p": args.top_p, **({"top_k": args.top_k} if args.top_k is not None else {}), **({"seed": args.seed} if args.seed is not None else {}), **({"stop": args.stop} if args.stop else {})},
        "request_timeout_seconds": args.timeout, "repetitions": args.repetitions,
        "concurrency": args.concurrency,
    })


def client(args: argparse.Namespace) -> int:
    base = args.bridge.rstrip("/")
    caps = _capabilities(base)
    config = _make_config(args, "single" if args.command == "request" else "compare")
    validate_config(config, {item["id"]: item for item in caps["profiles"]})
    request = urllib.request.Request(
        base + "/api/run", data=_json_bytes(config), method="POST",
        headers={"Content-Type": "application/json", "Accept": "text/event-stream", "X-Episode1-Session": caps["session"]},
    )
    final = None
    with urllib.request.urlopen(request, timeout=config["request_timeout_seconds"] + 10) as response:
        for raw in response:
            line = raw.decode("utf-8").rstrip("\r\n")
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            if event.get("type") == "content":
                sys.stdout.write(f"[{event['lane_id']}] {event['text']}")
                sys.stdout.flush()
            elif event.get("type") == "attempt":
                print(f"\n[{event['lane_id']}] {event['status']} TTFT={event.get('ttft_ms')}ms E2E={event.get('e2e_ms')}ms")
            elif event.get("type") == "complete":
                final = event["result"]
    if final is None:
        raise SystemExit("bridge ended without a completed result")
    if args.output:
        args.output.write_text(json.dumps(final, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        print(json.dumps(final, indent=2, sort_keys=True))
    return 0


def episode_client(args: argparse.Namespace) -> int:
    base = args.bridge.rstrip("/")
    caps = _capabilities(base)
    raw_config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {
        "schema_version": EPISODE_SCHEMA_VERSION,
        "episode": args.episode,
        "profile_ids": args.profile,
        "suite_repetitions": args.suite_repetitions,
        "repetitions": args.repetitions,
        "batch_size": args.batch_size,
        "context_tokens": args.context_tokens,
        "sequence_tokens": args.sequence_tokens,
        "request_timeout_seconds": args.timeout,
    }
    config = validate_episode_run(raw_config, {item["id"]: item for item in caps["profiles"]})
    request = urllib.request.Request(
        base + "/api/episode-run", data=_json_bytes(config), method="POST",
        headers={"Content-Type": "application/json", "Accept": "text/event-stream", "X-Episode1-Session": caps["session"]},
    )
    final = None
    with urllib.request.urlopen(request, timeout=config["request_timeout_seconds"] + 15) as response:
        for raw in response:
            line = raw.decode("utf-8").rstrip("\r\n")
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            if event.get("type") == "cell":
                print(f"episode {config['episode']} round {event.get('suite_round')}/{config['suite_repetitions']}: {event.get('cell_label')} — {event.get('state')}", file=sys.stderr)
            elif event.get("type") == "fatal":
                raise SystemExit(event.get("error", "episode run failed"))
            elif event.get("type") == "complete":
                final = event["result"]
    if final is None:
        raise SystemExit("bridge ended without a completed episode result")
    if args.output:
        args.output.write_text(json.dumps(final, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        print(json.dumps(final, indent=2, sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)
    for name in ("serve", "demo"):
        command = sub.add_parser(name, help="serve the loopback bridge" + (" with built-in mock endpoints" if name == "demo" else ""))
        command.add_argument("--port", type=int, default=8765)
        command.add_argument("--host", default="127.0.0.1", help="listen address; containers use 0.0.0.0")
        command.add_argument("--profiles", type=pathlib.Path)
        command.add_argument("--dashboard-dir", type=pathlib.Path, default=ROOT / "dashboard" / "dist")
        command.add_argument("--canonical-launch-bundle", type=pathlib.Path,
                             help="fixed Episode 1 launch bundle selected by the server operator")
        command.add_argument("--enable-canonical-launch", action="store_true",
                             help="permit paid launch after all canonical approval gates pass")
        command.set_defaults(func=serve, demo=name == "demo")
    for name in ("request", "compare"):
        command = sub.add_parser(name, help=f"run a {name} through a local bridge")
        command.add_argument("--bridge", default="http://127.0.0.1:8765")
        command.add_argument("--config", type=pathlib.Path)
        command.add_argument("--profile", action="append", default=[])
        command.add_argument("--prompt")
        command.add_argument("--prompt-file", type=pathlib.Path)
        command.add_argument("--system")
        command.add_argument("--max-output-tokens", type=int, default=128)
        command.add_argument("--temperature", type=float, default=0.0)
        command.add_argument("--top-p", type=float, default=1.0)
        command.add_argument("--top-k", type=int)
        command.add_argument("--seed", type=int)
        command.add_argument("--stop")
        command.add_argument("--timeout", type=float, default=120)
        command.add_argument("--repetitions", type=int, default=1)
        command.add_argument("--concurrency", type=int, default=1)
        command.add_argument("--output", type=pathlib.Path)
        command.set_defaults(func=client)
    command = sub.add_parser("episode", help="run one Episode 1-16 endpoint rehearsal through a local bridge")
    command.add_argument("--bridge", default="http://127.0.0.1:8765")
    command.add_argument("--config", type=pathlib.Path, help="complete episode run JSON; when set, workload flags are ignored")
    command.add_argument("--episode", type=int)
    command.add_argument("--profile", action="append", default=[])
    command.add_argument("--timeout", type=float, default=120)
    command.add_argument("--suite-repetitions", type=int, default=1, help="repeat the entire ordered episode pack 1-10 times")
    command.add_argument("--repetitions", type=int, default=1)
    command.add_argument("--batch-size", type=int, default=1)
    command.add_argument("--context-tokens", type=int, default=2048)
    command.add_argument("--sequence-tokens", type=int, default=128)
    command.add_argument("--output", type=pathlib.Path)
    command.set_defaults(func=episode_client)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
