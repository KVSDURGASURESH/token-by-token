import pytest
from runpod_benchmark.episode2_rca import evaluate_hypothesis,has_required_signals


def hypothesis():
    return {'id':'queue-1','mechanism':'queue pressure','predicted_signature':'queue wait rises before tails','confounders':['client lag'],'control':'reduce admitted load','required_signals':['queue_wait_ms','client_send_lag_ms'],'observations':[],'intervention_lineage':[],'disposition':'inconclusive','limits':[]}


def evidence(*, followup=False, queue_value=3):
    from test_episode2_analysis import stable_run,bounded_protocol
    from runpod_benchmark.episode2_corpus import build_trace
    from runpod_benchmark.episode2_contract import document_digest
    from runpod_benchmark.episode2_telemetry import SIGNAL_UNITS
    p=bounded_protocol();r=stable_run(p,execution_id='intervention' if followup else 'baseline')
    p['classification']='recorded';trace=build_trace(p)
    r.update(protocol_sha256=document_digest(p),trace_sha256=document_digest(trace),evidence_class='recorded',physical_gpu_private_ref='unit-test-allocation')
    config={'max_num_batched_tokens':1024 if followup else 2048};r['effective_config_sha256']=document_digest(config);r['window']['runtime_version']='0.29.0'
    for row in r['observations']:
        row.update(protocol_sha256=r['protocol_sha256'],trace_sha256=r['trace_sha256'],evidence_class='recorded',effective_config_sha256=r['effective_config_sha256'])
    signals=[]
    for block in r['blocks']:
        start,end=block['start_ns'],block['end_ns']
        for name,value in [('queue_wait_ms',queue_value),('client_send_lag_ms',1)]:
            signals.append({'name':name,'runtime':'vllm','version':'0.29.0','unit':'ms','scope':'client' if name.startswith('client') else 'runtime','source':'unit_test_recorded_shape_only','execution_id':r['execution_id'],'engine':'vllm','arm':r['arm'],'cell_id':r['cell_id'],'block_id':block['block_id'],'clock_domain':'client_monotonic','window':{'start_ns':start,'end_ns':end},'cadence_ns':max(1,end-start),'offset_ns':0,'uncertainty_ns':0,'kind':'gauge','samples':[{'timestamp_ns':n,'value':value,'process_attributed':True} for n in (start,end)],'unavailable_reason':None})
    return {'protocol':p,'result':r,'signals':signals}


def typed_hypothesis():
    h=hypothesis();h['predicted_signature']={'description':h['predicted_signature'],'predicates':[{'signal':'queue_wait_ms','statistic':'mean','operator':'ge','threshold':2}],'confounder_predicates':{'client lag':{'signal':'client_send_lag_ms','statistic':'maximum','operator':'lt','threshold':5}}}
    return h


def intervention(*, queue_value=3):
    return {'id':'diagnostic-1','hypothesis_id':'queue-1','evidence':evidence(followup=True,queue_value=queue_value),'control':{'description':'reduce admitted load','before':{'max_num_batched_tokens':2048},'after':{'max_num_batched_tokens':1024}}}


def test_correlation_without_intervention_is_inconclusive():
    e={'available_signals':['queue_wait_ms'],'correlation':.99}
    h=evaluate_hypothesis(hypothesis(),e,None)
    assert h['disposition']=='inconclusive'
    assert h['limits']


def test_supported_signature_requires_recorded_controlled_intervention():
    h=evaluate_hypothesis(typed_hypothesis(),evidence(),intervention())
    assert h['disposition']=='supported'
    assert h['intervention_lineage']==['diagnostic-1']
    assert len(set(h['observations']))==2


@pytest.mark.parametrize('mutation',['synthetic','missing_signal','same_run','changed_control'])
def test_missing_controls_and_synthetic_tests_cannot_establish_causation(mutation):
    i=intervention()
    if mutation=='synthetic':i['evidence']['protocol']['classification']='synthetic_mock'
    if mutation=='missing_signal':i['evidence']['signals']=[row for row in i['evidence']['signals'] if row['name']!='client_send_lag_ms']
    if mutation=='same_run':i['evidence']['result']['execution_id']='baseline'
    if mutation=='changed_control':i['control']['after']={'max_num_batched_tokens':99}
    if mutation=='same_run':
        for collection in ('observations','attempts','admissions','workflow_observations'):
            for row in i['evidence']['result'][collection]:row['execution_id']='baseline'
        for row in i['evidence']['signals']:row['execution_id']='baseline'
    assert evaluate_hypothesis(typed_hypothesis(),evidence(),i)['disposition']=='inconclusive'


def test_controlled_intervention_can_reject_predeclared_prediction():
    assert evaluate_hypothesis(typed_hypothesis(),evidence(),intervention(queue_value=0))['disposition']=='rejected'


def test_missing_signals_or_invalid_hypothesis_cannot_become_supported():
    e=evidence();e['signals'].pop()
    assert evaluate_hypothesis(typed_hypothesis(),e,intervention())['disposition']=='inconclusive'
    h=hypothesis();h['causal_winner']=True
    with pytest.raises(ValueError):evaluate_hypothesis(h,evidence(),intervention())


def test_hypothesis_schema_is_closed():
    import json
    from pathlib import Path
    from jsonschema import Draft202012Validator
    schema=json.loads((Path(__file__).resolve().parents[1]/'schemas/episode2-hypothesis.schema.json').read_text())
    validator=Draft202012Validator(schema)
    assert not list(validator.iter_errors(hypothesis()))
    h=hypothesis();h['unbound']=True
    assert list(validator.iter_errors(h))


def test_unbound_signature_text_and_reused_intervention_are_inconclusive():
    h=hypothesis(); h['predicted_signature']='unrelated prediction'
    i=intervention(); i['evidence']=evidence()
    assert evaluate_hypothesis(h,evidence(),i)['disposition']=='inconclusive'


def test_boolean_signature_claims_without_actual_samples_are_inconclusive():
    assert evaluate_hypothesis(hypothesis(),evidence(),intervention())['disposition']=='inconclusive'
