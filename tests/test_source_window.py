"""Stdlib-unittest integration coverage for the Episode 1 source-window seam."""
from __future__ import annotations

import hashlib
import json
import unittest

try:
    from runpod_benchmark.source_window import (
        SourceWindowError, canonical, summarize_system_source_window,
    )
    from runpod_benchmark.system_sampler import Binding, ProcessTarget, SystemSampler
except ImportError:
    from source_window import SourceWindowError, canonical, summarize_system_source_window
    from system_sampler import Binding, ProcessTarget, SystemSampler


PLAN = "a" * 64
BOOT = "11111111-2222-3333-4444-555555555555"
LABELS = {"source": "proc", "unit": "bytes", "scope": "process"}


def _record(seq, slot, phase, observed, gauge, counter, *, pid=77):
    metrics = [{"source":"proc", "name":name, "unit":"bytes", "scope":"process",
                "value":value, "status":"ok", "reason":None}
               for name,value in (("rss_bytes",gauge),("io_bytes_total",counter))]
    return {"schema_version":"episode1.system-sample.v1",
            "binding":{"run_id":"run","attempt_id":"attempt","block":"b1",
                       "clock_domain":"linux-clock-monotonic","source_boot_id":BOOT},
            "sequence":seq,"phase":phase,"slot_kind":slot,
            "scheduled_monotonic_ns":observed-20,"sample_start_monotonic_ns":observed-10,
            "observed_monotonic_ns":observed,"observed_utc_ns":100000+observed,
            "clock_uncertainty_ns":2,"schedule_lag_ns":10,"missed_slots":0,
            "observed_gap_ns":None if seq == 1 else 100,
            "process_expected":None if pid is None else {"pid":pid,"start_ticks":9,"role":"vllm-0.29.0"},
            "process_identity_before":None if pid is None else [pid,9],
            "process_identity_after":None if pid is None else [pid,9],
            "process_identity_status":"prestart" if pid is None else "ok","metrics":metrics}


def _case(*, counter=(10,12,15), metric="rss_bytes", kind="gauge"):
    rows = [_record(1,"periodic","warmup",100,1,5,pid=None),
            _record(2,"measurement_start_boundary","measurement",200,20,counter[0]),
            _record(3,"periodic","measurement",300,30,counter[1]),
            _record(4,"measurement_end_boundary","measurement",400,40,counter[2]),
            _record(5,"periodic","drain",500,2,20,pid=None)]
    source = b"".join(canonical(row)+b"\n" for row in rows)
    def receipt(row, marker, started, completed):
        return {"schema_version":"episode1.system-window-boundary.v1","plan_sha256":PLAN,
                "run_id":"run","attempt_id":"attempt","block":"b1","runtime":"vllm-0.29.0",
                "marker":marker,"source_clock_domain":"linux-clock-monotonic","source_boot_id":BOOT,
                "source_sequence":row["sequence"],
                "source_record_sha256":hashlib.sha256(canonical(row)+b"\n").hexdigest(),
                "source_observed_monotonic_ns":row["observed_monotonic_ns"],
                "source_observed_utc_ns":row["observed_utc_ns"],
                "source_utc_uncertainty_ns":row["clock_uncertainty_ns"],
                "client_clock_domain":"client_monotonic_ns",
                "client_call_started_monotonic_ns":started,
                "client_call_completed_monotonic_ns":completed}
    args = {"source":source,
            "start_receipt":receipt(rows[1],"measurement_start",1000,1100),
            "end_receipt":receipt(rows[3],"measurement_end",4900,5000),
            "plan_sha256":PLAN,"run_id":"run","attempt_id":"attempt","block":"b1",
            "runtime":"vllm-0.29.0","pid":77,"start_ticks":9,"metric_name":metric,
            "kind":kind,"labels":LABELS,"max_sampling_gap_ns":200,
            "first_measured_a_ns":1200,"last_measured_end_ns":4800}
    return rows,args


def _rebuild(args, rows):
    args["source"] = b"".join(canonical(row)+b"\n" for row in rows)


class SourceWindowTests(unittest.TestCase):
    def test_gauge_and_counter_are_derived_from_selected_remote_interval(self):
        _,args = _case()
        gauge = summarize_system_source_window(**args)
        self.assertEqual(gauge["value"], {"minimum":20.0,"maximum":40.0,"mean":30.0})
        self.assertEqual((gauge["expected_samples"],gauge["observed_samples"]),(3,3))
        _,args = _case(metric="io_bytes_total",kind="counter")
        counter = summarize_system_source_window(**args)
        self.assertEqual(counter["value"]["delta"],5.0)
        self.assertEqual(counter["observation_window"]["association"],
                         "causal_enclosure_no_clock_mapping")

    def test_counter_reset_is_explicitly_unavailable(self):
        _,args = _case(counter=(10,9,15),metric="io_bytes_total",kind="counter")
        result = summarize_system_source_window(**args)
        self.assertEqual((result["status"],result["unavailable_reason"]),
                         ("unavailable","counter_reset"))

    def test_rejects_bool_identity_values(self):
        mutations = [lambda rows: rows[2]["process_expected"].update(pid=True),
                     lambda rows: rows[2]["process_expected"].update(start_ticks=False),
                     lambda rows: rows[2].update(process_identity_before=[True,9]),
                     lambda rows: rows[2].update(process_identity_after=[77,False])]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                rows,args = _case(); mutate(rows); _rebuild(args,rows)
                with self.assertRaises(SourceWindowError): summarize_system_source_window(**args)

    def test_rejects_extra_or_swapped_boundary_markers(self):
        rows,args = _case(); rows[0].update(slot_kind="measurement_start_boundary",phase="measurement"); _rebuild(args,rows)
        with self.assertRaises(SourceWindowError): summarize_system_source_window(**args)
        rows,args = _case(); rows[1]["slot_kind"],rows[3]["slot_kind"] = rows[3]["slot_kind"],rows[1]["slot_kind"]; _rebuild(args,rows)
        with self.assertRaises(SourceWindowError): summarize_system_source_window(**args)

    def test_rejects_gap_boot_phase_identity_and_client_causality_tamper(self):
        mutations = [lambda rows,args: rows[2].update(observed_gap_ns=99),
                     lambda rows,args: rows[0].update(observed_gap_ns=0),
                     lambda rows,args: rows[2]["binding"].update(source_boot_id="other-boot"),
                     lambda rows,args: rows[2].update(phase="warmup"),
                     lambda rows,args: rows[2]["process_expected"].update(role="sglang-0.5.20"),
                     lambda rows,args: rows[2].update(process_identity_after=[78,9]),
                     lambda rows,args: args.update(first_measured_a_ns=1000),
                     lambda rows,args: args.update(last_measured_end_ns=5000)]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                rows,args = _case(); mutate(rows,args); _rebuild(args,rows)
                with self.assertRaises(SourceWindowError): summarize_system_source_window(**args)

    def test_rejects_contradictory_metric_status_value_and_reason(self):
        mutations = [
            lambda metric: metric.update(status="ok", reason="unexpected"),
            lambda metric: metric.update(status="unavailable", value=3, reason="not_reported"),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                rows,args = _case()
                metric = next(item for item in rows[2]["metrics"] if item["name"] == "rss_bytes")
                mutate(metric)
                _rebuild(args,rows)
                with self.assertRaises(SourceWindowError):
                    summarize_system_source_window(**args)

    def test_accepts_truthful_slow_final_clock_bracket(self):
        rows,args = _case()
        rows[1].update(observed_monotonic_ns=250, clock_uncertainty_ns=100,
                       observed_gap_ns=150)
        rows[2]["observed_gap_ns"] = 50
        receipt = args["start_receipt"]
        receipt.update(source_observed_monotonic_ns=250,
                       source_utc_uncertainty_ns=100,
                       source_record_sha256=hashlib.sha256(canonical(rows[1])+b"\n").hexdigest())
        _rebuild(args,rows)
        result = summarize_system_source_window(**args)
        self.assertEqual(result["status"],"available")


class _Clock:
    def __init__(self): self.n = 1000
    def __call__(self): self.n += 10; return self.n
class _Proc:
    def identity(self,target): return (target.pid,target.start_ticks)
    def collect(self,target):
        return ([{"source":"proc","name":"rss_bytes","unit":"bytes","scope":"process",
                  "value":10,"status":"ok","reason":None}],(target.pid,target.start_ticks))
class _GPU:
    def collect(self,deadline): return []


class BoundarySamplerTests(unittest.TestCase):
    def test_synchronous_boundary_markers_are_ordered_and_closed(self):
        clock = _Clock()
        sampler = SystemSampler(Binding("run","attempt","b1","boot-id"),_GPU(),_Proc(),
                                interval_ns=1000,command_budget_ns=100,
                                monotonic_ns=clock,utc_ns=lambda:5000)
        target = ProcessTarget(7,9,"runtime")
        start = sampler.sample_boundary(target,"measurement_start",hard_deadline_ns=10000)
        end = sampler.sample_boundary(target,"measurement_end",hard_deadline_ns=10000)
        self.assertEqual(start["slot_kind"],"measurement_start_boundary")
        self.assertEqual(end["slot_kind"],"measurement_end_boundary")
        self.assertGreater(end["scheduled_monotonic_ns"],start["scheduled_monotonic_ns"])
        self.assertEqual(end["observed_gap_ns"],
                         end["observed_monotonic_ns"]-start["observed_monotonic_ns"])
        with self.assertRaises(ValueError):
            sampler.sample_boundary(target,"bad",hard_deadline_ns=10000)

    def test_boundary_then_immediate_periodic_never_claims_future_slot(self):
        clock = _Clock()
        sampler = SystemSampler(Binding("run","attempt","b1","boot-id"),_GPU(),_Proc(),
                                interval_ns=1000,command_budget_ns=100,
                                monotonic_ns=clock,utc_ns=lambda:5000)
        target = ProcessTarget(7,9,"runtime")
        boundary = sampler.sample_boundary(target,"measurement_start",hard_deadline_ns=10000)
        periodic = sampler.sample_periodic(target,"measurement",hard_deadline_ns=10000)
        self.assertGreater(periodic["scheduled_monotonic_ns"],boundary["scheduled_monotonic_ns"])
        self.assertLessEqual(periodic["scheduled_monotonic_ns"],periodic["sample_start_monotonic_ns"])


if __name__ == "__main__":
    unittest.main()
