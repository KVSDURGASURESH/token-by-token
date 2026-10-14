from copy import deepcopy
import math

import pytest

from runpod_benchmark.episode2_corpus import build_trace, make_synthetic_protocol
from test_episode2_runner import run


def test_one_token_has_no_tpot_but_keeps_content_latency():
    from runpod_benchmark.episode2_validity import qualify_turn
    row = {'success':True,'output_tokens':1,'ttft_ms':2.0,'e2e_ms':4.0,'content_span_ms':0.0,'quality_valid':True,'schema_valid':True,'tool_valid':True,'work_equivalent':True}
    value = qualify_turn(row, {'quality':{'minimum_output_tokens':1}})
    assert value['tpot_ms'] is None and value['ttft_ms'] == 2 and value['e2e_ms'] == 4


def test_tool_only_has_terminal_latency_without_content_metrics():
    from runpod_benchmark.episode2_validity import qualify_turn
    row = {'success':True,'output_tokens':8,'ttft_ms':None,'e2e_ms':4.0,'content_span_ms':None,'quality_valid':True,'schema_valid':True,'tool_valid':True,'work_equivalent':True}
    value = qualify_turn(row, {'quality':{}})
    assert value['qualified'] and value['e2e_ms'] == 4
    assert value['ttft_ms'] is None and value['tpot_ms'] is None


@pytest.mark.parametrize('field,value', [('output_tokens',True),('output_tokens',-1),('ttft_ms',-1),('e2e_ms',float('nan')),('content_span_ms',float('inf'))])
def test_invalid_measurement_is_not_admitted(field,value):
    from runpod_benchmark.episode2_validity import qualify_turn
    row = {'success':True,'output_tokens':8,'ttft_ms':2.,'e2e_ms':4.,'content_span_ms':1.,'quality_valid':True,'schema_valid':True,'tool_valid':True,'work_equivalent':True}
    row[field] = value
    with pytest.raises(ValueError): qualify_turn(row, {'quality':{}})


def test_failure_retains_denominator_but_has_no_serving_metrics():
    from runpod_benchmark.episode2_validity import qualify_turn
    row = {'success':False,'output_tokens':None,'ttft_ms':None,'e2e_ms':None,'content_span_ms':None,'quality_valid':False,'schema_valid':False,'tool_valid':False,'work_equivalent':False}
    value = qualify_turn(row, {'quality':{}})
    assert not value['qualified'] and value['e2e_ms'] is None


@pytest.mark.parametrize('mutation', ['duplicate','missing','wrong_id','wrong_hash','negative_time','missing_usage','mixed_evidence','tool_arguments','changed_semantic','duplicate_attempt','wrong_summary'])
def test_result_entry_rejects_corrupted_or_missing_observations(mutation):
    from runpod_benchmark.episode2_validity import validate_observations
    protocol = make_synthetic_protocol(); trace = build_trace(protocol); result = run(protocol)
    row = result['observations'][0]
    if mutation == 'duplicate': result['observations'].append(deepcopy(row))
    if mutation == 'missing': result['observations'].pop()
    if mutation == 'wrong_id': row['logical_request_id'] = 'other'
    if mutation == 'wrong_hash': row['messages_sha256'] = '0'*64
    if mutation == 'negative_time': row['actual_send_ns'] = -1
    if mutation == 'missing_usage': row['input_tokens'] = None
    if mutation == 'mixed_evidence': row['evidence_class'] = 'recorded'
    if mutation == 'duplicate_attempt': result['attempts'].append(deepcopy(result['attempts'][-1]))
    if mutation == 'wrong_summary': result['window']['scheduled_requests'] = 1
    if mutation == 'changed_semantic':
        target = next(item for item in result['observations'] if item['class_id']=='structured')
        target['text'] = '{"answer":7,"unit":"items"}'
    if mutation == 'tool_arguments':
        target = next(item for item in result['observations'] if item['class_id']=='tool_call' and item['turn_id']=='turn-1')
        target['tool_calls'][0]['function']['arguments'] = '{"sku":"other"}'
    with pytest.raises(ValueError): validate_observations(result,protocol,trace)


def test_all_scheduled_identities_survive_cancelled_work():
    from runpod_benchmark.episode2_validity import validate_observations
    protocol=make_synthetic_protocol(); result=run(protocol,stop=lambda:True)
    validate_observations(result,protocol,build_trace(protocol))
    assert len(result['observations']) == 72 and not result['attempts']


def test_missing_physical_lineage_never_proves_equal_measured_work():
    from runpod_benchmark.episode2_validity import matched_work
    left,right=run(),run(engine='sglang')
    value=matched_work(left,right)
    assert value['status']=='inconclusive' and not value['equivalent']
    left['physical_gpu_private_ref']='private-gpu-a'; right['physical_gpu_private_ref']='private-gpu-b'
    value=matched_work(left,right)
    assert value['status']=='incompatible' and 'private-gpu' not in str(value)


def test_raw_observation_schema_preserves_unsent_nulls_and_rejects_fake_usage():
    import json
    from pathlib import Path
    from jsonschema import Draft202012Validator
    validator=Draft202012Validator(json.loads(Path('schemas/episode2-observation.schema.json').read_text()))
    row=run(stop=lambda:True)['observations'][0]
    validator.validate(row)
    row['input_tokens']=12
    assert list(validator.iter_errors(row))


def test_content_event_tampering_cannot_retain_quality_claim():
    from runpod_benchmark.episode2_validity import validate_observations
    protocol=make_synthetic_protocol(); result=run(protocol)
    result['observations'][0]['content_events'][0]['text']='tampered'
    with pytest.raises(ValueError,match='event'): validate_observations(result,protocol,build_trace(protocol))


def test_tool_event_arguments_must_agree_with_validated_model_call():
    from runpod_benchmark.episode2_validity import validate_observations
    protocol=make_synthetic_protocol(); result=run(protocol)
    row=next(item for item in result['observations'] if item['tool_calls'])
    row['tool_events'][0]['delta']['function']['arguments']='{"sku":"other"}'
    with pytest.raises(ValueError,match='tool.*event'): validate_observations(result,protocol,build_trace(protocol))


@pytest.mark.parametrize('table', ['attempts','workflow_observations','admissions'])
def test_other_execution_identity_is_rejected_in_every_denominator(table):
    from runpod_benchmark.episode2_validity import validate_observations
    protocol=make_synthetic_protocol(); result=run(protocol)
    result[table][0]['execution_id']='another-execution'
    with pytest.raises(ValueError): validate_observations(result,protocol,build_trace(protocol))


def test_warmup_attempts_cannot_disappear_behind_exclusion_windows():
    from runpod_benchmark.episode2_validity import validate_observations
    protocol=make_synthetic_protocol(); result=run(protocol)
    result['attempts']=[item for item in result['attempts'] if item['phase']=='measured']
    with pytest.raises(ValueError,match='warmup'): validate_observations(result,protocol,build_trace(protocol))


def test_tool_event_latency_is_separate_from_content_ttft():
    from runpod_benchmark.episode2_validity import qualify_turn
    row={'success':True,'output_tokens':8,'ttft_ms':None,'e2e_ms':.00009,'content_span_ms':None,'quality_valid':True,'schema_valid':True,'tool_valid':True,'work_equivalent':True,'actual_send_ns':10,'terminal_ns':100,'tool_events':[{'received_ns':20,'delta':{'index':0}}]}
    value=qualify_turn(row,{'quality':{}})
    assert value['tool_event_latency_ms']==pytest.approx(.00001)
    assert value['ttft_ms'] is None and value['tpot_ms'] is None


def test_shortened_measurement_cannot_inflate_rate_with_outside_requests():
    from runpod_benchmark.episode2_validity import validate_observations
    protocol=make_synthetic_protocol(); result=run(protocol)
    for block in result['blocks']:block['end_ns']=block['start_ns']+1
    result['window']['end_ns']=result['blocks'][-1]['end_ns']
    result['window']['measured_duration_ns']=len(result['blocks'])
    with pytest.raises(ValueError,match='block|window'):validate_observations(result,protocol,build_trace(protocol))


@pytest.mark.parametrize('table', ['workflow_observations','admissions'])
def test_workflow_terminal_and_admission_decision_must_fit_measured_block(table):
    from runpod_benchmark.episode2_validity import validate_observations
    protocol=make_synthetic_protocol(); result=run(protocol)
    row=result[table][0]
    block=next(item for item in result['blocks'] if item['block_id']==row['block_id'])
    if table=='workflow_observations':
        row['terminal_ns']=block['end_ns']+1
        row['workflow_e2e_ms']=(row['terminal_ns']-row['scheduled_ns'])/1e6
    else:row['decision_ns']=block['end_ns']+1
    with pytest.raises(ValueError,match='block|window'):validate_observations(result,protocol,build_trace(protocol))


def test_measured_attempts_cannot_be_shifted_outside_the_block():
    from runpod_benchmark.episode2_validity import validate_observations
    protocol=make_synthetic_protocol(); result=run(protocol)
    row=result['observations'][0]
    block=next(item for item in result['blocks'] if item['block_id']==row['block_id'])
    shift=block['end_ns']-row['actual_send_ns']+1000000
    for name in ['scheduled_ns','eligible_ns','actual_send_ns','first_content_ns','last_content_ns','terminal_ns','validation_terminal_ns']:
        if row[name] is not None:row[name]+=shift
    for event in row['content_events']+row['tool_events']:event['received_ns']+=shift
    attempt=next(item for item in result['attempts'] if item['attempt_id']==row['attempt_id'])
    attempt['start_ns']+=shift;attempt['end_ns']+=shift
    workflow=next(item for item in result['workflow_observations'] if item['block_id']==row['block_id'] and item['workflow_id']==row['workflow_id'])
    for name in ['scheduled_ns','actual_start_ns','terminal_ns']:workflow[name]+=shift
    admission=next(item for item in result['admissions'] if item['block_id']==row['block_id'] and item['workflow_id']==row['workflow_id'])
    admission['scheduled_ns']+=shift;admission['decision_ns']+=shift
    with pytest.raises(ValueError,match='block|window'):validate_observations(result,protocol,build_trace(protocol))


@pytest.mark.parametrize('corruption', [None, 'duplicate_id', 'wrong_id', 'wrong_name', 'wrong_arguments', 'null_arguments'])
def test_sglang_null_continuation_identity_preserves_actual_tool_fragments(corruption):
    """Shape captured from the completed run's three SGLang tool deltas."""
    from runpod_benchmark.episode2_sessions import StreamReply
    from runpod_benchmark.episode2_validity import _tool_event_match
    events = [
        {'received_ns':20, 'delta':{'index':0,'id':'call-captured','type':'function','function':{'name':'lookup_inventory','arguments':''}}},
        {'received_ns':30, 'delta':{'index':0,'id':None,'type':'function','function':{'name':None,'arguments':'{"sku": "'}}},
        {'received_ns':40, 'delta':{'index':0,'id':None,'type':'function','function':{'name':None,'arguments':'widget"}'}}},
    ]
    calls=[{'id':'call-captured','type':'function','function':{'name':'lookup_inventory','arguments':'{"sku": "widget"}'}}]
    if corruption=='duplicate_id': events[1]['delta']['id']='call-captured'
    if corruption=='wrong_id': events[0]['delta']['id']='call-other'
    if corruption=='wrong_name': events[0]['delta']['function']['name']='other_function'
    if corruption=='wrong_arguments': events[-1]['delta']['function']['arguments']='other"}'
    if corruption=='null_arguments': events[-1]['delta']['function']['arguments']=None
    reply=StreamReply('',calls,10,None,None,50,187,29,'tool_calls',[],events)
    if corruption is None: _tool_event_match(reply)
    else:
        with pytest.raises(ValueError,match='tool'): _tool_event_match(reply)
