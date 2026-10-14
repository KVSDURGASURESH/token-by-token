import pytest
from runpod_benchmark.episode2_arms import select_arms,build_rerun
from runpod_benchmark.episode2_corpus import make_synthetic_protocol,build_trace
from runpod_benchmark.episode2_contract import document_digest


def supported(control=None):
    if control is None:
        return {'id':'queue-1','disposition':'supported','observations':['a'*64,'b'*64],'intervention_lineage':['diagnostic-1'],'limits':['measured scope only']}
    from test_episode2_rca import typed_hypothesis
    from runpod_benchmark.episode2_rca import evaluate_hypothesis
    proof=control['hypothesis_evidence']
    return evaluate_hypothesis(typed_hypothesis(),proof['baseline'],proof['intervention'])


def control(protocol):
    from copy import deepcopy
    import hashlib
    from test_episode2_rca import evidence,intervention
    baseline=evidence();followup=intervention()
    protocol.clear();protocol.update(deepcopy(baseline['protocol']))
    defaults={'version':'0.29.0','parameters':{'max_num_batched_tokens':2048}}
    protocol['material']['vllm_defaults_sha256']=document_digest(defaults)
    for item in (baseline,followup['evidence']):
        item['protocol']=deepcopy(protocol);trace=build_trace(protocol)
        item['result'].update(protocol_sha256=document_digest(protocol),trace_sha256=document_digest(trace))
        for row in item['result']['observations']:
            row.update(protocol_sha256=document_digest(protocol),trace_sha256=document_digest(trace))
    text='vllm 0.29.0 --max-num-batched-tokens INT'
    return {'engine':'vllm','version':'0.29.0','help_sha256':hashlib.sha256(text.encode()).hexdigest(),'defaults_sha256':protocol['material']['vllm_defaults_sha256'],'hypothesis_id':'queue-1','group':'chunked_prefill','before':{'max_num_batched_tokens':2048},'after':{'max_num_batched_tokens':1024},'support':{'max_num_batched_tokens':{'type':'integer','minimum':1,'maximum':1048576}},'coupled_flags':[],'cache_reset_verified':True,'evidence_class':'recorded','runtime_proof':{'help_text':text,'defaults':defaults,'image_digest':protocol['material']['vllm_image']},'hypothesis_evidence':{'baseline':baseline,'intervention':followup}}


def test_no_supported_mechanism_produces_no_optimization():
    assert select_arms([],{'vllm':[],'sglang':[]},{'exclusions':['speculative_decoding']})==[]


def test_only_supported_control_group_can_make_a_no_spend_rerun_proposal():
    p=make_synthetic_protocol();c=control(p)
    arms=select_arms([supported(c)],{'vllm':[c],'sglang':[]},p)
    assert len(arms)==1
    proposal=arms[0]
    assert proposal['paid_approval_required'] is True
    assert proposal['execution_ready'] is False
    trace=build_trace(p)
    rerun=build_rerun(p,proposal,trace)
    assert rerun['material']['execution_ready'] is False
    assert rerun['mixture']==p['mixture'] and rerun['seed']==p['seed']
    assert build_trace(rerun)['logical_sha256']==trace['logical_sha256']


@pytest.mark.parametrize('mutation',['unsupported_flag','range','speculative','two_groups','missing_intervention','stale_defaults'])
def test_unsupported_or_uncontrolled_choices_supply_no_optimization(mutation):
    p=make_synthetic_protocol();c=control(p);h=supported(c)
    if mutation=='unsupported_flag':c['after']['unproved_flag']=True
    elif mutation=='range':c['after']['max_num_batched_tokens']=1048577
    elif mutation=='speculative':c['group']='speculative_decoding'
    elif mutation=='two_groups':c['after']['prefix_caching']=True;c['support']['prefix_caching']={'type':'boolean'}
    elif mutation=='missing_intervention':h['intervention_lineage']=[]
    elif mutation=='stale_defaults':c['defaults_sha256']='f'*64
    assert select_arms([h],{'vllm':[c],'sglang':[]},p)==[]


def test_rerun_rejects_changed_work_and_reuses_no_approval():
    p=make_synthetic_protocol();c=control(p);a=select_arms([supported(c)],{'vllm':[c],'sglang':[]},p)[0]
    changed=make_synthetic_protocol();changed['seed']=43
    with pytest.raises(ValueError):build_rerun(changed,a,build_trace(changed))
    a['configuration_after']['max_num_batched_tokens']=999
    with pytest.raises(ValueError):build_rerun(p,a,build_trace(p))


def test_partial_hypothesis_duplicate_lineage_and_unbound_runtime_are_rejected():
    p=make_synthetic_protocol(); c=control(p); c['version']='not-the-pinned-version'; c['help_sha256']='0'*64
    h=supported(); h['observations']=['a'*64,'a'*64]
    assert select_arms([h],{'vllm':[c],'sglang':[]},p)==[]


def test_hash_strings_without_retained_help_and_defaults_cannot_select():
    p=make_synthetic_protocol()
    assert select_arms([supported()],{'vllm':[control(p)],'sglang':[]},p)==[]


@pytest.mark.parametrize('mutation',['version','help_digest','help_bytes','default_bytes','support_range','image'])
def test_retained_runtime_support_cannot_be_substituted(mutation):
    p=make_synthetic_protocol();c=control(p);h=supported(c)
    if mutation=='version':c['version']='not-the-pinned-version'
    if mutation=='help_digest':c['help_sha256']='0'*64
    if mutation=='help_bytes':c['runtime_proof']['help_text']='invented help'
    if mutation=='default_bytes':c['runtime_proof']['defaults']['parameters']['max_num_batched_tokens']=99
    if mutation=='support_range':c['support']['max_num_batched_tokens']['maximum']=9999999
    if mutation=='image':c['runtime_proof']['image_digest']='sha256:'+'0'*64
    assert select_arms([h],{'vllm':[c],'sglang':[]},p)==[]


def test_proposal_matches_closed_public_schema():
    import json
    from jsonschema import Draft202012Validator
    from pathlib import Path
    p=make_synthetic_protocol();c=control(p);a=select_arms([supported(c)],{'vllm':[c],'sglang':[]},p)[0]
    Draft202012Validator(json.loads(Path('schemas/episode2-arm-proposal.schema.json').read_text())).validate(a)
