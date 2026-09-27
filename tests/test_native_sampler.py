from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import tempfile
import threading
import time
import unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from runpod_benchmark.native_sampler import (
    Binding,
    MetricSpec,
    NativeSampler,
    PrivateEvidenceStore,
    SamplerError,
    localhost_http_scraper,
    parse_prometheus,
)
from runpod_benchmark.telemetry_summary import Window


VALID = b"""# HELP engine_requests_total Native requests
# TYPE engine_requests counter
# UNIT engine_requests requests
engine_requests_total{model=\"m\\\"1\",worker=\"w0\"} 7
# HELP engine_queue_depth Native queue depth
# TYPE engine_queue_depth gauge
engine_queue_depth{worker=\"w0\"} 2
"""


class FakeClock:
    def __init__(self, monotonic_ns: int = 1_000, utc_ns: int = 1_700_000_000_000_000_000):
        self.mono = monotonic_ns
        self.utc = utc_ns

    def monotonic_ns(self) -> int:
        value = self.mono
        self.mono += 1
        return value

    def time_ns(self) -> int:
        value = self.utc
        self.utc += 1
        return value


def binding() -> Binding:
    return Binding(
        run_id="run-1", attempt_id="attempt-1", process_identity="pid:123",
        process_start_identity="linux:123:456", runtime="vllm", block="block-a",
        clock_domain="host-boot-a",
    )


def specs():
    return (
        MetricSpec("counter", "engine_requests_total", {"model": 'm"1', "worker": "w0"}, "requests"),
        MetricSpec("gauge", "engine_queue_depth", {"worker": "w0"}, "1"),
    )


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path == "/slow-header":
            wire = b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello"
            for byte in wire:
                try:
                    self.connection.sendall(bytes((byte,)))
                except (BrokenPipeError, ConnectionResetError):
                    break
                time.sleep(0.01)
            return
        if self.path == "/slow-body":
            try:
                self.connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 20\r\n\r\n")
                for _ in range(20):
                    self.connection.sendall(b"x")
                    time.sleep(0.01)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if self.path == "/eof-large":
            try:
                self.connection.sendall(b"HTTP/1.0 200 OK\r\n\r\n" + b"x" * 1025)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/metrics")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/slow":
            time.sleep(0.15)
        body = VALID if self.path != "/large" else b"x" * 1025
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def log_message(self, *_args):
        pass


class NativeSamplerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(1)

    def test_parser_preserves_native_metadata_labels_and_units(self):
        parsed = parse_prometheus(VALID)
        self.assertEqual(parsed.types["engine_requests"], "counter")
        self.assertEqual(parsed.units["engine_requests"], "requests")
        point = parsed.points[0]
        self.assertEqual(point.metric_name, "engine_requests_total")
        self.assertEqual(point.labels, {"model": 'm"1', "worker": "w0"})
        self.assertEqual(point.help, "Native requests")
        self.assertEqual(point.declared_type, "counter")
        self.assertEqual(point.declared_unit, "requests")

    def test_parser_inherits_histogram_family_metadata_for_sum_count_bucket(self):
        parsed = parse_prometheus(
            b"# HELP phase_seconds Phase duration\n"
            b"# TYPE phase_seconds histogram\n"
            b"# UNIT phase_seconds seconds\n"
            b"phase_seconds_bucket{le=\"1\"} 2\n"
            b"phase_seconds_sum 3\n"
            b"phase_seconds_count 2\n"
        )
        self.assertEqual(
            [(point.help, point.declared_type, point.declared_unit) for point in parsed.points],
            [("Phase duration", "histogram", "seconds")] * 3,
        )

    def test_parser_rejects_nonfinite_duplicate_and_timestamps(self):
        bad = (
            b"x NaN\n",
            b"x{a=\"b\"} 1\nx{a=\"b\"} 2\n",
            b"x 1 1700000000\n",
        )
        for body in bad:
            with self.subTest(body=body), self.assertRaises(SamplerError):
                parse_prometheus(body)

    def test_parser_checks_deadline_within_label_loop_and_bounds_lines(self):
        calls = 0

        def deadline_check():
            nonlocal calls
            calls += 1
            if calls == 4:
                raise TimeoutError("synthetic parse deadline")

        labels = ",".join(f'l{i}="v"' for i in range(100))
        with self.assertRaisesRegex(TimeoutError, "synthetic parse deadline"):
            parse_prometheus(f"g{{{labels}}} 1\n".encode(), deadline_check=deadline_check)
        with self.assertRaisesRegex(SamplerError, "line too long"):
            parse_prometheus(("g " + "1" * 65_536 + "\n").encode())

    def test_http_is_direct_loopback_deadline_bounded_and_no_redirect(self):
        base = f"http://127.0.0.1:{self.server.server_port}"
        scraper = localhost_http_scraper(base + "/metrics")
        self.assertEqual(scraper(time.monotonic_ns() + 1_000_000_000), VALID)
        with self.assertRaises(SamplerError):
            localhost_http_scraper(base + "/redirect")(time.monotonic_ns() + 1_000_000_000)
        with self.assertRaises(TimeoutError):
            localhost_http_scraper(base + "/slow")(time.monotonic_ns() + 20_000_000)
        for path in ("/slow-header", "/slow-body"):
            started = time.monotonic()
            with self.subTest(path=path), self.assertRaises(TimeoutError):
                localhost_http_scraper(base + path)(time.monotonic_ns() + 40_000_000)
            self.assertLess(time.monotonic() - started, 0.20)
        with self.assertRaises(SamplerError):
            localhost_http_scraper(base + "/large", max_body_bytes=1024)(time.monotonic_ns() + 1_000_000_000)
        with self.assertRaises(SamplerError):
            localhost_http_scraper(base + "/eof-large", max_body_bytes=1024)(time.monotonic_ns() + 1_000_000_000)
        with self.assertRaises(ValueError):
            localhost_http_scraper(base + "/metrics", max_body_bytes=True)
        for invalid in ("http://localhost:9/metrics", "https://127.0.0.1:9/metrics", "http://example.com:9/metrics"):
            with self.assertRaises(ValueError):
                localhost_http_scraper(invalid)

    def test_exact_slots_missing_errors_raw_bytes_modes_and_hashes(self):
        clock = FakeClock()
        calls = iter((VALID, b"# TYPE engine_requests counter\nengine_requests_total{model=\"m\\\"1\",worker=\"w0\"} 8\n", RuntimeError("offline")))

        def scrape(_deadline):
            value = next(calls)
            if isinstance(value, BaseException):
                raise value
            return value

        with tempfile.TemporaryDirectory(dir="/private/tmp") as parent:
            root = Path(parent) / "private"
            sampler = NativeSampler(
                binding=binding(), metrics=specs(), scrape=scrape,
                identity_probe=lambda _deadline: ("pid:123", "linux:123:456"),
                store=PrivateEvidenceStore(root), interval_ns=10,
                scrape_timeout_ns=100, finalize_reserve_ns=10,
                monotonic_ns=clock.monotonic_ns, utc_ns=clock.time_ns,
            )
            sampler.collect_schedule(1_010, 1_025, 2_000)
            self.assertEqual([r["scheduled_monotonic_ns"] for r in sampler.records], [1010, 1020, 1025])
            second = json.loads(Path(sampler.records[1]["private_path"]).read_bytes())
            third = json.loads(Path(sampler.records[2]["private_path"]).read_bytes())
            self.assertEqual(second["native_samples"][1]["status"], "missing")
            self.assertEqual(third["native_samples"][0]["status"], "error")
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
            for record in sampler.records:
                path = Path(record["private_path"])
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                encoded = path.read_bytes()
                self.assertEqual(hashlib.sha256(encoded).hexdigest(), record["file_sha256"])
                persisted = json.loads(encoded)
                raw = base64.b64decode(persisted["raw_base64"], validate=True)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), persisted["raw_sha256"])
                self.assertEqual(persisted["binding"]["run_id"], "run-1")
                self.assertGreaterEqual(persisted["clock_uncertainty_ns"], 0)

    def test_counter_reset_is_retained_and_existing_summarizer_rejects_it(self):
        clock = FakeClock()
        values = iter((7, 3))

        def scrape(_deadline):
            value = next(values)
            return f"# HELP c Native counter\n# TYPE c counter\nc {value}\n".encode()

        with tempfile.TemporaryDirectory(dir="/private/tmp") as parent:
            sampler = NativeSampler(
                binding=binding(), metrics=(MetricSpec("counter", "c", {}, "1"),),
                scrape=scrape, identity_probe=lambda _deadline: ("pid:123", "linux:123:456"),
                store=PrivateEvidenceStore(Path(parent) / "p"),
                interval_ns=10, scrape_timeout_ns=100,
                finalize_reserve_ns=10,
                monotonic_ns=clock.monotonic_ns, utc_ns=clock.time_ns,
            )
            sampler.collect_schedule(1_010, 1_020, 2_000)
            self.assertEqual(sampler.records[1]["counter_reset_count"], 1)
            first = sampler.samples[0]["monotonic_ns"]
            last = sampler.samples[-1]["monotonic_ns"]
            result = sampler.summarize(
                Window("host-boot-a", first, last, 10_000, "pid:123", "linux:123:456", "vllm", "block-a"),
                MetricSpec("counter", "c", {}, "1"),
            )
            self.assertFalse(result["available"])
            self.assertEqual(result["unavailable_reason"], "counter_decreased")

    def test_explicit_start_stop_joins_and_captures_exact_drain(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as parent:
            now = time.monotonic_ns()
            sampler = NativeSampler(
                binding=binding(), metrics=(MetricSpec("gauge", "g", {}, "1"),),
                scrape=lambda _deadline: b"# HELP g Native gauge\n# TYPE g gauge\ng 1\n",
                identity_probe=lambda _deadline: ("pid:123", "linux:123:456"),
                store=PrivateEvidenceStore(Path(parent) / "p"), interval_ns=10_000_000,
                scrape_timeout_ns=50_000_000, reap_reserve_ns=100_000_000,
                finalize_reserve_ns=100_000_000,
            )
            hard = now + 1_000_000_000
            sampler.start(start_ns=now, hard_deadline_ns=hard)
            time.sleep(0.025)
            drain = time.monotonic_ns()
            sampler.stop(drain_ns=drain, join_deadline_ns=hard - 100_000_000)
            self.assertFalse(sampler._thread.is_alive())
            slots = [r["scheduled_monotonic_ns"] for r in sampler.records]
            self.assertEqual(slots[-1], drain)
            self.assertEqual(slots, sorted(set(slots)))

    def test_late_injected_scraper_becomes_error_record(self):
        clock = FakeClock()

        def late(_deadline):
            clock.mono += 1_000
            return VALID

        with tempfile.TemporaryDirectory(dir="/private/tmp") as parent:
            sampler = NativeSampler(
                binding=binding(), metrics=specs(), scrape=late,
                identity_probe=lambda _deadline: ("pid:123", "linux:123:456"),
                store=PrivateEvidenceStore(Path(parent) / "p"), interval_ns=10,
                scrape_timeout_ns=5, finalize_reserve_ns=1,
                monotonic_ns=clock.monotonic_ns, utc_ns=clock.time_ns,
            )
            record = sampler.sample_slot(1_000, 2_000)
            self.assertEqual(record["scrape_status"], "error")
            persisted = json.loads(Path(record["private_path"]).read_bytes())
            self.assertEqual(persisted["native_samples"][0]["reason"], "scrape_failed")

    def test_parse_completion_is_checked_against_absolute_scrape_deadline(self):
        clock = FakeClock()
        real_parse = parse_prometheus

        def late_parse(raw, **_kwargs):
            parsed = real_parse(raw)
            clock.mono += 1_000
            return parsed

        with tempfile.TemporaryDirectory(dir="/private/tmp") as parent:
            sampler = NativeSampler(
                binding=binding(), metrics=specs(), scrape=lambda _deadline: VALID,
                identity_probe=lambda _deadline: ("pid:123", "linux:123:456"),
                store=PrivateEvidenceStore(Path(parent) / "p"), interval_ns=10,
                scrape_timeout_ns=100, finalize_reserve_ns=10,
                monotonic_ns=clock.monotonic_ns, utc_ns=clock.time_ns,
            )
            with mock.patch("runpod_benchmark.native_sampler.parse_prometheus", side_effect=late_parse):
                receipt = sampler.sample_slot(1_000, 2_000)
            persisted = json.loads(Path(receipt["private_path"]).read_bytes())
            self.assertEqual(persisted["scrape_reason"], "scrape_failed")
            self.assertEqual(base64.b64decode(persisted["raw_base64"]), VALID)

    def test_missed_slots_are_records_without_back_to_back_catchup_scrapes(self):
        calls = 0

        def slow_scrape(_deadline):
            nonlocal calls
            calls += 1
            time.sleep(0.03)
            return b"# TYPE g gauge\ng 1\n"

        with tempfile.TemporaryDirectory(dir="/private/tmp") as parent:
            now = time.monotonic_ns()
            sampler = NativeSampler(
                binding=binding(), metrics=(MetricSpec("gauge", "g"),), scrape=slow_scrape,
                identity_probe=lambda _deadline: ("pid:123", "linux:123:456"),
                store=PrivateEvidenceStore(Path(parent) / "p"), interval_ns=10_000_000,
                scrape_timeout_ns=100_000_000, reap_reserve_ns=100_000_000,
                finalize_reserve_ns=100_000_000,
            )
            hard = now + 2_000_000_000
            sampler.start(start_ns=now, hard_deadline_ns=hard)
            time.sleep(0.075)
            drain = time.monotonic_ns()
            sampler.stop(drain_ns=drain, join_deadline_ns=hard - 100_000_000)
            persisted = [json.loads(Path(r["private_path"]).read_bytes()) for r in sampler.records]
            missed = [r for r in persisted if r["scrape_reason"] == "scheduled_slot_missed"]
            self.assertTrue(missed)
            self.assertLess(calls, len(persisted))
            self.assertTrue(all(r["raw_base64"] == "" for r in missed))
            self.assertEqual(persisted[-1]["scheduled_monotonic_ns"], drain)

    def test_identity_is_checked_each_scrape_and_mismatch_is_unsupported(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as parent:
            sampler = NativeSampler(
                binding=binding(), metrics=(MetricSpec("gauge", "g"),),
                scrape=lambda _deadline: b"# TYPE g gauge\ng 1\n",
                identity_probe=lambda _deadline: ("pid:999", "linux:999:1"),
                store=PrivateEvidenceStore(Path(parent) / "p"), interval_ns=10,
                scrape_timeout_ns=1_000_000, finalize_reserve_ns=1_000_000,
            )
            receipt = sampler.sample_slot(time.monotonic_ns(), time.monotonic_ns() + 10_000_000)
            persisted = json.loads(Path(receipt["private_path"]).read_bytes())
            self.assertEqual(persisted["scrape_reason"], "identity_changed")
            self.assertEqual(persisted["native_samples"][0]["status"], "unsupported")

    def test_clocks_reject_bool_float_and_backward_values(self):
        for invalid in (lambda: True, lambda: 1.5):
            with tempfile.TemporaryDirectory(dir="/private/tmp") as parent:
                sampler = NativeSampler(
                    binding=binding(), metrics=(MetricSpec("gauge", "g"),), scrape=lambda _d: b"g 1\n",
                    identity_probe=lambda _deadline: ("pid:123", "linux:123:456"),
                    store=PrivateEvidenceStore(Path(parent) / "p"), interval_ns=10,
                    scrape_timeout_ns=10, monotonic_ns=invalid,
                )
                with self.assertRaises(SamplerError):
                    sampler._monotonic()
        with tempfile.TemporaryDirectory(dir="/private/tmp") as parent:
            values = iter((10, 9))
            sampler = NativeSampler(
                binding=binding(), metrics=(MetricSpec("gauge", "g"),), scrape=lambda _d: b"g 1\n",
                identity_probe=lambda _deadline: ("pid:123", "linux:123:456"),
                store=PrivateEvidenceStore(Path(parent) / "p"), interval_ns=10,
                scrape_timeout_ns=10, monotonic_ns=lambda: next(values),
            )
            self.assertEqual(sampler._monotonic(), 10)
            with self.assertRaises(SamplerError):
                sampler._monotonic()

    def test_store_rejects_reuse_and_symlink_parent_and_handles_partial_write(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as parent:
            existing = Path(parent) / "existing"
            existing.mkdir()
            with self.assertRaises(ValueError):
                PrivateEvidenceStore(existing)
            real_parent = Path(parent) / "real"
            real_parent.mkdir()
            link = Path(parent) / "link"
            link.symlink_to(real_parent, target_is_directory=True)
            with self.assertRaises(ValueError):
                PrivateEvidenceStore(link / "child")
            store = PrivateEvidenceStore(Path(parent) / "new")
            real_write = os.write

            def partial_write(fd, data):
                return real_write(fd, bytes(data[:max(1, len(data) // 3)]))

            with mock.patch("runpod_benchmark.native_sampler.os.write", side_effect=partial_write):
                path, digest = store.persist(1, {"raw": "abcdef"})
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
            self.assertEqual(json.loads(path.read_bytes()), {"raw": "abcdef"})

    def test_total_raw_bound_commits_error_receipt_then_fails_closed(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as parent:
            sampler = NativeSampler(
                binding=binding(), metrics=(MetricSpec("gauge", "g"),),
                scrape=lambda _deadline: b"# TYPE g gauge\ng 1\n",
                identity_probe=lambda _deadline: ("pid:123", "linux:123:456"),
                store=PrivateEvidenceStore(Path(parent) / "p"), interval_ns=10,
                scrape_timeout_ns=1_000_000, finalize_reserve_ns=1_000_000,
                max_total_raw_bytes=1,
                max_total_artifact_bytes=100_000,
            )
            with self.assertRaisesRegex(SamplerError, "retention bound"):
                sampler.sample_slot(time.monotonic_ns(), time.monotonic_ns() + 10_000_000)
            self.assertEqual(len(sampler.records), 1)
            persisted = json.loads(Path(sampler.records[0]["private_path"]).read_bytes())
            self.assertEqual(persisted["scrape_reason"], "evidence_limit_reached")
            self.assertEqual(persisted["raw_base64"], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
