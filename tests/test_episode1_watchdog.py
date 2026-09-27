from __future__ import annotations
import json, os, signal, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from episode1_watchdog import (
    WatchdogError, ProcessLauncher, atomic_json, build_guard_commands,
    observe_clock_domain, persist_authority, prepare_launch, read_authority, read_permit,
    restart_cleanup, run_guard, worker_binding_document,
)

D = "a" * 64

class Clock:
    def __init__(self, value=1.0): self.value = value
    def now(self): return self.value
    def sleep(self, seconds): self.value += seconds

class Provider:
    def __init__(self, verified=True):
        self.verified = verified; self.calls=[]
    def poll_owned(self, authority, *, deadline_monotonic):
        self.calls.append(("poll", authority.private_id, deadline_monotonic)); return True
    def delete_owned(self, authority, *, deadline_monotonic):
        self.calls.append(("delete", authority.private_id, deadline_monotonic)); return self.verified
    def inventory_absent(self, authority, *, deadline_monotonic):
        self.calls.append(("inventory", authority.private_id, deadline_monotonic)); return self.verified
    def direct_not_found(self, authority, *, deadline_monotonic):
        self.calls.append(("direct", authority.private_id, deadline_monotonic)); return self.verified

class Tests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(); self.root=Path(self.t.name)
        self.entry = self.root/"entry.py"; self.entry.write_text("# entry\n"); os.chmod(self.entry, 0o600)
        self.adapter = self.root/"adapter.py"; self.adapter.write_text("# adapter\n"); os.chmod(self.adapter, 0o600)
        self.library = ROOT / "scripts" / "episode1_watchdog.py"
        self.restart_entry = ROOT / "scripts" / "restart_cleanup_entry.py"
    def tearDown(self): self.t.cleanup()

    def permit(self, clock=None):
        clock = clock or Clock()
        return prepare_launch(directory=self.root/"state", plan_sha256=D,
            watchdog_plan_sha256="b"*64, unique_name="episode1-x", ownership_token="secret",
            original_t0_monotonic=0, arm_deadline_monotonic=5,
            teardown_deadline_monotonic=8, hard_deadline_monotonic=12,
            clock_domain="boot-1", entrypoint=self.entry, library_path=self.library,
            restart_entrypoint=self.restart_entry, adapter_source=self.adapter,
            now=clock.now, run_nonce="c"*64)

    def authority(self, permit):
        return persist_authority(self.root/"state"/"authority.json", permit,
            private_id="pod-1", unique_name="episode1-x", ownership_token="secret",
            billing_started_monotonic=1.2)

    def test_command_builder_produces_two_inhibited_role_commands(self):
        commands,inhibitor=build_guard_commands(python=Path(sys.executable),entrypoint=self.entry,
            state_directory=self.root/"state",guard_directory=self.root/"guard",
            adapter_spec="adapter:make",adapter_source=self.adapter,heartbeat_seconds=2,
            poll_timeout_seconds=1,
            retry_delays=(0,1),sleep_preventer=("/usr/bin/caffeinate","-dimsu","-w","{worker_pid}"))
        self.assertEqual(set(commands),{"primary","secondary"})
        self.assertEqual(commands["primary"][0],sys.executable)
        self.assertEqual(inhibitor[-1],"{worker_pid}")
        self.assertIn("primary",commands["primary"]); self.assertIn("secondary",commands["secondary"])
        self.assertNotEqual(commands["primary"],commands["secondary"])

    def test_clock_domain_observation_uses_boot_identity(self):
        boot=b"12345678-1234-1234-1234-123456789abc\n"
        with mock.patch("episode1_watchdog.sys.platform","linux"), \
             mock.patch("episode1_watchdog.Path.read_bytes",return_value=boot):
            self.assertEqual(observe_clock_domain(),
                "linux-boot-id:12345678-1234-1234-1234-123456789abc:monotonic")
        result=SimpleNamespace(stdout="{ sec = 123, usec = 456 } Mon Jan  1 00:00:00 2024\n")
        with mock.patch("episode1_watchdog.sys.platform","darwin"), \
             mock.patch("episode1_watchdog.subprocess.run",return_value=result) as run:
            self.assertEqual(observe_clock_domain(),"darwin-kern-boottime:123:456:monotonic")
            run.assert_called_once_with(("/usr/sbin/sysctl","-n","kern.boottime"),
                check=True,capture_output=True,text=True,timeout=2.0)

    def test_atomic_json_full_write_exclusive_and_symlink_parent(self):
        target=self.root/"state"/"one.json"; real_write=os.write
        def partial(fd,data): return real_write(fd,data[:3])
        with mock.patch("episode1_watchdog.os.write",side_effect=partial):
            atomic_json(target,{"large":"x"*100},exclusive=True)
        self.assertEqual(json.loads(target.read_text()),{"large":"x"*100})
        with self.assertRaises(FileExistsError):
            atomic_json(target,{"large":"replacement"},exclusive=True)
        self.assertEqual(json.loads(target.read_text()),{"large":"x"*100})
        actual=self.root/"actual"; actual.mkdir(mode=0o700)
        linked=self.root/"linked"; linked.symlink_to(actual,target_is_directory=True)
        with self.assertRaisesRegex(WatchdogError,"real directory"):
            atomic_json(linked/"bad.json",{"x":1},exclusive=True)

    def test_precreate_permit_binds_exact_sources_and_expires(self):
        permit=self.permit(); self.assertEqual(permit.entrypoint_sha256,
            __import__('hashlib').sha256(b"# entry\n").hexdigest())
        self.entry.write_text("changed")
        authority=self.authority(permit)
        atomic_json(self.root/"state"/"worker-binding.json",
            worker_binding_document(permit=permit, authority=authority, guard_binding_sha256=D), exclusive=True)
        with self.assertRaisesRegex(WatchdogError, "entrypoint bytes"):
            run_guard(role="primary", permit_path=self.root/"state"/"launch-permit.json",
                authority_path=self.root/"state"/"authority.json",
                binding_path=self.root/"state"/"worker-binding.json", entrypoint_path=self.entry,
                library_path=self.library, adapter_source=self.adapter, provider=Provider(), heartbeat_seconds=1,
                retry_delays=(0,), clock_domain=lambda:"boot-1",
                monotonic=Clock().now, sleep=lambda _:None, pid=50)
        with self.assertRaisesRegex(WatchdogError, "expired"):
            prepare_launch(directory=self.root/"late", plan_sha256=D, watchdog_plan_sha256="b"*64,
                unique_name="x", ownership_token="y", original_t0_monotonic=0,
                arm_deadline_monotonic=5, teardown_deadline_monotonic=8,
                hard_deadline_monotonic=12, clock_domain="boot-1", entrypoint=self.entry,
                library_path=self.library, restart_entrypoint=self.restart_entry,
                adapter_source=self.adapter, now=lambda:5)

    def test_authority_is_closed_private_and_tamper_rejected(self):
        p=self.permit(); a=self.authority(p)
        self.assertEqual((self.root/"state"/"authority.json").stat().st_mode & 0o777, 0o600)
        value=a.document; value["private_id"]="other"; value["extra"]=1
        atomic_json(self.root/"state"/"authority.json", value)
        with self.assertRaisesRegex(WatchdogError, "open or incomplete"):
            read_authority(self.root/"state"/"authority.json", p)

    def test_guard_emits_fresh_compatible_receipts_and_verified_cleanup(self):
        p=self.permit(); a=self.authority(p)
        atomic_json(self.root/"state"/"worker-binding.json",
            worker_binding_document(permit=p, authority=a, guard_binding_sha256=D), exclusive=True)
        clock=Clock(); provider=Provider()
        result=run_guard(role="primary", permit_path=self.root/"state"/"launch-permit.json",
            authority_path=self.root/"state"/"authority.json",
            binding_path=self.root/"state"/"worker-binding.json", entrypoint_path=self.entry,
            library_path=self.library, adapter_source=self.adapter, provider=provider, heartbeat_seconds=2,
            retry_delays=(0,), clock_domain=lambda:"boot-1",
            monotonic=clock.now, sleep=clock.sleep, pid=50)
        self.assertTrue(result["verified"])
        armed=json.loads((self.root/"state"/"armed-primary.json").read_text())
        pulse=json.loads((self.root/"state"/"heartbeat-primary.json").read_text())
        self.assertEqual(armed["schema_version"], "episode1.guard-armed.v1")
        self.assertEqual(pulse["schema_version"], "episode1.guard-heartbeat.v1")
        self.assertEqual(armed["binding_sha256"], D)
        self.assertLess(pulse["observed_monotonic"], p.teardown_deadline_monotonic)
        self.assertEqual({c[0] for c in provider.calls}, {"poll","delete","inventory","direct"})

    def test_guard_rejects_changed_observed_clock_domain_before_provider_call(self):
        p=self.permit(); a=self.authority(p); provider=Provider()
        atomic_json(self.root/"state"/"worker-binding.json",
            worker_binding_document(permit=p, authority=a, guard_binding_sha256=D), exclusive=True)
        with self.assertRaisesRegex(WatchdogError, "clock domain changed"):
            run_guard(role="primary", permit_path=self.root/"state"/"launch-permit.json",
                authority_path=self.root/"state"/"authority.json",
                binding_path=self.root/"state"/"worker-binding.json", entrypoint_path=self.entry,
                library_path=self.library, adapter_source=self.adapter, provider=provider,
                heartbeat_seconds=2, poll_timeout_seconds=1, retry_delays=(0,),
                clock_domain=lambda:"boot-2", monotonic=Clock().now, sleep=lambda _:None, pid=50)
        self.assertEqual(provider.calls, [])

    def test_every_ownership_poll_uses_finite_timeout_under_original_ceiling(self):
        p=self.permit(); a=self.authority(p); clock=Clock(); starts=[]
        atomic_json(self.root/"state"/"worker-binding.json",
            worker_binding_document(permit=p, authority=a, guard_binding_sha256=D), exclusive=True)
        class SlowPoll(Provider):
            def poll_owned(inner, authority, *, deadline_monotonic):
                starts.append((clock.now(), deadline_monotonic))
                inner.calls.append(("poll", authority.private_id, deadline_monotonic))
                if len(starts) > 1:
                    clock.value = deadline_monotonic
                return True
        provider=SlowPoll()
        result=run_guard(role="primary", permit_path=self.root/"state"/"launch-permit.json",
            authority_path=self.root/"state"/"authority.json",
            binding_path=self.root/"state"/"worker-binding.json", entrypoint_path=self.entry,
            library_path=self.library, adapter_source=self.adapter, provider=provider,
            heartbeat_seconds=2, poll_timeout_seconds=1, retry_delays=(0,),
            clock_domain=lambda:"boot-1", monotonic=clock.now, sleep=clock.sleep, pid=50)
        self.assertTrue(result["verified"])
        self.assertGreater(len(starts), 1)
        self.assertTrue(all(0 < deadline-start <= 1 for start,deadline in starts))
        self.assertLessEqual(starts[0][1], p.arm_deadline_monotonic)
        self.assertTrue(all(deadline <= p.teardown_deadline_monotonic
                            for _,deadline in starts[1:]))
        self.assertFalse((self.root/"state"/"heartbeat-primary.json").exists())

    def test_owned_lifetime_armed_write_failure_cleans_once_after_trust_gates(self):
        p=self.permit(); a=self.authority(p); provider=Provider(); clock=Clock()
        binding_path=self.root/"state"/"worker-binding.json"
        atomic_json(binding_path,
            worker_binding_document(permit=p, authority=a, guard_binding_sha256=D), exclusive=True)
        real_atomic=atomic_json; failed=False
        def fail_armed_once(path, value, **kwargs):
            nonlocal failed
            if path.name == "armed-primary.json" and not failed:
                failed=True
                raise OSError("forced receipt failure")
            return real_atomic(path, value, **kwargs)
        with mock.patch("episode1_watchdog.atomic_json", side_effect=fail_armed_once):
            with self.assertRaisesRegex(OSError, "forced receipt failure"):
                run_guard(role="primary", permit_path=self.root/"state"/"launch-permit.json",
                    authority_path=self.root/"state"/"authority.json", binding_path=binding_path,
                    entrypoint_path=self.entry, library_path=self.library,
                    adapter_source=self.adapter, provider=provider, heartbeat_seconds=2,
                    poll_timeout_seconds=1, retry_delays=(0,), clock_domain=lambda:"boot-1",
                    monotonic=clock.now, sleep=clock.sleep, pid=50)
        self.assertEqual([c[0] for c in provider.calls].count("delete"), 1)
        self.assertTrue(json.loads((self.root/"state"/"cleanup-primary.json").read_text())["verified"])

    def test_owned_lifetime_nonboolean_poll_cleans_once(self):
        p=self.permit(); a=self.authority(p); clock=Clock()
        atomic_json(self.root/"state"/"worker-binding.json",
            worker_binding_document(permit=p, authority=a, guard_binding_sha256=D), exclusive=True)
        class NonBoolean(Provider):
            def poll_owned(inner, authority, *, deadline_monotonic):
                inner.calls.append(("poll", authority.private_id, deadline_monotonic))
                return True if len([c for c in inner.calls if c[0] == "poll"]) == 1 else "yes"
        provider=NonBoolean()
        with self.assertRaisesRegex(WatchdogError, "boolean"):
            run_guard(role="primary", permit_path=self.root/"state"/"launch-permit.json",
                authority_path=self.root/"state"/"authority.json",
                binding_path=self.root/"state"/"worker-binding.json", entrypoint_path=self.entry,
                library_path=self.library, adapter_source=self.adapter, provider=provider,
                heartbeat_seconds=2, poll_timeout_seconds=1, retry_delays=(0,),
                clock_domain=lambda:"boot-1", monotonic=clock.now, sleep=clock.sleep, pid=50)
        self.assertEqual([c[0] for c in provider.calls].count("delete"), 1)
        self.assertTrue(all(c[-1] <= p.hard_deadline_monotonic for c in provider.calls))

    def test_owned_lifetime_never_deletes_before_all_trust_gates(self):
        p=self.permit(); a=self.authority(p)
        valid=worker_binding_document(permit=p, authority=a, guard_binding_sha256=D)
        corruptions={"plan_sha256":"d"*64, "run_nonce":"e"*64,
            "allocation_id_sha256":"f"*64, "clock_domain":"other",
            "hard_deadline_monotonic":11, "teardown_deadline_monotonic":7,
            "script_sha256":"1"*64, "schema_version":"other"}
        for field,bad in corruptions.items():
            provider=Provider(); document=dict(valid); document[field]=bad
            atomic_json(self.root/"state"/"worker-binding.json", document)
            with self.assertRaisesRegex(WatchdogError, "binding"):
                run_guard(role="primary", permit_path=self.root/"state"/"launch-permit.json",
                    authority_path=self.root/"state"/"authority.json",
                    binding_path=self.root/"state"/"worker-binding.json", entrypoint_path=self.entry,
                    library_path=self.library, adapter_source=self.adapter, provider=provider,
                    heartbeat_seconds=2, poll_timeout_seconds=1, retry_delays=(0,),
                    clock_domain=lambda:"boot-1", monotonic=Clock().now, pid=50)
            self.assertEqual(provider.calls, [], field)

    def test_cleanup_receipt_failure_is_unverified_without_second_delete(self):
        p=self.permit(); a=self.authority(p); clock=Clock()
        atomic_json(self.root/"state"/"worker-binding.json",
            worker_binding_document(permit=p, authority=a, guard_binding_sha256=D), exclusive=True)
        class InitialOnly(Provider):
            def poll_owned(inner, authority, *, deadline_monotonic):
                inner.calls.append(("poll", authority.private_id, deadline_monotonic))
                return len([c for c in inner.calls if c[0] == "poll"]) == 1
        provider=InitialOnly(); real_atomic=atomic_json
        def fail_cleanup(path, value, **kwargs):
            if path.name == "cleanup-primary.json":
                raise OSError("forced cleanup receipt failure")
            return real_atomic(path, value, **kwargs)
        with mock.patch("episode1_watchdog.atomic_json", side_effect=fail_cleanup):
            with self.assertRaisesRegex(WatchdogError, "cleanup is not verified"):
                run_guard(role="primary", permit_path=self.root/"state"/"launch-permit.json",
                    authority_path=self.root/"state"/"authority.json",
                    binding_path=self.root/"state"/"worker-binding.json", entrypoint_path=self.entry,
                    library_path=self.library, adapter_source=self.adapter, provider=provider,
                    heartbeat_seconds=20, poll_timeout_seconds=1, retry_delays=(0,),
                    clock_domain=lambda:"boot-1", monotonic=clock.now, sleep=clock.sleep, pid=50)
        self.assertEqual([c[0] for c in provider.calls].count("delete"), 1)

    def test_cleanup_failure_is_not_success(self):
        p=self.permit(); a=self.authority(p)
        atomic_json(self.root/"state"/"worker-binding.json",
            worker_binding_document(permit=p, authority=a, guard_binding_sha256=D), exclusive=True)
        clock=Clock()
        with self.assertRaisesRegex(WatchdogError, "not verified"):
            run_guard(role="secondary", permit_path=self.root/"state"/"launch-permit.json",
                authority_path=self.root/"state"/"authority.json",
                binding_path=self.root/"state"/"worker-binding.json", entrypoint_path=self.entry,
                library_path=self.library, adapter_source=self.adapter, provider=Provider(False), heartbeat_seconds=3,
                retry_delays=(0,), clock_domain=lambda:"boot-1",
                monotonic=clock.now, sleep=clock.sleep, pid=51)

    def test_restart_cleanup_only_and_original_deadline(self):
        p=self.permit(); self.authority(p); provider=Provider(); clock=Clock(9)
        receipt=restart_cleanup(permit_path=self.root/"state"/"launch-permit.json",
            authority_path=self.root/"state"/"authority.json", provider=provider,
            current_plan_sha256=D, current_clock_domain="boot-1",
            restart_entrypoint_path=self.restart_entry, library_path=self.library, monotonic=clock.now,
            sleep=clock.sleep, retry_delays=(0,), clock_domain=lambda:"boot-1")
        self.assertTrue(receipt["verified"])
        self.assertTrue(provider.calls)
        self.assertTrue(all(call[-1] == 12 for call in provider.calls))
        self.assertFalse(hasattr(provider, "create_allocation"))
        with self.assertRaisesRegex(WatchdogError, "clock domain"):
            restart_cleanup(permit_path=self.root/"state"/"launch-permit.json",
                authority_path=self.root/"state"/"authority.json", provider=provider,
                current_plan_sha256=D, current_clock_domain="boot-2",
                restart_entrypoint_path=self.restart_entry, library_path=self.library,
                monotonic=clock.now, clock_domain=lambda:"boot-1")

    def test_restart_rejects_replayed_stored_domain_when_boot_observation_changed(self):
        p=self.permit(); self.authority(p); provider=Provider()
        with self.assertRaisesRegex(WatchdogError, "independently observed"):
            restart_cleanup(permit_path=self.root/"state"/"launch-permit.json",
                authority_path=self.root/"state"/"authority.json", provider=provider,
                current_plan_sha256=D, current_clock_domain="boot-1",
                restart_entrypoint_path=self.restart_entry, library_path=self.library,
                monotonic=Clock(9).now, clock_domain=lambda:"boot-2")
        self.assertEqual(provider.calls, [])

    def test_restart_after_original_deadline_fails_without_provider_call(self):
        p=self.permit(); self.authority(p); provider=Provider(); clock=Clock(12)
        with self.assertRaisesRegex(WatchdogError, "not verified"):
            restart_cleanup(permit_path=self.root/"state"/"launch-permit.json",
                authority_path=self.root/"state"/"authority.json", provider=provider,
                current_plan_sha256=D, current_clock_domain="boot-1",
                restart_entrypoint_path=self.restart_entry, library_path=self.library, monotonic=clock.now,
                retry_delays=(0,), clock_domain=lambda:"boot-1")
        self.assertEqual(provider.calls, [])
        receipt=json.loads((self.root/"state"/"restart-cleanup.json").read_text())
        self.assertEqual(receipt["status"],"cleanup-unverified")

    def test_cleanup_proof_after_deadline_and_nonboolean_are_rejected(self):
        p=self.permit(); self.authority(p)
        class Late(Provider):
            def direct_not_found(inner, authority, *, deadline_monotonic):
                clock.value = deadline_monotonic
                return True
        clock=Clock(9)
        with self.assertRaisesRegex(WatchdogError, "not verified"):
            restart_cleanup(permit_path=self.root/"state"/"launch-permit.json",
                authority_path=self.root/"state"/"authority.json", provider=Late(),
                current_plan_sha256=D, current_clock_domain="boot-1",
                restart_entrypoint_path=self.restart_entry, library_path=self.library,
                monotonic=clock.now, sleep=clock.sleep, retry_delays=(0,),
                clock_domain=lambda:"boot-1")
        class Bad(Provider):
            def delete_owned(inner, authority, *, deadline_monotonic): return "yes"
        with self.assertRaisesRegex(WatchdogError, "not verified"):
            restart_cleanup(permit_path=self.root/"state"/"launch-permit.json",
                authority_path=self.root/"state"/"authority.json", provider=Bad(),
                current_plan_sha256=D, current_clock_domain="boot-1",
                restart_entrypoint_path=self.restart_entry, library_path=self.library,
                monotonic=Clock(9).now, retry_delays=(0,), clock_domain=lambda:"boot-1")

    def test_cleanup_never_combines_stale_success_across_attempts(self):
        p=self.permit(); self.authority(p); clock=Clock(9)
        class Stale(Provider):
            def __init__(inner): inner.attempt=0
            def delete_owned(inner, authority, *, deadline_monotonic):
                inner.attempt += 1
                if inner.attempt == 1: return True
                raise OSError("second delete failed")
            def inventory_absent(inner, authority, *, deadline_monotonic):
                raise OSError("first inventory failed")
            def direct_not_found(inner, authority, *, deadline_monotonic): return True
        with self.assertRaisesRegex(WatchdogError,"not verified"):
            restart_cleanup(permit_path=self.root/"state"/"launch-permit.json",
                authority_path=self.root/"state"/"authority.json",provider=Stale(),
                current_plan_sha256=D,current_clock_domain="boot-1",
                restart_entrypoint_path=self.restart_entry,library_path=self.library,
                monotonic=clock.now,sleep=clock.sleep,retry_delays=(0,0),
                clock_domain=lambda:"boot-1")
        receipt=json.loads((self.root/"state"/"restart-cleanup.json").read_text())
        self.assertEqual(receipt["status"],"cleanup-unverified")
        self.assertFalse(receipt["verified"])

    def test_missing_durable_authority_still_invokes_in_memory_cleanup(self):
        p=self.permit(); cleaned=[]
        command=(sys.executable,"-c","raise SystemExit(0)")
        launcher=ProcessLauncher(permit_path=self.root/"state"/"launch-permit.json",
            authority_path=self.root/"state"/"authority.json",
            commands={role:command for role in ("primary","secondary")},
            cleanup_partial=lambda deadline:cleaned.append(deadline), monotonic=Clock().now)
        binding=SimpleNamespace(sha256=D,run_nonce=p.run_nonce,
            hard_deadline_monotonic=p.hard_deadline_monotonic)
        with self.assertRaisesRegex(WatchdogError,"cannot read deletion authority"):
            launcher(binding,self.root/"guard",4)
        self.assertEqual(cleaned,[p.hard_deadline_monotonic])

    def test_partial_arm_reaps_fixture_and_invokes_cleanup(self):
        p=self.permit(); a=self.authority(p)
        fixture=self.root/"fixture.py"
        fixture.write_text('''import json,os,sys,time\nrole,directory,mode=sys.argv[1:]\nb=json.load(open(directory+"/worker-binding.json"))\nif mode=="fail": sys.exit(7)\nr={"schema_version":"episode1.guard-armed.v1","role":role,"binding_sha256":b["binding_sha256"],"run_nonce":b["run_nonce"],"pid":os.getpid(),"observed_monotonic":1.0,"initial_provider_poll_ok":True,"script_sha256":b["script_sha256"]}\nopen(directory+"/armed-"+role+".json","w").write(json.dumps(r))\ntime.sleep(10)\n''')
        os.chmod(fixture, 0o600)
        processes=[]
        def popen(*args, **kwargs):
            child=subprocess.Popen(*args, **kwargs); processes.append(child); return child
        cleaned=[]
        commands={"primary":(sys.executable,str(fixture),"primary",str(self.root/"state"),"stay"),
                  "secondary":(sys.executable,str(fixture),"secondary",str(self.root/"state"),"fail")}
        launcher=ProcessLauncher(permit_path=self.root/"state"/"launch-permit.json", authority_path=self.root/"state"/"authority.json", commands=commands, cleanup_partial=lambda deadline: cleaned.append(deadline),
                                 monotonic=time.monotonic, popen=popen)
        # Rewrite times into this process's monotonic domain for this isolated launcher test.
        value=p.document; now=time.monotonic(); value.update(original_t0_monotonic=now-1,
            arm_deadline_monotonic=now+1, teardown_deadline_monotonic=now+2, hard_deadline_monotonic=now+3)
        atomic_json(self.root/"state"/"launch-permit.json", value)
        p=read_permit(self.root/"state"/"launch-permit.json")
        # Authority must be rebound because permit digest includes deadlines.
        (self.root/"state"/"authority.json").unlink()
        a=persist_authority(self.root/"state"/"authority.json",p,private_id="pod-1",
            unique_name="episode1-x",ownership_token="secret",billing_started_monotonic=now)
        binding=SimpleNamespace(sha256=D,run_nonce=p.run_nonce,hard_deadline_monotonic=p.hard_deadline_monotonic)
        with self.assertRaisesRegex(WatchdogError, "exited"):
            launcher(binding,self.root/"state",now+1)
        self.assertEqual(len(cleaned),1)
        self.assertEqual(len(processes),2)
        self.assertTrue(all(child.poll() is not None for child in processes))

    def test_launcher_tracks_direct_worker_pids_separately_from_inhibitors(self):
        p=self.permit(); self.authority(p); now=time.monotonic(); value=p.document
        value.update(original_t0_monotonic=now-1,arm_deadline_monotonic=now+1,
            teardown_deadline_monotonic=now+2,hard_deadline_monotonic=now+3)
        atomic_json(self.root/"state"/"launch-permit.json",value)
        p=read_permit(self.root/"state"/"launch-permit.json")
        (self.root/"state"/"authority.json").unlink()
        persist_authority(self.root/"state"/"authority.json",p,private_id="pod-1",
            unique_name="episode1-x",ownership_token="secret",billing_started_monotonic=now)
        worker=self.root/"worker.py"
        worker.write_text('''import json,os,sys,time\nrole,directory=sys.argv[1:]\nb=json.load(open(directory+"/worker-binding.json"))\nr={"schema_version":"episode1.guard-armed.v1","role":role,"binding_sha256":b["binding_sha256"],"run_nonce":b["run_nonce"],"pid":os.getpid(),"observed_monotonic":time.monotonic(),"initial_provider_poll_ok":True,"script_sha256":b["script_sha256"]}\nopen(directory+"/armed-"+role+".json","w").write(json.dumps(r))\ntime.sleep(10)\n''')
        inhibitor=self.root/"inhibitor.py"; log=self.root/"inhibitor.log"
        inhibitor.write_text('''import sys,time\nopen(sys.argv[1],"a").write(sys.argv[2]+"\\n")\ntime.sleep(10)\n''')
        processes=[]
        def popen(*args,**kwargs):
            child=subprocess.Popen(*args,**kwargs); processes.append(child); return child
        commands={role:(sys.executable,str(worker),role,str(self.root/"state"))
                  for role in ("primary","secondary")}
        launcher=ProcessLauncher(permit_path=self.root/"state"/"launch-permit.json",
            authority_path=self.root/"state"/"authority.json",commands=commands,
            sleep_preventer=(sys.executable,str(inhibitor),str(log),"{worker_pid}"),
            cleanup_partial=lambda deadline:None,monotonic=time.monotonic,popen=popen)
        binding=SimpleNamespace(sha256=D,run_nonce=p.run_nonce,
            hard_deadline_monotonic=p.hard_deadline_monotonic)
        try:
            pids=launcher(binding,self.root/"state",now+1)
            receipt_pids=[json.loads((self.root/"state"/f"armed-{role}.json").read_text())["pid"]
                          for role in ("primary","secondary")]
            self.assertEqual(pids,receipt_pids)
            until=time.monotonic()+.5
            while time.monotonic()<until and (not log.exists() or len(log.read_text().splitlines())<2):
                time.sleep(.01)
            self.assertEqual(set(log.read_text().splitlines()),set(map(str,pids)))
            self.assertEqual(len(processes),4)
        finally:
            for child in processes:
                try: os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError: pass
            for child in processes:
                try: child.wait(timeout=1)
                except subprocess.TimeoutExpired: pass

    def test_partial_launch_constructor_failure_still_cleans_and_reaps(self):
        p=self.permit(); self.authority(p); real=[]; calls=0
        fixture=self.root/"sleep.py"; fixture.write_text("import time; time.sleep(10)\n")
        def popen(*args,**kwargs):
            nonlocal calls; calls+=1
            if calls==2: raise OSError("fixture failure")
            child=subprocess.Popen(*args,**kwargs); real.append(child); return child
        now=time.monotonic(); value=p.document; value.update(original_t0_monotonic=now-1,
            arm_deadline_monotonic=now+1,teardown_deadline_monotonic=now+2,hard_deadline_monotonic=now+3)
        atomic_json(self.root/"state"/"launch-permit.json",value); p=read_permit(self.root/"state"/"launch-permit.json")
        (self.root/"state"/"authority.json").unlink(); self.authority(p)
        cleaned=[]; command=(sys.executable,str(fixture))
        launcher=ProcessLauncher(permit_path=self.root/"state"/"launch-permit.json", authority_path=self.root/"state"/"authority.json", commands={r:command for r in ("primary","secondary")},
            cleanup_partial=lambda deadline:cleaned.append(deadline),monotonic=time.monotonic,popen=popen)
        with self.assertRaises(OSError): launcher(SimpleNamespace(sha256=D,run_nonce=p.run_nonce,hard_deadline_monotonic=p.hard_deadline_monotonic),self.root/"state",now+1)
        self.assertEqual(len(cleaned),1); self.assertIsNotNone(real[0].poll())

    @unittest.skipUnless(hasattr(os,"fork"),"requires POSIX process groups")
    def test_partial_arm_kills_stopped_term_ignoring_descendant_after_leader_exit(self):
        p=self.permit(); self.authority(p); now=time.monotonic(); value=p.document
        value.update(original_t0_monotonic=now-1,arm_deadline_monotonic=now+1,
            teardown_deadline_monotonic=now+2,hard_deadline_monotonic=now+3)
        atomic_json(self.root/"state"/"launch-permit.json",value)
        p=read_permit(self.root/"state"/"launch-permit.json")
        (self.root/"state"/"authority.json").unlink()
        persist_authority(self.root/"state"/"authority.json",p,private_id="pod-1",
            unique_name="episode1-x",ownership_token="secret",billing_started_monotonic=now)
        fixture=self.root/"descendant.py"; pidfile=self.root/"descendant.pid"
        fixture.write_text('''import os,signal,sys,time\npidfile=sys.argv[1]\nchild=os.fork()\nif child==0:\n signal.signal(signal.SIGTERM,signal.SIG_IGN)\n open(pidfile,"w").write(str(os.getpid()))\n os.kill(os.getpid(),signal.SIGSTOP)\n while True: time.sleep(1)\nwhile not os.path.exists(pidfile): time.sleep(.005)\nos._exit(7)\n''')
        sleeper=(sys.executable,"-c","import time; time.sleep(10)")
        commands={"primary":(sys.executable,str(fixture),str(pidfile)),"secondary":sleeper}
        launcher=ProcessLauncher(permit_path=self.root/"state"/"launch-permit.json",
            authority_path=self.root/"state"/"authority.json",commands=commands,
            cleanup_partial=lambda deadline:None,monotonic=time.monotonic)
        binding=SimpleNamespace(sha256=D,run_nonce=p.run_nonce,
            hard_deadline_monotonic=p.hard_deadline_monotonic)
        with self.assertRaisesRegex(WatchdogError,"exited"):
            launcher(binding,self.root/"state",now+1)
        descendant=int(pidfile.read_text())
        with self.assertRaises(ProcessLookupError): os.kill(descendant,0)

if __name__ == "__main__": unittest.main()
