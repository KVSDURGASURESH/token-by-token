"""Rehearsal runner preserves denominator, dependency, and actual transport identity."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from runpod_benchmark.episode2_corpus import OUTPUT_CONCEPTS, build_trace, make_synthetic_protocol
from runpod_benchmark.episode2_runner import run_cell, validate_replay_pair
from runpod_benchmark.episode2_sessions import StreamReply


ROOT = Path(__file__).resolve().parents[1]


def reply_for(turn, clock=time.monotonic_ns):
    start = clock()
    class_id, number = turn['class_id'], turn['turn_id']
    tool = (class_id == 'tool_call' and number == 'turn-1') or (class_id == 'agent_chain' and number == 'turn-2')
    if tool:
        calls = [{'id': 'call-fixture', 'type': 'function', 'function': {'name': 'lookup_inventory', 'arguments': '{"sku":"widget"}'}}]
        text, output = '', 12
    else:
        values = {
            'short': 'Equal work compares identical declared tasks and validated model outputs.',
            'long_prefill': '{"row_003":3,"row_127":127}',
            'structured': '{"answer":6,"unit":"items"}',
            'code_reasoning': '{"value":42,"expression":"6*7"}',
            'conversation': '{"selected":"orange"}' if number == 'turn-1' else '{"color":"orange"}',
            'tool_call': '{"answer":6}',
            'agent_chain': '{"sku":"widget"}' if number == 'turn-1' else '{"order":4}',
            'output_heavy': '\n'.join(f'{i}. {concept}: This declared concept keeps all measured comparisons aligned across repeated controlled workloads and observations.' for i, concept in enumerate(OUTPUT_CONCEPTS, 1)),
        }
        text, output, calls = values[class_id], 300 if class_id == 'output_heavy' else 12, []
    end = max(start, clock())
    return StreamReply(text, calls, start, None if tool else end, None if tool else end, end,
                       2400 if class_id == 'long_prefill' else 32, output,
                       'tool_calls' if tool else 'stop',
                       [] if tool else [{'received_ns': end, 'text': text}],
                       [{'received_ns': end, 'delta': {'index': 0, 'id': 'call-fixture', 'type': 'function', 'function': {'name': 'lookup_inventory', 'arguments': '{"sku":"widget"}'}}}] if tool else [])


def run(protocol=None, **kwargs):
    protocol = protocol or make_synthetic_protocol()
    return run_cell(protocol, build_trace(protocol), engine=kwargs.pop('engine', 'vllm'),
                    arm=kwargs.pop('arm', 'defaults'), cell_id=protocol['cells'][0]['cell_id'],
                    execution_id=kwargs.pop('execution_id', 'test-execution'),
                    send=kwargs.pop('send', reply_for), clock=kwargs.pop('clock', time.monotonic_ns),
                    stop=kwargs.pop('stop', lambda: False), **kwargs)


@pytest.mark.parametrize('blocks', [6, 7, 8])
def test_all_repetition_blocks_replay_mixture_with_warmups_excluded(blocks):
    result = run(make_synthetic_protocol(blocks=blocks))
    assert result['evidence_class'] == 'synthetic_mock'
    assert len(result['observations']) == 12 * blocks
    assert len(result['workflow_observations']) == 8 * blocks
    assert len(result['blocks']) == blocks
    assert all(row['status'] == 'success' for row in result['observations'])
    assert all(row['success'] for row in result['workflow_observations'])
    assert all(row['workflow_e2e_ms'] >= 0 for row in result['workflow_observations'])
    assert len([row for row in result['attempts'] if row['phase'] == 'warmup']) == blocks
    assert len([row for row in result['attempts'] if row['phase'] == 'measured']) == 12 * blocks
    assert result['window']['max_active_workflows'] <= 2
    assert result['window']['max_in_flight_requests'] <= 2
    for block in result['blocks']:
        assert set(block['class_counts'].values()) == {1}


def test_concurrent_workflows_replenish_only_after_terminal_and_keep_turn_order():
    gate = threading.Barrier(2)
    first = set()
    lock = threading.Lock()
    def send(turn):
        if turn['phase'] == 'measured' and turn['block_id'] == 'block-01' and turn['predecessor_id'] is None:
            with lock:
                first.add(turn['workflow_id'])
                use_gate = len(first) <= 2
            if use_gate:
                gate.wait(timeout=2)
        return reply_for(turn)
    result = run(send=send)
    assert result['window']['max_active_workflows'] == 2
    rows = {(row['block_id'], row['logical_request_id']): row for row in result['observations']}
    for row in result['observations']:
        if row['predecessor_id'] is not None:
            parent = rows[(row['block_id'], row['predecessor_id'])]
            assert row['eligible_ns'] >= parent['validation_terminal_ns']
            assert row['actual_send_ns'] >= row['eligible_ns']
            assert row['send_lag_ns'] == row['dependency_wait_ns'] + row['eligible_send_lag_ns']


def test_invalid_predecessor_retained_without_retry_and_descendants_blocked():
    def send(turn):
        reply = reply_for(turn)
        if turn['phase'] == 'measured' and turn['class_id'] == 'conversation' and turn['turn_id'] == 'turn-1':
            reply.text = '{"selected":"violet"}'
        return reply
    result = run(send=send)
    assert len(result['observations']) == 72
    assert len([row for row in result['observations'] if row['status'] == 'semantic_invalid']) == 6
    blocked = [row for row in result['observations'] if row['status'] == 'dependency_blocked']
    assert len(blocked) == 6
    assert all(row['actual_send_ns'] is None and row['attempt_id'] is None for row in blocked)
    measured = [row for row in result['attempts'] if row['phase'] == 'measured']
    assert len(measured) == 66
    assert len({row['attempt_id'] for row in measured}) == 66
    with pytest.raises(ValueError, match='non-equivalent'):
        validate_replay_pair(result, run(engine='sglang'))


def test_cancellation_before_dispatch_preserves_all_unsent_identities():
    def must_not_send(_turn):
        raise AssertionError('cancelled work was dispatched')
    result = run(stop=lambda: True, send=must_not_send)
    assert len(result['observations']) == 72
    assert not result['attempts']
    assert {row['status'] for row in result['observations']} == {'cancelled'}
    assert all(row['actual_send_ns'] is None for row in result['observations'])


def test_transport_error_does_not_disappear_or_retry():
    def send(turn):
        if turn['phase'] == 'measured' and turn['class_id'] == 'agent_chain' and turn['turn_id'] == 'turn-1':
            raise TimeoutError('private connection details must not enter error text')
        return reply_for(turn)
    result = run(send=send)
    assert len([row for row in result['observations'] if row['status'] == 'transport_error']) == 6
    assert len([row for row in result['observations'] if row['status'] == 'dependency_blocked']) == 12
    assert 'private connection details' not in json.dumps(result)


def test_open_loop_clock_advances_arrivals_while_first_requests_stall():
    protocol = make_synthetic_protocol(mode='open-loop')
    now = [0]
    signals = [threading.Event(), threading.Event()]
    release = threading.Event()
    stop_event = threading.Event()
    observed = []
    def send(turn):
        if turn['phase'] == 'measured':
            observed.append((turn['class_id'], turn['scheduled_ns']))
            if turn['class_id'] in {'short', 'long_prefill'}:
                signals[0 if turn['class_id'] == 'short' else 1].set()
                assert release.wait(3)
        return reply_for(turn, lambda: now[0])
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run, protocol, send=send, clock=lambda: now[0], stop=stop_event.is_set)
        try:
            assert signals[0].wait(2)
            now[0] = 100_000_000
            assert signals[1].wait(2)
            now[0] = 200_000_000
            time.sleep(.025)
            now[0] = 1_000_000_000
            time.sleep(.025)
            stop_event.set()
        finally:
            release.set()
        result = future.result(timeout=3)
    assert observed[:2] == [('short', 0), ('long_prefill', 100_000_000)]
    dropped = [row for row in result['admissions'] if row['block_id'] == 'block-01' and row['class_id'] == 'output_heavy']
    assert dropped[0]['scheduled_ns'] == 200_000_000
    assert dropped[0]['status'] == 'dropped'
    assert len(result['observations']) == 72
    assert result['window']['max_in_flight_requests'] <= 2


def test_replay_pair_requires_same_successful_requested_and_delivered_work():
    left, right = run(), run(engine='sglang')
    validate_replay_pair(left, right)
    changed = deepcopy(right)
    changed['observations'][0]['messages_sha256'] = 'f' * 64
    with pytest.raises(ValueError):
        validate_replay_pair(left, changed)
    changed = deepcopy(right)
    changed['observations'][0]['output_tokens'] += 1
    with pytest.raises(ValueError):
        validate_replay_pair(left, changed)


def test_recorded_execution_requires_later_compiled_authority():
    protocol = make_synthetic_protocol()
    protocol['classification'] = 'recorded'
    protocol['material']['execution_ready'] = True
    with pytest.raises(ValueError, match='compiled'):
        run(protocol)


@pytest.mark.parametrize('mode', ['closed-loop', 'open-loop'])
def test_loopback_cli_writes_private_synthetic_manifests_and_refuses_existing_output(tmp_path, mode):
    output = tmp_path / 'rehearsal'
    command = [sys.executable, str(ROOT / 'scripts/run_episode2_loopback_rehearsal.py'), '--output', str(output), '--blocks', '6', '--mode', mode]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    manifest = json.loads((output / 'manifest.json').read_text())
    assert manifest['evidence_class'] == 'synthetic_mock'
    assert manifest['provider_calls'] == 0
    assert manifest['transport'] == 'http_loopback_sse'
    assert manifest['comparison']['status'] in {'equivalent', 'non_equivalent'}
    assert manifest['comparison']['qualified_for_comparison'] is (manifest['comparison']['status'] == 'equivalent')
    assert manifest['results']
    assert output.stat().st_mode & 0o077 == 0
    result = json.loads((output / manifest['results'][0]).read_text())
    assert len(result['observations']) == 72
    assert all(row['content_events'] or row['tool_events'] for row in result['observations'] if row['attempt_id'] is not None)
    repeat = subprocess.run(command, capture_output=True, text=True, timeout=5)
    assert repeat.returncode != 0


def test_observation_carries_bound_qualification_fields():
    result = run()
    for row in result['observations']:
        assert row['campaign_id'] == 'episode2-synthetic-rehearsal-v1'
        assert row['schema_version'] == 'episode2.observation.v1'
        assert row['evidence_class'] == 'synthetic_mock'
        assert row['protocol_sha256'] == result['protocol_sha256']
        assert row['trace_sha256'] == result['trace_sha256']
        assert row['effective_config_sha256'] == result['effective_config_sha256']
        assert row['schema_valid'] is True and row['quality_valid'] is True
        assert row['tool_valid'] is True
        assert len(row['tool_fixtures_sha256']) == 64


def test_campaign_executes_counterbalanced_block_order_instead_of_grouping_engines():
    from runpod_benchmark.episode2_runner import run_campaign
    from runpod_benchmark.episode2_schedule import compile_order
    protocol = make_synthetic_protocol()
    order_seen = []
    def factory(engine, arm, cell_id):
        def send(turn):
            key = (engine, arm, cell_id, turn['block_id'])
            if turn['phase'] == 'measured' and key not in order_seen:
                order_seen.append(key)
            return reply_for(turn)
        return send
    campaign = run_campaign(protocol, build_trace(protocol), arm_ids=['defaults', 'treatment-1'],
                            execution_id='paired', sender_factory=factory)
    expected = [(row['engine'], row['arm'], row['cell_id'], row['block_id']) for row in compile_order(protocol, ['defaults', 'treatment-1'])]
    assert order_seen == expected
    assert len(campaign['results']) == 4
    assert all(len(result['observations']) == 72 for result in campaign['results'])


def recorded_context_fixture(monkeypatch):
    from runpod_benchmark import episode2_runner as runner
    from runpod_benchmark.episode2_contract import document_digest
    protocol=make_synthetic_protocol();protocol['classification']='recorded';protocol['material']['execution_ready']=True
    protocol['quality']['output_length_tolerance_fraction']=0.1
    protocol['safeguards'].update(e2e_slo_ms=1000,ttft_slo_ms=500,tpot_slo_ms=100,goodput_min_tokens_per_second=1,admission_rate_min=1,cost_max_usd='5.00',resource_max={'gpu_memory_fraction':0.95,'host_memory_fraction':0.95,'host_cpu_percent':99})
    trace=build_trace(protocol)
    material={'images':{engine:{'version':'fixture-version'} for engine in ('vllm','sglang')}}
    plan={'execution_ready':True,'manifest':{'episode2':{'protocol':protocol,'trace':trace,'material':material,
        'schedule':__import__('runpod_benchmark.episode2_schedule',fromlist=['compile_order']).compile_order(protocol,['defaults']),'inputs':{'phase_budgets':{'total':60}},'cleanup':{'mode':'local_only_acknowledged','guard_policy':{'watchdog_script_sha256':'c'*64,'heartbeat_stale_after_seconds':2}}}}}
    class Compiler:
        def plan_digest(self,p): return document_digest(p)
    monkeypatch.setattr(runner,'_compiler',lambda:Compiler())
    monkeypatch.setattr(runner,'_ongoing_sources_verified',lambda material:True)
    start=time.monotonic_ns()
    context={'compiled_plan':plan,'plan_sha256':document_digest(plan),'protocol_sha256':document_digest(protocol),
        'trace_sha256':document_digest(trace),'material_sha256':document_digest(material),'execution_id':'recorded-fixture',
        'physical_gpu_private_ref':'opaque-fixture-allocation','evidence_class':'synthetic_mock','guard_nonce':'fixture-guard',
        'guard_epoch_ns':start,'guard_deadline_ns':start+60_000_000_000}
    return protocol,trace,context


def test_recorded_campaign_requires_boundaries_and_keeps_mock_receipts_synthetic(monkeypatch):
    from runpod_benchmark.episode2_runner import run_campaign
    protocol,trace,context=recorded_context_fixture(monkeypatch)
    calls=[]
    def before(row):
        calls.append(('before',row['engine'],row['block_id']))
        now=time.monotonic_ns()
        return {'status':'verified','plan_sha256':context['plan_sha256'],'execution_id':context['execution_id'],
            'engine':row['engine'],'arm':row['arm'],'cell_id':row['cell_id'],'block_id':row['block_id'],
            'physical_gpu_private_ref':context['physical_gpu_private_ref'],'runtime_ready':True,'smoke_verified':True,
            'defaults_verified':True,'cache_reset_verified':True,'epoch_id':row['engine']+'-'+row['block_id'],
            'guard':{'nonce':context['guard_nonce'],'observed_ns':now,'deadline_ns':context['guard_deadline_ns'],
                'roles':[{'role':role,'pid':pid,'heartbeat_ns':now,'nonce':context['guard_nonce'],'source_sha256':'c'*64}
                         for role,pid in [('primary',100),('secondary',101)]],'caffeinate':True}}
    def after(row):
        calls.append(('after',row['engine'],row['block_id']))
        return {'status':'stopped','plan_sha256':context['plan_sha256'],'execution_id':context['execution_id'],
            'engine':row['engine'],'arm':row['arm'],'cell_id':row['cell_id'],'block_id':row['block_id'],
            'physical_gpu_private_ref':context['physical_gpu_private_ref']}
    result=run_campaign(protocol,trace,arm_ids=['defaults'],execution_id=context['execution_id'],
        sender_factory=lambda *_:reply_for,execution_context=context,before_block=before,after_block=after)
    assert [x[0] for x in calls]==['before','after']*12
    assert all(r['evidence_class']=='synthetic_mock' for r in result['results'])
    assert all(r['window']['readiness_status']=='verified' for r in result['results'])
    calls.clear()
    def failed_after(row):
        after(row)
        return {'status':'failed'}
    with pytest.raises(ValueError,match='drain'):
        run_campaign(protocol,trace,arm_ids=['defaults'],execution_id=context['execution_id'],
            sender_factory=lambda *_:reply_for,execution_context=context,before_block=before,after_block=failed_after)
    assert len(calls)==2
    calls.clear()
    def failed_warmup(turn):
        if turn['phase']=='warmup': raise RuntimeError('mock warmup transport failure')
        return reply_for(turn)
    with pytest.raises(ValueError,match='recorded'):
        run_campaign(protocol,trace,arm_ids=['defaults'],execution_id=context['execution_id'],
            sender_factory=lambda *_:failed_warmup,execution_context=context,before_block=before,after_block=after)
    assert len(calls)==2
    for failure_status in ('transport_error','semantic_invalid','timing_invalid'):
        calls.clear()
        def failed_sample(turn):
            reply=reply_for(turn)
            if turn['phase']=='measured' and turn['class_id']=='conversation' and turn['turn_id']=='turn-1':
                if failure_status=='transport_error': raise TimeoutError('bounded sample failure')
                if failure_status=='semantic_invalid': reply.text='{"selected":"violet"}'
                if failure_status=='timing_invalid': reply.actual_send_ns=turn['eligible_ns']-1
            return reply
        completed=run_campaign(protocol,trace,arm_ids=['defaults'],execution_id=context['execution_id'],
            sender_factory=lambda *_:failed_sample,execution_context=context,before_block=before,after_block=after)
        assert [x[0] for x in calls]==['before','after']*12
        rows=[row for result in completed['results'] for row in result['observations']]
        assert len(rows)==144
        assert sum(row['status']==failure_status for row in rows)==12
        assert sum(row['status']=='dependency_blocked' for row in rows)==12
        assert all(row['status']=='success' for row in rows if row['class_id']!='conversation')
        assert all(not row['semantic_valid'] for row in rows if row['status']!= 'success')


def test_recorded_guard_failure_still_drains_and_cannot_reset_deadline(monkeypatch):
    from runpod_benchmark.episode2_runner import run_campaign
    protocol,trace,context=recorded_context_fixture(monkeypatch)
    drained=[]
    def before(row): raise ValueError('fresh guard heartbeat unavailable')
    def after(row):
        drained.append(row)
        return {'status':'stopped','plan_sha256':context['plan_sha256'],'execution_id':context['execution_id'],
            'engine':row['engine'],'arm':row['arm'],'cell_id':row['cell_id'],'block_id':row['block_id'],
            'physical_gpu_private_ref':context['physical_gpu_private_ref']}
    with pytest.raises(ValueError,match='heartbeat'):
        run_campaign(protocol,trace,arm_ids=['defaults'],execution_id=context['execution_id'],
            sender_factory=lambda *_:reply_for,execution_context=context,before_block=before,after_block=after)
    assert len(drained)==1
    context['guard_deadline_ns']+=1
    with pytest.raises(ValueError,match='horizon'):
        run_campaign(protocol,trace,arm_ids=['defaults'],execution_id=context['execution_id'],
            sender_factory=lambda *_:reply_for,execution_context=context,before_block=before,after_block=after)


@pytest.mark.parametrize('fault',['stale','same_pid','nonce','source','deadline','caffeinate','private_ref'])
def test_recorded_attestation_rejects_guard_or_allocation_drift(monkeypatch,fault):
    from runpod_benchmark.episode2_runner import _attestation
    protocol,trace,context=recorded_context_fixture(monkeypatch)
    row=context['compiled_plan']['manifest']['episode2']['schedule'][0];now=time.monotonic_ns()
    value={'status':'verified','plan_sha256':context['plan_sha256'],'execution_id':context['execution_id'],
        **{key:row[key] for key in ('engine','arm','cell_id','block_id')},'physical_gpu_private_ref':context['physical_gpu_private_ref'],
        'runtime_ready':True,'smoke_verified':True,'defaults_verified':True,'cache_reset_verified':True,'epoch_id':'mock-epoch',
        'guard':{'nonce':context['guard_nonce'],'observed_ns':now,'deadline_ns':context['guard_deadline_ns'],'caffeinate':True,
                 'roles':[{'role':role,'pid':pid,'heartbeat_ns':now,'nonce':context['guard_nonce'],'source_sha256':'c'*64} for role,pid in [('primary',100),('secondary',101)]]}}
    guard=value['guard']
    if fault=='stale': guard['roles'][0]['heartbeat_ns']-=3_000_000_000
    elif fault=='same_pid': guard['roles'][1]['pid']=100
    elif fault=='nonce': guard['roles'][0]['nonce']='other'
    elif fault=='source': guard['roles'][0]['source_sha256']='d'*64
    elif fault=='deadline': guard['deadline_ns']+=1
    elif fault=='caffeinate': guard['caffeinate']=False
    else: value['physical_gpu_private_ref']='other-allocation'
    with pytest.raises(ValueError): _attestation(value,row,context,now)


def test_recorded_context_recompiles_current_sources_and_rejects_changed_schedule(monkeypatch):
    from runpod_benchmark import episode2_runner as runner
    protocol,trace,context=recorded_context_fixture(monkeypatch)
    order=context['compiled_plan']['manifest']['episode2']['schedule']
    class ChangedCompiler:
        def plan_digest(self,plan): raise ValueError('current source changed')
    monkeypatch.setattr(runner,'_compiler',lambda:ChangedCompiler())
    with pytest.raises(ValueError,match='source'): runner._execution_context(context,protocol,trace,context['execution_id'],order,time.monotonic_ns())


def test_owned_continuation_keeps_initial_authority_when_quotes_expire_but_rejects_drift(monkeypatch):
    from runpod_benchmark import episode2_runner as runner
    from runpod_benchmark.episode2_contract import document_digest
    protocol,trace,context=recorded_context_fixture(monkeypatch)
    order=context['compiled_plan']['manifest']['episode2']['schedule']
    runner._execution_context(context,protocol,trace,context['execution_id'],order,time.monotonic_ns())
    snapshot=document_digest(context)
    class ExpiredCompiler:
        def plan_digest(self,plan): raise ValueError('quotes expired')
    monkeypatch.setattr(runner,'_compiler',lambda:ExpiredCompiler())
    monkeypatch.setattr(runner,'_ongoing_sources_verified',lambda material:True,raising=False)
    runner._execution_context(context,protocol,trace,context['execution_id'],order,time.monotonic_ns(),verified_snapshot=snapshot)
    context['compiled_plan']['manifest']['episode2']['material']['changed']=True
    with pytest.raises(ValueError,match='snapshot'):
        runner._execution_context(context,protocol,trace,context['execution_id'],order,time.monotonic_ns(),verified_snapshot=snapshot)
    del context['compiled_plan']['manifest']['episode2']['material']['changed']
    monkeypatch.setattr(runner,'_ongoing_sources_verified',lambda material:False)
    with pytest.raises(ValueError,match='source'):
        runner._execution_context(context,protocol,trace,context['execution_id'],order,time.monotonic_ns(),verified_snapshot=snapshot)
