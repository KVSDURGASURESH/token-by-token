from copy import deepcopy
import pytest
from runpod_benchmark.episode2_telemetry import align_signals


def result():
    return {'execution_id':'run-1','engine':'vllm','arm':'defaults','cell_id':'closed-loop-c2-warm','runtime_version':'0.29.0','window':{'start_ns':10000000,'end_ns':12000000}}


def signal(name='queue_wait_ms',unit='ms',scope='runtime'):
    return {'name':name,'runtime':'vllm','version':'0.29.0','unit':unit,'scope':scope,'source':'pinned_native_mapping','execution_id':'run-1','engine':'vllm','arm':'defaults','cell_id':'closed-loop-c2-warm','block_id':'block-01','clock_domain':'client_monotonic','window':{'start_ns':10000000,'end_ns':12000000},'cadence_ns':1000000,'offset_ns':0,'uncertainty_ns':0,'kind':'gauge','samples':[{'timestamp_ns':n,'value':v,'process_attributed':True} for n,v in [(10000000,2),(11000000,3),(12000000,4)]],'unavailable_reason':None}


def test_aligned_native_gauge_preserves_samples_and_scope():
    aligned=align_signals(result(),[signal()],{})
    assert aligned['available_signals']==['queue_wait_ms']
    assert aligned['signals'][0]['samples'][1]['value']==3
    assert aligned['signals'][0]['block_id']=='block-01'


@pytest.mark.parametrize('field,value,reason',[
    ('unit','tokens','unit'),('execution_id','other','identity'),
    ('clock_domain','unknown','clock'),('uncertainty_ns',1000001,'uncertainty'),
    ('version','0.1','version'),
])
def test_incompatible_signals_are_explicitly_unavailable(field,value,reason):
    s=signal();s[field]=value
    aligned=align_signals(result(),[s],{})
    assert aligned['available_signals']==[]
    assert reason in aligned['signals'][0]['unavailable_reason']


def test_missing_window_coverage_and_cadence_gaps_are_unavailable():
    s=signal();s['window']['start_ns']=11000000;s['samples']=s['samples'][1:]
    assert 'coverage' in align_signals(result(),[s],{})['signals'][0]['unavailable_reason']
    s=signal();s['samples']=s['samples'][:1]
    assert 'coverage' in align_signals(result(),[s],{})['signals'][0]['unavailable_reason']


def test_counter_reset_and_gpu_misattribution_remain_unavailable():
    s=signal();s['kind']='counter';s['samples'][-1]['value']=0
    assert 'reset' in align_signals(result(),[s],{})['signals'][0]['unavailable_reason']
    s=signal('gpu_utilization_percent','percent','gpu');s['samples'][1]['process_attributed']=False
    assert 'attribution' in align_signals(result(),[s],{})['signals'][0]['unavailable_reason']


def test_clock_offset_is_applied_with_explicit_uncertainty():
    s=signal();s['clock_domain']='remote_monotonic';s['offset_ns']=1000000;s['uncertainty_ns']=100
    s['window']={k:v-1000000 for k,v in s['window'].items()}
    for row in s['samples']:row['timestamp_ns']-=1000000
    aligned=align_signals(result(),[s],{})
    assert aligned['signals'][0]['samples'][0]['timestamp_ns']==10000000
    assert aligned['signals'][0]['uncertainty_ns']==100


def test_nonfinite_values_and_unknown_fields_are_rejected():
    for s in [signal(),signal()]:
        s['samples'][0]['value']=float('nan')
        with pytest.raises(ValueError):align_signals(result(),[s],{})
    s=signal();s['private_unbound_config']='canary'
    with pytest.raises(ValueError):align_signals(result(),[s],{})


def test_converted_timestamps_are_labeled_client_monotonic():
    s=signal();s['clock_domain']='remote_monotonic';s['offset_ns']=1000000
    s['window']={k:v-1000000 for k,v in s['window'].items()}
    for row in s['samples']:row['timestamp_ns']-=1000000
    row=align_signals(result(),[s],{})['signals'][0]
    assert row['clock_domain']=='client_monotonic'
    assert row['source_clock_domain']=='remote_monotonic'


def test_runtime_version_can_be_bound_in_the_measured_result_window():
    r=result();version=r.pop('runtime_version');r['window']['runtime_version']=version
    assert align_signals(r,[signal()],{})['available_signals']==['queue_wait_ms']


def test_coverage_uses_the_matched_block_window_not_other_engine_idle_gaps():
    r=result();r['blocks']=[{'block_id':'block-01','start_ns':10000000,'end_ns':12000000},{'block_id':'block-02','start_ns':90000000,'end_ns':92000000}];r['window'].update(start_ns=10000000,end_ns=92000000)
    assert align_signals(r,[signal()],{})['available_signals']==['queue_wait_ms']
    s=signal();s['block_id']='block-99'
    assert 'block' in align_signals(r,[s],{})['signals'][0]['unavailable_reason']
