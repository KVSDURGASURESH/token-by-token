import base64, hashlib, json, tempfile, unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from runpod_benchmark import episode1_capture as ch
from runpod_benchmark.episode1_promotion import promote_private_evidence
from test_episode1_promotion import START, make_bundle, ready_plan
from runpod_benchmark.episode1 import CELLS, validate_observation


class Clock:
    def __init__(self): self.m=START; self.u=1_800_000_000_000_000_000
    def set_before(self,value):
        if value<=self.m: value=self.m+2
        self.m=value-1
    def mono(self): self.m+=1; return self.m
    def utc(self): self.u+=1; return self.u


@dataclass(frozen=True)
class Authority:
    private_id: str='pod-integration'
    unique_name: str='episode1-integration'
    ownership_token: str='f'*64
    billing_started_monotonic: float=(START+1)/1_000_000_000
    ssh_host: str='127.0.0.1'
    ssh_public_port: int=2222
    container_ssh_port: int=22
    gpu: str='NVIDIA H100 80GB HBM3'
    gpu_count: int=1
    data_center_id: str='US-TEST-1'
    cloud_type: str='SECURE'
    container_disk_gb: int=120
    volume_gb: int=0
    volume_mount_path: str=''
    requested_image_reference: str='example.invalid/episode1@sha256:'+'a'*64
    provider_image_reference: str='example.invalid/episode1@sha256:'+'a'*64

    @property
    def resource_identity_sha256(self):
        return ch.sha(ch.canonical({
            'provider':'runpod-rest-v2','private_id':self.private_id,
            'unique_name':self.unique_name,
            'ownership_token_sha256':ch.sha(self.ownership_token.encode()),
            'billing_started_monotonic':self.billing_started_monotonic,
        }))

    @property
    def immutable_allocation_sha256(self):
        return ch.sha(ch.canonical({'private_id':self.private_id,'unique_name':self.unique_name,
            'ssh_host':self.ssh_host,'ssh_public_port':self.ssh_public_port,
            'requested_image_reference':self.requested_image_reference,
            'provider_image_reference':self.provider_image_reference,'gpu':self.gpu,
            'gpu_count':self.gpu_count,'data_center_id':self.data_center_id,
            'cloud_type':self.cloud_type,'container_disk_gb':self.container_disk_gb,
            'volume_gb':self.volume_gb,'volume_mount_path':self.volume_mount_path,
            'container_ssh_port':self.container_ssh_port}))


def native_source(run_id,attempt_id,block,runtime,start,end):
    result=[]
    for sequence,(when,value) in enumerate(((start,10),(end,20)),1):
        raw=(b"# HELP native_queue_depth Runtime queue depth\n"
             b"# TYPE native_queue_depth gauge\n"
             b"# UNIT native_queue_depth items\n"+
             f"native_queue_depth {value}\n".encode())
        sample={"clock_domain":"integration-clock","monotonic_ns":when,
            "process_identity":"pid:4242","process_start_identity":"ticks:8080","runtime":runtime,
            "block":block,"metric_name":"native_queue_depth","labels":{},"value":value,
            "status":"ok","reason":None,"kind":"gauge","unit":"items",
            "help":"Runtime queue depth","declared_type":"gauge","declared_unit":"items"}
        envelope={"schema_version":"episode1.native-scrape.v1","binding":{"run_id":run_id,
            "attempt_id":attempt_id,"process_identity":"pid:4242","process_start_identity":"ticks:8080",
            "runtime":runtime,"block":block,"clock_domain":"integration-clock"},"sequence":sequence,
            "scheduled_monotonic_ns":when,"observed_monotonic_ns":when,
            "observed_utc_ns":1_800_000_000_000_000_000+when,"clock_uncertainty_ns":1,
            "scrape_start_monotonic_ns":when,"scrape_end_monotonic_ns":when+1,
            "scrape_deadline_monotonic_ns":when+1000,"scrape_status":"ok",
            "scrape_reason":None,"schedule_lag_ns":0,
            "observed_process_identity_before":["pid:4242","ticks:8080"],
            "observed_process_identity_after":["pid:4242","ticks:8080"],
            "raw_kind":"body","raw_sha256":hashlib.sha256(raw).hexdigest(),
            "raw_base64":base64.b64encode(raw).decode(),"native_samples":[sample],"counter_resets":[]}
        result.append(json.dumps(envelope,sort_keys=True,separators=(',',':')).encode()+b'\n')
    return b''.join(result),{"start_monotonic_ns":start,"end_monotonic_ns":end,
        "max_sampling_gap_ns":end-start}


def paired_native_source(run_id,attempt_id,block,runtime,start,end):
    """Two real runtime selectors, including SGLang's shared counter family."""
    if runtime.startswith("sglang"):
        definitions=(
            ("native-prefill","sglang:realtime_tokens_total",
             {"model_name":"Qwen/Qwen2.5-32B-Instruct","mode":"prefill_compute"},
             "tokens","counter","Total realtime tokens"),
            ("native-decode","sglang:realtime_tokens_total",
             {"model_name":"Qwen/Qwen2.5-32B-Instruct","mode":"decode"},
             "tokens","counter","Total realtime tokens"),
        )
    else:
        definitions=(
            ("native-prefill","vllm:request_prefill_time_seconds_sum",
             {"model_name":"Qwen/Qwen2.5-32B-Instruct","engine":"0"},
             "seconds","histogram","Prefill time"),
            ("native-decode","vllm:request_decode_time_seconds_sum",
             {"model_name":"Qwen/Qwen2.5-32B-Instruct","engine":"0"},
             "seconds","histogram","Decode time"),
        )
    result=[]
    for sequence,(when,value) in enumerate(((start,10),(end,20)),1):
        declarations=[]; points=[]; samples=[]; declared=set()
        for _,metric,labels,unit,declared_type,help_text in definitions:
            family=metric[:-4] if declared_type=="histogram" else metric
            if family not in declared:
                declarations.extend((f"# HELP {family} {help_text}",
                                     f"# TYPE {family} {declared_type}"))
                declared.add(family)
            label_text=",".join(f'{key}={json.dumps(label)}' for key,label in labels.items())
            points.append(f"{metric}{{{label_text}}} {value}")
            samples.append({"clock_domain":"integration-clock","monotonic_ns":when,
                "process_identity":"pid:4242","process_start_identity":"ticks:8080",
                "runtime":runtime,"block":block,"metric_name":metric,"labels":labels,
                "value":value,"status":"ok","reason":None,"kind":"counter","unit":unit,
                "help":help_text,"declared_type":declared_type,"declared_unit":None})
        raw=("\n".join(declarations+points)+"\n").encode()
        envelope={"schema_version":"episode1.native-scrape.v1","binding":{"run_id":run_id,
            "attempt_id":attempt_id,"process_identity":"pid:4242","process_start_identity":"ticks:8080",
            "runtime":runtime,"block":block,"clock_domain":"integration-clock"},"sequence":sequence,
            "scheduled_monotonic_ns":when,"observed_monotonic_ns":when,
            "observed_utc_ns":1_800_000_000_000_000_000+when,"clock_uncertainty_ns":1,
            "scrape_start_monotonic_ns":when,"scrape_end_monotonic_ns":when+1,
            "scrape_deadline_monotonic_ns":when+1000,"scrape_status":"ok",
            "scrape_reason":None,"schedule_lag_ns":0,
            "observed_process_identity_before":["pid:4242","ticks:8080"],
            "observed_process_identity_after":["pid:4242","ticks:8080"],
            "raw_kind":"body","raw_sha256":hashlib.sha256(raw).hexdigest(),
            "raw_base64":base64.b64encode(raw).decode(),"native_samples":samples,"counter_resets":[]}
        result.append(json.dumps(envelope,sort_keys=True,separators=(',',':')).encode()+b'\n')
    window={"start_monotonic_ns":start,"end_monotonic_ns":end,
        "max_sampling_gap_ns":end-start}
    return b''.join(result),window,definitions


def system_source(run_id,attempt_id,block,start,end,pid=4242,ticks=8080):
    result=[]
    for sequence,(scheduled,value) in enumerate(((start,10),(end,20)),1):
        observed=scheduled+2
        record={"schema_version":"episode1.system-sample.v1","binding":{"run_id":run_id,
            "attempt_id":attempt_id,"block":block,"clock_domain":"integration-clock"},
            "sequence":sequence,"phase":"measurement","scheduled_monotonic_ns":scheduled,
            "sample_start_monotonic_ns":scheduled+1,"observed_monotonic_ns":observed,
            "observed_utc_ns":1_800_000_000_000_000_000+scheduled,"clock_uncertainty_ns":1,
            "schedule_lag_ns":1,"missed_slots":0,
            "observed_gap_ns":None if sequence==1 else end-start,
            "process_expected":{"pid":pid,"start_ticks":ticks,"role":"runtime"},
            "process_identity_before":[pid,ticks],"process_identity_after":[pid,ticks],
            "process_identity_status":"ok","metrics":[{"source":"procfs","name":"rss_bytes",
                "unit":"bytes","scope":"process","value":value,"status":"ok","reason":None}]}
        result.append(json.dumps(record,sort_keys=True,separators=(',',':')).encode()+b'\n')
    return b''.join(result),{"start_monotonic_ns":start+2,"end_monotonic_ns":end+2,
        "max_sampling_gap_ns":end-start,"pid":pid,"start_ticks":ticks}


class PromotionIntegration(unittest.TestCase):
    def test_counter_projection_retains_unavailable_reset_and_gap_evidence(self):
        def samples(values, stamps):
            return [{"clock_domain":"integration-clock","monotonic_ns":stamp,
                "process_identity":"pid:4242","process_start_identity":"ticks:8080",
                "runtime":"vllm","block":"block-1","metric_name":"counter_total",
                "labels":{},"value":value,"status":"ok","reason":None}
                for value,stamp in zip(values,stamps,strict=True)]
        series=ch.Series.create("counter","counter_total",{})
        reset_window=ch.Window("integration-clock",100,200,200,"pid:4242","ticks:8080",
            "vllm","block-1")
        reset,_=ch._summary_projection(samples((10,9),(100,200)),reset_window,series,
            "counter_total","counter","tokens",b"reset")
        self.assertEqual((reset["status"],reset["unavailable_reason"],reset["value"]),
            ("unavailable","counter_reset",None))
        self.assertEqual((reset["first_sample_monotonic_ns"],reset["last_sample_monotonic_ns"]),
            (100,200))
        gap_window=ch.Window("integration-clock",100,300,100,"pid:4242","ticks:8080",
            "vllm","block-1")
        gap,_=ch._summary_projection(samples((10,20),(100,300)),gap_window,series,
            "counter_total","counter","tokens",b"gap")
        self.assertEqual((gap["status"],gap["unavailable_reason"],gap["value"]),
            ("unavailable","sampling_gap",None))
        self.assertEqual((gap["first_sample_monotonic_ns"],gap["last_sample_monotonic_ns"]),
            (100,300))

    def test_capture_start_rejects_unapproved_or_divergent_image_references(self):
        plan=ready_plan(); cells={c['id']:c for c in CELLS}; counts={}
        blocks=tuple((b['block_id'],b['runtime']) for b in plan['blocks'])
        for block in plan['blocks']:
            for cell_id in block['cell_order']:
                counts[f"{block['block_id']}|{cell_id}|1"]=cells[cell_id]['warmups']
                counts[f"{block['block_id']}|{cell_id}|0"]=cells[cell_id]['requests']
        hard=START+int(plan['budget']['maximum_lifetime_seconds'])*1_000_000_000
        approved='example.invalid/episode1@'+plan['runtime_builds'][0]['derived_image_digest']
        wrong='registry.invalid/episode1@sha256:'+'f'*64
        for requested,provider in ((wrong,wrong),(approved,wrong)):
            with self.subTest(requested=requested,provider=provider):
                contract=ch.RunContract('run-20260922','attempt-01',plan['plan_sha256'],
                    'b'*64,plan['material_sha256'],blocks,counts,('native-queue','system-rss'),START,
                    1_800_000_000_000_000_000,hard,hard-60_000_000_000,
                    'integration-clock','integration-boot')
                clock=Clock(); directory=Path(tempfile.mkdtemp(dir='/private/tmp',prefix='capture-image-'))/'run'
                cap=ch.EvidenceCaptureV2(directory,contract,monotonic_ns=clock.mono,
                    utc_ns=clock.utc,observation_validator=validate_observation)
                authority=Authority(requested_image_reference=requested,
                    provider_image_reference=provider)
                cap.prepare(plan,'episode1-integration','f'*64)
                cap.owned(authority,plan,cleanup_deadline_monotonic=hard/1e9)
                with self.assertRaisesRegex(ValueError,'image references'):
                    cap.start(authority,plan,cleanup_deadline_monotonic=hard/1e9)

    def test_authority_only_cleanup_is_retained_sealed_and_not_promotable(self):
        plan=ready_plan(); cells={c['id']:c for c in CELLS}; counts={}
        blocks=tuple((b['block_id'],b['runtime']) for b in plan['blocks'])
        for block in plan['blocks']:
            for cell_id in block['cell_order']:
                counts[f"{block['block_id']}|{cell_id}|1"]=cells[cell_id]['warmups']
                counts[f"{block['block_id']}|{cell_id}|0"]=cells[cell_id]['requests']
        hard=START+int(plan['budget']['maximum_lifetime_seconds'])*1_000_000_000
        contract=ch.RunContract('run-early-cleanup','attempt-01',plan['plan_sha256'],
            'b'*64,plan['material_sha256'],blocks,counts,('native-queue',),START,
            1_800_000_000_000_000_000,hard,hard-60_000_000_000,
            'integration-clock','integration-boot')
        clock=Clock(); directory=Path(tempfile.mkdtemp(dir='/private/tmp',prefix='capture-early-'))/'run'
        cap=ch.EvidenceCaptureV2(directory,contract,monotonic_ns=clock.mono,
            utc_ns=clock.utc,observation_validator=validate_observation)
        authority=Authority()
        cap.prepare(plan,authority.unique_name,authority.ownership_token)
        cap.owned(authority,plan,cleanup_deadline_monotonic=hard/1e9)
        cap.cleanup_attempt_observed(delete_attempt=1,operation='delete',
            observation=None,error_type='TimeoutError')
        times=(START+100,START+200,START+300)
        observations=[]; results=[]
        for operation,kind,status,complete,absent,raw,when in zip(
            ('delete','inventory','direct'),('delete_ack','inventory_read','direct_read'),
            ('acknowledged','complete','not_found'),(None,True,None),(None,True,None),
            (b'',b'{"pods":[]}',b''),times,strict=True):
            capture_input={'schema_version':'episode1.provider-call-observation.v1',
                'delete_attempt':2,'kind':kind,'run_id':contract.run_id,
                'attempt_id':contract.attempt_id,'plan_sha256':contract.plan_sha256,
                'resource_identity_sha256':authority.resource_identity_sha256,
                'observed_monotonic_ns':when,
                'provider_response_sha256':hashlib.sha256(raw).hexdigest(),
                'status':status,'complete':complete,'resource_absent':absent}
            result=SimpleNamespace(raw_bytes=raw,capture_input=capture_input,
                provider_artifact={'operation':operation})
            cap.cleanup_attempt_observed(delete_attempt=2,operation=operation,
                observation=result,error_type=None)
            observations.append(capture_input); results.append(result)
        clock.set_before(times[-1]+1)
        cap.deletion_verified(attempts=2,acknowledged=True,inventory_absent=True,
            direct_not_found=True,attempt_evidence=observations,
            provider_evidence=[item.provider_artifact for item in results],
            delete_response=results[0].raw_bytes,inventory_response=results[1].raw_bytes,
            direct_response=results[2].raw_bytes)
        cap.close()
        ledger=(directory/'lifecycle.jsonl').read_text().splitlines()
        events=[json.loads(line)['event'] for line in ledger]
        self.assertEqual(events.count('cleanup-attempt-observed'),4)
        self.assertIn('deletion-verified',events)
        self.assertTrue((directory/'capture-seal.json').is_file())
        with self.assertRaisesRegex(ch.IncompleteEvidence,'promotion-owned'):
            cap.assemble_promotion_bundle(plan=plan,sources={},approval={},image_digest='sha256:'+'a'*64)

    def test_request_lifecycle_requires_dispatch_and_exact_terminal_timestamps(self):
        record={"request_id":"request-1","block_id":"block-1","cell_id":"cell-1",
            "scheduled_order":1,"status":"success","a_ns":10,"b_ns":11,"end_ns":20}
        base={"schema_version":"episode1.request-lifecycle.v1","request_id":"request-1",
            "block_id":"block-1","cell_id":"cell-1","scheduled_order":1,
            "clock_domain":"client_monotonic_ns"}
        missing_dispatch=[{**base,"stage":"scheduled","at_ns":10},
            {**base,"stage":"finalized","at_ns":20}]
        with self.assertRaisesRegex(ch.IntegrityError,"dispatch"):
            ch._verify_request_lifecycle(missing_dispatch,[record])
        wrong_times=[{**base,"stage":"scheduled","at_ns":9},
            {**base,"stage":"dispatched","at_ns":11},
            {**base,"stage":"finalized","at_ns":20}]
        with self.assertRaisesRegex(ch.IntegrityError,"timestamps"):
            ch._verify_request_lifecycle(wrong_times,[record])

    def test_unsent_request_may_omit_dispatch_but_still_binds_endpoints(self):
        record={"request_id":"request-1","block_id":"block-1","cell_id":"cell-1",
            "scheduled_order":1,"status":"unsent","a_ns":10,"b_ns":None,"end_ns":20}
        base={"schema_version":"episode1.request-lifecycle.v1","request_id":"request-1",
            "block_id":"block-1","cell_id":"cell-1","scheduled_order":1,
            "clock_domain":"client_monotonic_ns"}
        ch._verify_request_lifecycle([
            {**base,"stage":"scheduled","at_ns":10},
            {**base,"stage":"finalized","at_ns":20},
        ],[record])

    def test_600_record_capture_assembles_bundle_accepted_by_reviewed_promoter(self):
        plan=ready_plan(); reference=make_bundle(plan)
        cells={c['id']:c for c in CELLS}; counts={}
        blocks=tuple((b['block_id'],b['runtime']) for b in plan['blocks'])
        for block in plan['blocks']:
            for cell_id in block['cell_order']:
                counts[f"{block['block_id']}|{cell_id}|1"]=cells[cell_id]['warmups']
                counts[f"{block['block_id']}|{cell_id}|0"]=cells[cell_id]['requests']
        hard=START+int(plan['budget']['maximum_lifetime_seconds'])*1_000_000_000
        contract=ch.RunContract('run-20260922','attempt-01',plan['plan_sha256'],
            'b'*64,plan['material_sha256'],blocks,counts,
            ('native-prefill','native-decode','system-rss'),START,
            1_800_000_000_000_000_000,hard,hard-60_000_000_000,
            'integration-clock','integration-boot')
        clock=Clock(); directory=Path(tempfile.mkdtemp(dir='/private/tmp',prefix='capture-real-'))/'run'
        cap=ch.EvidenceCaptureV2(directory,contract,monotonic_ns=clock.mono,
            utc_ns=clock.utc,observation_validator=validate_observation)
        approved_ref='example.invalid/episode1@'+plan['runtime_builds'][0]['derived_image_digest']
        authority=Authority(requested_image_reference=approved_ref,provider_image_reference=approved_ref)
        cap.prepare(plan,'episode1-integration','f'*64)
        cap.owned(authority,plan,cleanup_deadline_monotonic=hard/1e9)
        allocation=reference['ledger']['entries'][0]
        clock.set_before(allocation['monotonic_ns'])
        cap.start(authority,plan,cleanup_deadline_monotonic=hard/1e9)
        groups={}
        for record in reference['records']['records']:
            groups.setdefault((record['block_id'],record['cell_id'],record['warmup']),[]).append(record)
        process_receipts={}
        for event in reference['ledger']['entries'][1:]:
            name=event['event']; detail=event['details']
            if name=='block-start':
                clock.set_before(event['monotonic_ns'])
                process_start=ch.sha(ch.canonical({'pid':4242,'start_ticks':8080}))
                process_identity=ch.sha(ch.canonical({
                    'process_id_sha256':detail['process_id_sha256'],
                    'process_start_identity_sha256':process_start}))
                process_receipts[detail['block_id']]=process_identity
                cap.block_start(detail['block_id'],detail['runtime'],block_attempt=detail['block_attempt'],
                    startup_attempt_id_sha256=detail['startup_attempt_id_sha256'],
                    process_id_sha256=detail['process_id_sha256'],
                    process_start_identity_sha256=process_start,
                    image_digest=detail['image_digest'])
            elif name in {'warmup-complete','cell-complete'}:
                warm=name=='warmup-complete'; key=(detail['block_id'],detail['cell_id'],warm)
                for record in groups[key]:
                    fact={"schema_version":"episode1.request-lifecycle.v1",
                        "request_id":record["request_id"],"block_id":record["block_id"],
                        "cell_id":record["cell_id"],"scheduled_order":record["scheduled_order"],
                        "clock_domain":"client_monotonic_ns"}
                    cap.request_lifecycle({**fact,"stage":"scheduled","at_ns":record["a_ns"]})
                    cap.request_lifecycle({**fact,"stage":"dispatched","at_ns":record["b_ns"]})
                    cap.request(record)
                    cap.request_lifecycle({**fact,"stage":"finalized","at_ns":record["end_ns"]})
                clock.set_before(event['monotonic_ns'])
                cap.cell_complete(detail['block_id'],detail['cell_id'],warmup=warm,
                    startup_attempt_id_sha256=detail['startup_attempt_id_sha256'],
                    process_identity_sha256=process_receipts[detail['block_id']])
            elif name=='block-stop':
                runtime=dict(blocks)[detail['block_id']]; clock.set_before(event['monotonic_ns'])
                cap.block_complete(detail['block_id'],runtime,descendants_absent=True,memory_recovered=True,
                    startup_attempt_id_sha256=detail['startup_attempt_id_sha256'],
                    process_identity_sha256=process_receipts[detail['block_id']])
            elif name=='essential-export-complete':
                for block_id,runtime in blocks:
                    source,window,definitions=paired_native_source(
                        contract.run_id,contract.attempt_id,block_id,runtime,
                        START+90_000_000,START+210_000_000)
                    window={**window,"start_monotonic_ns":START+100_000_000,
                        "end_monotonic_ns":START+200_000_000}
                    system_bytes,system_window=system_source(contract.run_id,contract.attempt_id,block_id,
                        START+100_000_000,START+200_000_000)
                    cap.telemetry({'plan_sha256':plan['plan_sha256'],'block_id':block_id,'runtime':runtime,
                        'series':[{'series_id':series_id,'source_kind':'native','metric_name':metric,
                            'kind':'counter','status':'available',
                            'value':{'first':10.0,'last':20.0,'delta':10.0,
                                'rate_per_second':10.0/0.12,'elapsed_seconds':0.12},
                            'unavailable_reason':None,
                            'expected_samples':2,'observed_samples':2,'missing_samples':0,
                            'labels':labels,'window':window,'source_bytes':source}
                            for series_id,metric,labels,_,_,_ in definitions]+[
                            {'series_id':'system-rss','source_kind':'system','metric_name':'rss_bytes','kind':'gauge',
                             'status':'available','value':{'minimum':10.0,'maximum':20.0,'mean':15.0},
                             'unavailable_reason':None,'expected_samples':2,'observed_samples':2,'missing_samples':0,
                             'labels':{'source':'procfs','unit':'bytes','scope':'process'},
                             'window':system_window,'source_bytes':system_bytes}]})
                clock.set_before(event['monotonic_ns'])
                cap.export_essential(deadline_monotonic=hard/1e9)
                break
        delete_event=next(e for e in reference['ledger']['entries'] if e['event']=='delete-ack')
        clock.set_before(delete_event['monotonic_ns'])
        receipt_times=(52_000_000_000,53_000_000_000,54_000_000_000)
        ownership=ch.sha(ch.canonical({'provider':'runpod-rest-v2',
            'private_id':authority.private_id,'unique_name':authority.unique_name,
            'ownership_token_sha256':ch.sha(authority.ownership_token.encode()),
            'billing_started_monotonic_ns':int(authority.billing_started_monotonic*1_000_000_000)}))
        def provider_call(role,method,path,status,started,completed,raw,query=None,**extra):
            body={'schema_version':'episode1.provider-call-evidence.v1','role':role,
                'delete_attempt':1,
                'run_id':contract.run_id,'attempt_id':contract.attempt_id,
                'plan_sha256':contract.plan_sha256,
                'resource_identity_sha256':authority.resource_identity_sha256,
                'ownership_identity_sha256':ownership,'http_method':method,
                'request_path':path,'request_query':query or {},'http_status':status,
                'request_started_monotonic_ns':started,'body_complete_monotonic_ns':completed,
                'absolute_deadline_monotonic_ns':hard,
                'operation_deadline_monotonic_ns':completed+500_000_000,
                'raw_body_sha256':hashlib.sha256(raw).hexdigest(),
                'raw_body_base64':base64.b64encode(raw).decode(),**extra}
            body['artifact_sha256']=ch.sha(ch.canonical(body)); return body
        delete_raw=b''
        delete_evidence=provider_call('delete-response','DELETE',f'/pods/{authority.private_id}',204,
            receipt_times[0]-100_000_000,receipt_times[0],delete_raw)
        page_raw=json.dumps({'pagination':{'hasNextPage':False,'nextCursor':None},'pods':[]},
            sort_keys=True,separators=(',',':')).encode()
        page=provider_call('inventory-page','GET','/pods',200,
            receipt_times[0]+100_000_000,receipt_times[1],page_raw,
            query={'includeClusterPods':'true','limit':'1000'},sequence=1,
            request_cursor=None,has_next_page=False,next_cursor=None)
        inventory_evidence={'schema_version':'episode1.provider-inventory-evidence.v1',
            'role':'inventory-after-delete','delete_attempt':1,'run_id':contract.run_id,
            'attempt_id':contract.attempt_id,'plan_sha256':contract.plan_sha256,
            'resource_identity_sha256':authority.resource_identity_sha256,
            'ownership_identity_sha256':ownership,
            'absolute_deadline_monotonic_ns':hard,'pages':[page],
            'terminal_page_sequence':1,'terminal_next_cursor':None,
            'complete':True,'resource_absent':True}
        inventory_evidence['artifact_sha256']=ch.sha(ch.canonical(inventory_evidence))
        inventory_raw=ch.canonical(inventory_evidence)
        direct_raw=b''
        direct_evidence=provider_call('direct-after-delete','GET',f'/pods/{authority.private_id}',404,
            receipt_times[1]+100_000_000,receipt_times[2],direct_raw)
        responses=(delete_raw,inventory_raw,direct_raw)
        provider_evidence=(delete_evidence,inventory_evidence,direct_evidence)
        observations=[]
        for kind,status,complete,absent,raw,when in zip(
            ('delete_ack','inventory_read','direct_read'),('acknowledged','complete','not_found'),
            (None,True,None),(None,True,None),responses,receipt_times,strict=True):
            observations.append({'schema_version':'episode1.provider-call-observation.v1','delete_attempt':1,
                'kind':kind,'run_id':contract.run_id,'attempt_id':contract.attempt_id,
                'plan_sha256':contract.plan_sha256,
                'resource_identity_sha256':authority.resource_identity_sha256,
                'observed_monotonic_ns':when,'provider_response_sha256':hashlib.sha256(raw).hexdigest(),
                'status':status,'complete':complete,'resource_absent':absent})
        clock.set_before(receipt_times[-1]+1)
        cap.deletion_verified(attempts=1,acknowledged=True,inventory_absent=True,direct_not_found=True,
            attempt_evidence=observations,provider_evidence=provider_evidence,
            delete_response=responses[0],
            inventory_response=responses[1],direct_response=responses[2])
        cap.settlement_observed(status='provisional',response=b'{"billing":"pending"}',
            reason='pending_provider_settlement')
        cap.close()
        bundle=cap.assemble_promotion_bundle(plan=plan,sources=reference['sources'],
            approval=reference['approval'],image_digest=plan['runtime_builds'][0]['derived_image_digest'])
        promoted=promote_private_evidence(plan=plan,bundle=bundle)
        self.assertEqual(promoted['record_count'],600)
        sgl_block=next(block_id for block_id,runtime in blocks if runtime.startswith('sglang'))
        sgl_summaries=[item for item in bundle['telemetry']['summaries']
            if item['block_id']==sgl_block and item['source_kind']=='native']
        self.assertEqual([item['metric_name'] for item in sgl_summaries],
            ['sglang:realtime_tokens_total']*2)
        self.assertEqual({item['labels']['mode'] for item in sgl_summaries},
            {'prefill_compute','decode'})
        self.assertEqual({item['counter_semantics'] for item in sgl_summaries},
            {'delta_over_actual_bracketing_interval'})
        self.assertEqual({item['coverage'] for item in sgl_summaries},
            {'sampled_interval_covering_window'})
        self.assertEqual({item['first_sample_monotonic_ns'] for item in sgl_summaries},
            {START+90_000_000})
        self.assertEqual({item['last_sample_monotonic_ns'] for item in sgl_summaries},
            {START+210_000_000})
        self.assertEqual({item['unit'] for item in sgl_summaries},{'tokens'})
        self.assertEqual(set(bundle),{'manifest','allocation_authority','sources','approval','records','telemetry',
            'cleanup','provider_artifacts','ledger','settlement'})
        authority_artifact=bundle['allocation_authority']
        self.assertEqual(authority_artifact['private_id'],authority.private_id)
        self.assertEqual(authority_artifact['resource_identity_sha256'],authority.resource_identity_sha256)
        self.assertEqual(authority_artifact['artifact_sha256'],
            bundle['manifest']['allocation_authority_sha256'])
        self.assertEqual(authority_artifact['immutable_allocation_sha256'],
            authority.immutable_allocation_sha256)
        self.assertEqual({r['delete_attempt'] for r in bundle['cleanup']['receipts']},{1})
        self.assertEqual({item['evidence']['delete_attempt']
            for item in bundle['provider_artifacts']['artifacts']},{1})
        self.assertEqual(tuple(r['observed_monotonic_ns'] for r in bundle['cleanup']['receipts']),receipt_times)
        cleanup_events=[e for e in bundle['ledger']['entries']
            if e['event'] in {'delete-ack','inventory-read','direct-read'}]
        self.assertEqual(tuple(e['monotonic_ns'] for e in cleanup_events),receipt_times)


if __name__=='__main__': unittest.main()
