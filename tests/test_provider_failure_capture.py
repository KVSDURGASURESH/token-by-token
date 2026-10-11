from __future__ import annotations
import json, os, tempfile, time, unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

from runpod_benchmark import episode1_capture as capmod
from runpod_benchmark import episode1_provider_failure_capture as sinkmod
from runpod_benchmark.bounded_runpod_transport import TransportInvalidResponseError
from runpod_benchmark.episode1_orchestrator import LifecycleError
from runpod_benchmark.episode1_provider_failure_capture import CaptureFailureSink
from runpod_benchmark.runpod_v2 import OwnedResource, Response, RunpodV2Provider

KEY="SHA256:"+"A"*43
IMAGE="example.invalid/e1@sha256:"+"a"*64

class Clock:
    def __init__(self,start): self.value=start
    def mono(self): self.value+=1; return self.value
    def utc(self): return 1_900_000_000_000_000_000+self.value

class Transport:
    def __init__(self,responses): self.responses=list(responses); self.calls=[]
    def request(self,method,path,*,query=None,json_body=None,deadline_monotonic):
        self.calls.append((method,path,query,deadline_monotonic))
        value=self.responses.pop(0)
        if isinstance(value,BaseException): raise value
        if isinstance(value,Response) and value.completed_monotonic_ns==0:
            value=Response(value.status,value.body,value.raw_body,time.monotonic_ns())
        return value

@dataclass(frozen=True)
class Authority:
    private_id: str
    unique_name: str
    ownership_token: str
    billing_started_monotonic: float

def raw_response(status,body,*,completed=0,raw=None):
    if raw is None: raw=json.dumps(body,separators=(",",":"),sort_keys=True).encode() if body is not None else b""
    return Response(status,body,raw,completed)

def fixture(responses):
    now=time.monotonic(); billing=round(now-1,6); t0=int((billing-.5)*1e9); hard=int((now+60)*1e9)
    blocks=tuple((f"b{i}","vllm" if i%2 else "sglang") for i in range(1,7))
    counts={}
    for block,_ in blocks: counts[f"{block}|cell|1"]=12; counts[f"{block}|cell|0"]=88
    contract=capmod.RunContract("run-1","attempt-1","a"*64,"b"*64,"c"*64,blocks,counts,
        ("native",),t0,1_900_000_000_000_000_000,hard,hard-1_000_000_000,"clock-1","boot-1")
    directory=Path(tempfile.mkdtemp(dir="/private/tmp",prefix="pfail-test-"))/"capture"
    clock=Clock(t0); capture=capmod.EvidenceCaptureV2(directory,contract,
        monotonic_ns=clock.mono,utc_ns=clock.utc,observation_validator=lambda value:value)
    authority=Authority("pod-1","episode1-run","t"*64,billing); plan={"plan_sha256":"a"*64}
    capture.prepare(plan,authority.unique_name,authority.ownership_token)
    capture.owned(authority,plan,cleanup_deadline_monotonic=hard/1e9)
    owned=OwnedResource(authority.private_id,authority.unique_name,authority.ownership_token,billing)
    transport=Transport(responses)
    provider=RunpodV2Provider(transport,approved_image_reference=IMAGE,
        approved_authorized_key_fingerprint=KEY,persist_owned=lambda _:None,monotonic=time.monotonic)
    provider._owned[owned.private_id]=owned
    sink=CaptureFailureSink(capture); provider.bind_failure_observation_sink(sink)
    binding=provider.make_cleanup_observation_binding(owned,run_id=contract.run_id,
        attempt_id=contract.attempt_id,plan_sha256=contract.plan_sha256,
        resource_identity_sha256=capture._cleanup_resource_identity_sha256,
        original_deadline_monotonic_ns=hard)
    return capture,provider,transport,owned,binding,hard/1e9

def artifacts(capture):
    return [json.loads(p.read_text()) for p in sorted(capture.directory.glob("cleanup-failure-*.json"))]

def observation(value):
    raw=capmod.canonical(value)
    return __import__('types').SimpleNamespace(evidence_bytes=raw,
                                               evidence_sha256=capmod.sha(raw))

def resealed_inventory_call(source,*,index,raw_body,started,complete):
    value=json.loads(json.dumps(source)); call=value["provider_call"]
    call["schema_version"]="episode1.provider-call-evidence.v1"
    call.pop("validation_error",None)
    call["http_status"]=200
    call["request_started_monotonic_ns"]=started
    call["body_complete_monotonic_ns"]=complete
    call["raw_body_base64"]=__import__('base64').b64encode(raw_body).decode()
    call["raw_body_sha256"]=capmod.sha(raw_body)
    call["artifact_sha256"]=capmod.sha(capmod.canonical(
        {k:v for k,v in call.items() if k!="artifact_sha256"}))
    value["call_index"]=index
    value["provider_call"]=call
    value["artifact_sha256"]=capmod.sha(capmod.canonical(
        {k:v for k,v in value.items() if k!="artifact_sha256"}))
    return value

def resealed_terminal(source,calls,pages):
    value=json.loads(json.dumps(source))
    value["provider_call_artifact_sha256"]=[
        call["provider_call"]["artifact_sha256"] for call in calls]
    value["validated_inventory_pages"]=pages
    value["artifact_sha256"]=capmod.sha(capmod.canonical(
        {k:v for k,v in value.items() if k!="artifact_sha256"}))
    return value

class FailureCaptureTests(unittest.TestCase):
    def test_delete_500_is_durable_and_nonpromotable(self):
        raw=b'{ "error" : "denied" }'
        capture,p,_,owned,binding,deadline=fixture([raw_response(500,{"error":"denied"},raw=raw)])
        with self.assertRaisesRegex(LifecycleError,"not accepted"):
            p.delete_allocation_observed(owned,binding=binding,delete_attempt=1,deadline_monotonic=deadline)
        values=artifacts(capture); self.assertEqual(2,len(values))
        call=next(x for x in values if x["schema_version"].endswith("call.v1"))
        self.assertEqual(raw, __import__('base64').b64decode(call["provider_call"]["raw_body_base64"]))
        terminal=next(x for x in values if x["schema_version"].endswith("terminal.v1"))
        self.assertIsNone(terminal["resource_absent"]); self.assertFalse(terminal["complete"])
        for path in capture.directory.glob("cleanup-failure-*.json"):
            self.assertEqual(0o600,os.stat(path).st_mode & 0o777)

    def test_inventory_prefix_survives_later_http_failure(self):
        first={"pods":[],"pagination":{"nextCursor":"c2","hasNextPage":True}}
        second={"error":"later"}
        capture,p,_,owned,binding,deadline=fixture([raw_response(200,first),raw_response(500,second)])
        with self.assertRaisesRegex(LifecycleError,"inventory request failed"):
            p.inventory_absent_observed(owned,binding=binding,delete_attempt=2,deadline_monotonic=deadline)
        values=artifacts(capture); calls=sorted((x for x in values if x["schema_version"].endswith("call.v1")),key=lambda x:x["call_index"])
        self.assertEqual([1,2],[x["call_index"] for x in calls])
        terminal=next(x for x in values if x["schema_version"].endswith("terminal.v1"))
        self.assertEqual(1,len(terminal["validated_inventory_pages"]))
        self.assertEqual([x["provider_call"]["artifact_sha256"] for x in calls],terminal["provider_call_artifact_sha256"])

    def test_terminal_inventory_prefix_must_derive_from_retained_calls(self):
        first={"pods":[],"pagination":{"nextCursor":"c2","hasNextPage":True}}
        capture,p,_,owned,binding,deadline=fixture([
            raw_response(200,first),raw_response(500,{"error":"later"})])
        with self.assertRaises(LifecycleError):
            p.inventory_absent_observed(owned,binding=binding,delete_attempt=7,
                                        deadline_monotonic=deadline)
        values=artifacts(capture)
        calls=sorted((x for x in values if x["schema_version"].endswith("call.v1")),
                     key=lambda x:x["call_index"])
        terminal=next(x for x in values if x["schema_version"].endswith("terminal.v1"))
        sink=CaptureFailureSink(capture)
        for call in calls:
            raw=capmod.canonical(call)
            sink(__import__('types').SimpleNamespace(evidence_bytes=raw,
                                                     evidence_sha256=capmod.sha(raw)))
        terminal["validated_inventory_pages"][0].update(
            request_cursor="impossible",has_next_page=False,
            next_cursor="also-impossible",page_artifact_sha256="f"*64)
        terminal["artifact_sha256"]=capmod.sha(capmod.canonical(
            {k:v for k,v in terminal.items() if k!="artifact_sha256"}))
        raw=capmod.canonical(terminal)
        with self.assertRaisesRegex(capmod.IntegrityError,"does not match retained calls"):
            sink(__import__('types').SimpleNamespace(evidence_bytes=raw,
                                                     evidence_sha256=capmod.sha(raw)))

    def test_invalid_pagination_call_is_retained_but_not_validated_as_page(self):
        invalid={"pods":[],"pagination":{"nextCursor":None,"hasNextPage":True}}
        capture,p,_,owned,binding,deadline=fixture([raw_response(200,invalid)])
        with self.assertRaisesRegex(LifecycleError,"cursor is missing"):
            p.inventory_absent_observed(owned,binding=binding,delete_attempt=8,
                                        deadline_monotonic=deadline)
        values=artifacts(capture)
        self.assertEqual(1,sum(x["schema_version"].endswith("call.v1") for x in values))
        terminal=next(x for x in values if x["schema_version"].endswith("terminal.v1"))
        self.assertEqual([],terminal["validated_inventory_pages"])

    def test_repeated_cursor_page_is_not_added_to_validated_prefix(self):
        first={"pods":[],"pagination":{"nextCursor":"c2","hasNextPage":True}}
        repeated={"pods":[],"pagination":{"nextCursor":"c2","hasNextPage":True}}
        capture,p,_,owned,binding,deadline=fixture([
            raw_response(200,first),raw_response(200,repeated)])
        with self.assertRaisesRegex(LifecycleError,"cursor is missing or repeated"):
            p.inventory_absent_observed(owned,binding=binding,delete_attempt=9,
                                        deadline_monotonic=deadline)
        terminal=next(x for x in artifacts(capture)
                      if x["schema_version"].endswith("terminal.v1"))
        self.assertEqual(1,len(terminal["validated_inventory_pages"]))
        self.assertEqual("c2",terminal["validated_inventory_pages"][0]["next_cursor"])

    def test_malformed_inventory_raw_is_retained_without_validated_page(self):
        response=Response(200,None,b'{"pods":',time.monotonic_ns()+1_000_000_000)
        error=TransportInvalidResponseError("invalid",response=response,stage="invalid_json")
        capture,p,_,owned,binding,deadline=fixture([error])
        with self.assertRaises(TransportInvalidResponseError):
            p.inventory_absent_observed(owned,binding=binding,delete_attempt=10,
                                        deadline_monotonic=deadline)
        values=artifacts(capture)
        call=next(x for x in values if x["schema_version"].endswith("call.v1"))
        self.assertEqual("episode1.provider-failed-http-call.v1",
                         call["provider_call"]["schema_version"])
        terminal=next(x for x in values if x["schema_version"].endswith("terminal.v1"))
        self.assertEqual([],terminal["validated_inventory_pages"])

    def test_valid_page_after_invalid_call_cannot_reenter_prefix(self):
        response=Response(200,None,b'{"pods":',time.monotonic_ns()+1_000_000_000)
        error=TransportInvalidResponseError("invalid",response=response,stage="invalid_json")
        capture,p,_,owned,binding,deadline=fixture([error])
        with self.assertRaises(TransportInvalidResponseError):
            p.inventory_absent_observed(owned,binding=binding,delete_attempt=12,
                                        deadline_monotonic=deadline)
        first=next(x for x in artifacts(capture)
                   if x["schema_version"].endswith("call.v1"))
        terminal=next(x for x in artifacts(capture)
                      if x["schema_version"].endswith("terminal.v1"))
        prior_complete=first["provider_call"]["body_complete_monotonic_ns"]
        page=capmod.canonical(
            {"pods":[],"pagination":{"nextCursor":None,"hasNextPage":False}})
        second=resealed_inventory_call(first,index=2,raw_body=page,
            started=prior_complete,complete=prior_complete+1)
        sink=CaptureFailureSink(capture)
        sink(observation(first)); sink(observation(second))
        self.assertEqual([],sink._validated_pages.get((12,"inventory_read"),[]))
        sink(observation(resealed_terminal(terminal,[first,second],[])))

    def test_extra_page_after_terminal_page_cannot_extend_prefix(self):
        page={"pods":[],"pagination":{"nextCursor":None,"hasNextPage":False}}
        capture,p,_,owned,binding,deadline=fixture([raw_response(200,page)])
        checks=0
        def deadline_check(_deadline):
            nonlocal checks
            checks+=1
            if checks==5: raise TimeoutError("post-parse deadline")
        p._check_deadline=deadline_check
        with self.assertRaisesRegex(TimeoutError,"post-parse deadline"):
            p.inventory_absent_observed(owned,binding=binding,delete_attempt=13,
                                        deadline_monotonic=deadline)
        first=next(x for x in artifacts(capture)
                   if x["schema_version"].endswith("call.v1"))
        terminal=next(x for x in artifacts(capture)
                      if x["schema_version"].endswith("terminal.v1"))
        prior_complete=first["provider_call"]["body_complete_monotonic_ns"]
        second=resealed_inventory_call(first,index=2,
            raw_body=capmod.canonical(page),started=prior_complete,
            complete=prior_complete+1)
        sink=CaptureFailureSink(capture)
        sink(observation(first)); sink(observation(second))
        pages=sink._validated_pages[(13,"inventory_read")]
        self.assertEqual(1,len(pages))
        self.assertFalse(pages[0]["has_next_page"])
        sink(observation(resealed_terminal(terminal,[first,second],pages)))

    def test_valid_page_survives_post_parse_deadline_failure(self):
        page={"pods":[],"pagination":{"nextCursor":None,"hasNextPage":False}}
        capture,p,_,owned,binding,deadline=fixture([raw_response(200,page)])
        checks=0
        def deadline_check(_deadline):
            nonlocal checks
            checks+=1
            if checks==5: raise TimeoutError("post-parse deadline")
        p._check_deadline=deadline_check
        with self.assertRaisesRegex(TimeoutError,"post-parse deadline"):
            p.inventory_absent_observed(owned,binding=binding,delete_attempt=11,
                                        deadline_monotonic=deadline)
        terminal=next(x for x in artifacts(capture)
                      if x["schema_version"].endswith("terminal.v1"))
        self.assertEqual(1,len(terminal["validated_inventory_pages"]))

    def test_html_empty_and_late_responses_are_retained_as_failed_http(self):
        cases=[Response(500,None,b"<html>bad</html>",0),
               Response(500,None,b"",0)]
        for response in cases:
            with self.subTest(raw=response.raw_body):
                capture,p,_,owned,binding,deadline=fixture([response])
                with self.assertRaises(LifecycleError):
                    p.direct_not_found_observed(owned,binding=binding,delete_attempt=1,deadline_monotonic=deadline)
                call=next(x for x in artifacts(capture) if x["schema_version"].endswith("call.v1"))
                self.assertEqual("episode1.provider-failed-http-call.v1",call["provider_call"]["schema_version"])
                self.assertEqual(response.raw_body,__import__('base64').b64decode(call["provider_call"]["raw_body_base64"]))
        capture,p,_,owned,binding,deadline=fixture([])
        late=Response(500,None,b"late",int(deadline*1e9)+1); p.transport.responses=[late]
        with self.assertRaises(LifecycleError):
            p.direct_not_found_observed(owned,binding=binding,delete_attempt=1,deadline_monotonic=deadline)
        call=next(x for x in artifacts(capture) if x["schema_version"].endswith("call.v1"))
        self.assertEqual("late_response",call["provider_call"]["validation_error"])

    def test_typed_transport_error_and_provider_postcheck_are_retained(self):
        response=raw_response(500,None,raw=b"<html>bad</html>",completed=time.monotonic_ns()+1_000_000_000)
        error=TransportInvalidResponseError("invalid",response=response,stage="invalid_json")
        capture,p,_,owned,binding,deadline=fixture([error])
        with self.assertRaises(TransportInvalidResponseError):
            p.direct_not_found_observed(owned,binding=binding,delete_attempt=1,
                                        deadline_monotonic=deadline)
        call=next(x for x in artifacts(capture) if x["schema_version"].endswith("call.v1"))
        self.assertEqual("invalid_body",call["provider_call"]["validation_error"])
        self.assertEqual(b"<html>bad</html>",__import__('base64').b64decode(
            call["provider_call"]["raw_body_base64"]))

        response=raw_response(500,{"error":"late"})
        capture,p,transport,owned,binding,deadline=fixture([response])
        ticks=iter((deadline-1,deadline+1))
        p.monotonic=lambda: next(ticks)
        with self.assertRaises(TimeoutError):
            p.delete_allocation_observed(owned,binding=binding,delete_attempt=1,
                                         deadline_monotonic=deadline)
        call=next(x for x in artifacts(capture) if x["schema_version"].endswith("call.v1"))
        self.assertEqual("late_response",call["provider_call"]["validation_error"])

    def test_sink_write_failure_is_fail_closed(self):
        capture,p,_,owned,binding,deadline=fixture([raw_response(500,{"error":"x"})])
        capture.provider_failure_observed=lambda _value: (_ for _ in ()).throw(OSError("disk"))
        with self.assertRaisesRegex(LifecycleError,"persistence failed"):
            p.delete_allocation_observed(owned,binding=binding,delete_attempt=1,deadline_monotonic=deadline)
        self.assertEqual([],artifacts(capture))

    def test_resealed_wrong_binding_is_rejected(self):
        capture,p,_,owned,binding,deadline=fixture([raw_response(500,{"error":"x"})])
        with self.assertRaises(LifecycleError):
            p.delete_allocation_observed(owned,binding=binding,delete_attempt=1,deadline_monotonic=deadline)
        path=next(capture.directory.glob("cleanup-failure-*.json")); value=json.loads(path.read_text())
        value["ownership_identity_sha256"]="f"*64
        value["artifact_sha256"]=capmod.sha(capmod.canonical({k:v for k,v in value.items() if k!="artifact_sha256"}))
        raw=capmod.canonical(value)
        obs=__import__('types').SimpleNamespace(evidence_bytes=raw,evidence_sha256=capmod.sha(raw))
        with self.assertRaisesRegex(capmod.IntegrityError,"binding"):
            CaptureFailureSink(capture)(obs)

    def test_per_call_persistence_avoids_aggregate_loss(self):
        first={"pods":[],"pagination":{"nextCursor":"c2","hasNextPage":True}}
        capture,p,_,owned,binding,deadline=fixture([raw_response(200,first),raw_response(500,{"pad":"x"*3000})])
        p.MAX_PROVIDER_ARTIFACT_BYTES=7000
        with self.assertRaises(LifecycleError):
            p.inventory_absent_observed(owned,binding=binding,delete_attempt=3,deadline_monotonic=deadline)
        values=artifacts(capture)
        self.assertEqual(3,len(values))
        self.assertTrue(all(len(capmod.canonical(v))<7000 for v in values))

    def test_sink_cannot_bind_after_observation_started(self):
        capture,p,_,owned,binding,deadline=fixture([raw_response(500,{"error":"x"})])
        with self.assertRaises(LifecycleError):
            p.delete_allocation_observed(owned,binding=binding,delete_attempt=1,deadline_monotonic=deadline)
        with self.assertRaisesRegex(LifecycleError,"already bound"):
            p.bind_failure_observation_sink(CaptureFailureSink(capture))

    def test_authority_reader_rejects_fifo_symlink_and_same_size_mutation(self):
        root=Path(tempfile.mkdtemp(dir="/private/tmp",prefix="pfail-reader-"))
        fifo=root/"cleanup-authority.json"; os.mkfifo(fifo,0o600)
        started=time.monotonic()
        with self.assertRaisesRegex(capmod.IntegrityError,"regular file"):
            sinkmod._bounded_authority(root)
        self.assertLess(time.monotonic()-started,1)
        fifo.unlink(); target=root/"target"; target.write_bytes(b"{}")
        os.chmod(target,0o600); fifo.symlink_to(target)
        with self.assertRaisesRegex(capmod.IntegrityError,"unavailable"):
            sinkmod._bounded_authority(root)
        fifo.unlink(); fifo.write_bytes(b'{"x":1}'); os.chmod(fifo,0o600)
        real_read=os.read; changed=False
        def mutating_read(fd,count):
            nonlocal changed
            data=real_read(fd,count)
            if data and not changed:
                changed=True
                other=os.open(fifo,os.O_WRONLY)
                try: os.write(other,b'{"x":2}')
                finally: os.close(other)
            return data
        with mock.patch.object(sinkmod.os,"read",side_effect=mutating_read):
            with self.assertRaisesRegex(capmod.IntegrityError,"changed while reading"):
                sinkmod._bounded_authority(root)

    def test_sink_requires_capture_owned_authority(self):
        now=time.monotonic(); hard=int((now+60)*1e9)
        blocks=tuple((f"b{i}","vllm" if i%2 else "sglang") for i in range(1,7))
        counts={f"{block}|cell|{warmup}": count for block,_ in blocks
                for warmup,count in ((1,12),(0,88))}
        contract=capmod.RunContract("run-1","attempt-1","a"*64,"b"*64,"c"*64,
            blocks,counts,("native",),int((now-1)*1e9),1_900_000_000_000_000_000,
            hard,hard-1_000_000_000,"clock-1","boot-1")
        directory=Path(tempfile.mkdtemp(dir="/private/tmp",prefix="pfail-unowned-"))/"capture"
        clock=Clock(contract.original_t0_monotonic_ns)
        capture=capmod.EvidenceCaptureV2(directory,contract,monotonic_ns=clock.mono,
            utc_ns=clock.utc,observation_validator=lambda value:value)
        capture.prepare({"plan_sha256":"a"*64},"episode1-run","t"*64)
        with self.assertRaisesRegex(capmod.IntegrityError,"authority is unavailable"):
            CaptureFailureSink(capture)

if __name__=="__main__": unittest.main()
