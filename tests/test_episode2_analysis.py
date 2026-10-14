from copy import deepcopy

import pytest

from runpod_benchmark.episode2_corpus import CLASS_IDS, build_trace, make_synthetic_protocol
from test_episode2_runner import run, reply_for


def stable_run(protocol=None, **kwargs):
    def send(turn):
        value = reply_for(turn)
        start = value.actual_send_ns
        value.terminal_ns = start + 10
        if value.text:
            value.first_content_ns, value.last_content_ns = start+2, start+5
            value.content_events = [{"received_ns":start+2,"text":value.text[:1]},{"received_ns":start+5,"text":value.text[1:]}]
        else:
            value.tool_events[0]["received_ns"] = start+3
        return value
    return run(protocol, send=send, **kwargs)


def test_each_metric_and_claim_requires_its_own_count():
    from runpod_benchmark.episode2_analysis import eligible_percentile
    assert eligible_percentile([1000,1000])=='p99'
    assert eligible_percentile([1000,999])=='p95'
    assert eligible_percentile([10000,20])=='p95'
    assert eligible_percentile([])=='p95'


def test_gap_uses_raw_pooled_linear_rank_and_rejects_empty():
    from runpod_benchmark.episode2_analysis import absolute_gap
    assert absolute_gap([1,2,3,4],.95)==pytest.approx(1.35)
    with pytest.raises(ValueError): absolute_gap([],.95)


def test_bootstrap_reuses_whole_paired_blocks_and_is_deterministic():
    from runpod_benchmark.episode2_analysis import paired_block_interval
    pairs=[([1,10,100],[1,5,50]) for _ in range(6)]
    left=paired_block_interval(pairs,q=.95,resamples=100)
    right=paired_block_interval(pairs,q=.95,resamples=100)
    assert left==right and left['block_pairs']==6
    assert left['low_ms']==left['high_ms']==left['estimate_ms']
    assert left['estimate_ms']==pytest.approx(45.)


@pytest.mark.parametrize('pairs', [[], [([1,2],[1,2])]*5, [([1],[1])]*5+[([],[1])]])
def test_bootstrap_requires_six_complete_nonempty_pairs(pairs):
    from runpod_benchmark.episode2_analysis import paired_block_interval
    with pytest.raises(ValueError): paired_block_interval(pairs,q=.95,resamples=20)


def test_summary_retains_all_classes_and_tool_only_metric_counts():
    from runpod_benchmark.episode2_analysis import summarize_episode2
    protocol=make_synthetic_protocol(); summary=summarize_episode2(run(protocol),protocol)
    assert summary['counts']['scheduled_requests']==72
    assert summary['counts']['sent_requests']==72
    assert summary['counts']['qualified_requests']==72
    assert set(summary['classes'])==set(CLASS_IDS)
    assert summary['classes']['tool_call']['metrics']['e2e_ms']['count']==12
    assert summary['classes']['tool_call']['metrics']['ttft_ms']['count']==6
    assert summary['metrics']['workflow_e2e_ms']['count']==48
    assert summary['metrics']['e2e_ms']['headline_percentile']=='p95'
    assert summary['metrics']['e2e_ms']['p99_label']=='descriptive p99'
    assert summary['goodput']['available'] is False


def test_cancelled_summary_keeps_unavailable_metrics_and_full_denominator():
    from runpod_benchmark.episode2_analysis import summarize_episode2
    protocol=make_synthetic_protocol(); value=summarize_episode2(run(protocol,stop=lambda:True),protocol)
    assert value['counts']['scheduled_requests']==72 and value['counts']['sent_requests']==0
    assert value['counts']['cancelled_requests']==72 and value['counts']['qualified_requests']==0
    assert all(not row['metrics']['e2e_ms']['available'] for row in value['classes'].values())


def test_synthetic_missing_cost_resource_and_physical_lineage_is_inconclusive():
    from runpod_benchmark.episode2_analysis import compare_arms
    protocol=make_synthetic_protocol()
    value=compare_arms(stable_run(protocol),stable_run(protocol,arm='treatment'),protocol)
    assert value['status'] in {'inconclusive','rejected'}
    assert value['safeguards']['attributable_cost']['status']=='inconclusive'
    assert value['safeguards']['resource']['status']=='inconclusive'
    assert value['safeguards']['goodput']['status']=='inconclusive'
    assert value['winner'] is None


def test_changed_requested_work_is_incompatible_even_when_timing_is_faster():
    from runpod_benchmark.episode2_analysis import compare_arms
    protocol=make_synthetic_protocol(); left,right=run(protocol),run(protocol,arm='treatment')
    right['observations'][0]['requested_output_tokens']=1
    with pytest.raises(ValueError): compare_arms(left,right,protocol)


def test_schema_rejects_private_extra_fields_in_public_projection():
    import json
    from pathlib import Path
    from jsonschema import Draft202012Validator
    from runpod_benchmark.episode2_analysis import summarize_episode2
    protocol=make_synthetic_protocol(); value=summarize_episode2(run(protocol),protocol)
    schema=json.loads(Path('schemas/episode2-public-aggregate.schema.json').read_text())
    validator=Draft202012Validator(schema); validator.validate(value)
    value['provider_handle']='private-canary'
    assert list(validator.iter_errors(value))


def test_skewed_blocks_pool_samples_instead_of_averaging_percentiles():
    from runpod_benchmark.episode2_analysis import paired_block_interval
    pairs=[([0]*100+[100],[0]*101)]+[([10],[0]) for _ in range(5)]
    assert paired_block_interval(pairs,q=.95,resamples=30)['estimate_ms']==pytest.approx(7.5)


def test_broad_paired_interval_retains_both_signs():
    from runpod_benchmark.episode2_analysis import paired_block_interval
    pairs=[([0,100],[0,10])]*3+[([0,10],[0,100])]*3
    interval=paired_block_interval(pairs,q=.95,resamples=200)
    assert interval['low_ms']<0<interval['high_ms']


def test_zero_count_never_receives_p99_headline():
    from runpod_benchmark.episode2_analysis import eligible_percentile
    with pytest.raises(ValueError): eligible_percentile([True,1000])
    assert eligible_percentile([0,10000])=='p95'


def test_comparison_schema_covers_counts_uncertainty_and_closed_subgroups():
    import json
    from pathlib import Path
    from jsonschema import Draft202012Validator
    from runpod_benchmark.episode2_analysis import compare_arms
    protocol=make_synthetic_protocol()
    value=compare_arms(stable_run(protocol),stable_run(protocol,arm='treatment'),protocol)
    validator=Draft202012Validator(json.loads(Path('schemas/episode2-public-aggregate.schema.json').read_text()))
    validator.validate(value)
    value['classes']['short']['private_config']={'canary_marker':'unreviewed'}
    assert list(validator.iter_errors(value))


def bounded_protocol():
    protocol=make_synthetic_protocol()
    protocol['quality']['output_length_tolerance_fraction']=0
    protocol['safeguards'].update(e2e_slo_ms=1.,ttft_slo_ms=1.,tpot_slo_ms=1.,goodput_min_tokens_per_second=1.,admission_rate_min=1.,cost_max_usd='1.00',resource_max={'gpu_memory_fraction':.9,'host_memory_fraction':.9,'host_cpu_percent':90.})
    return protocol


def test_unbound_cost_and_resource_samples_remain_unavailable():
    from runpod_benchmark.episode2_analysis import compare_arms
    protocol=bounded_protocol(); left,right=stable_run(protocol),stable_run(protocol,arm='treatment')
    for result in (left,right):
        result['window']['safeguard_evidence']={'cost':{'status':'settled','attributable':True,'usd':'0.10','source_sha256':'a'*64,'measured_window_sha256':'b'*64},'resource':{'metrics':{'gpu_memory_fraction':.1,'host_memory_fraction':.1,'host_cpu_percent':1.},'source_sha256':'a'*64,'measured_window_sha256':'b'*64}}
    value=compare_arms(left,right,protocol)
    assert value['safeguards']['attributable_cost']['status']=='inconclusive'
    assert value['safeguards']['resource']['status']=='inconclusive'


def test_reduced_tail_gap_with_slower_median_is_rejected():
    from runpod_benchmark.episode2_analysis import compare_arms
    protocol=bounded_protocol(); left,right=stable_run(protocol),stable_run(protocol,arm='treatment')
    for row in right['observations']:
        row['terminal_ns']+=1
        row['e2e_ms']=(row['terminal_ns']-row['actual_send_ns'])/1e6
    for attempt in right['attempts']:
        if attempt['phase']=='measured': attempt['end_ns']+=1
    value=compare_arms(left,right,protocol)
    assert value['safeguards']['median']['status']=='rejected' and value['status']=='rejected' and value['winner'] is None


def test_companion_slo_breach_rejects_even_when_e2e_gap_is_unchanged():
    from runpod_benchmark.episode2_analysis import compare_arms
    protocol=bounded_protocol(); protocol['safeguards']['ttft_slo_ms']=.000001
    value=compare_arms(stable_run(protocol),stable_run(protocol,arm='treatment'),protocol)
    assert value['classes']['short']['safeguards']['ttft_ms']['status']=='rejected'


def test_cold_cell_cannot_satisfy_primary_warm_tail_scope():
    from runpod_benchmark.episode2_analysis import compare_arms
    protocol=bounded_protocol(); protocol['cells'][0]['temperature']='cold'
    value=compare_arms(stable_run(protocol),stable_run(protocol,arm='treatment'),protocol)
    assert value['safeguards']['primary_cell']['status']=='inconclusive'


def test_missing_output_tolerance_never_establishes_matching():
    from runpod_benchmark.episode2_validity import matched_work
    protocol=make_synthetic_protocol(); left,right=stable_run(protocol),stable_run(protocol)
    left['physical_gpu_private_ref']=right['physical_gpu_private_ref']='private-same-allocation'
    value=matched_work(left,right,protocol)
    assert value['status']=='inconclusive' and 'tolerance' in str(value)


def test_bound_cost_and_resource_limit_breaches_are_rejected():
    from runpod_benchmark.episode2_contract import document_digest
    from runpod_benchmark.episode2_analysis import compare_arms
    protocol=bounded_protocol(); left,right=stable_run(protocol),stable_run(protocol,arm='treatment')
    for result in (left,right):
        windows=[{'block_id':row['block_id'],'start_ns':row['start_ns'],'end_ns':row['end_ns']} for row in result['blocks']]
        binding={'source_sha256':'a'*64,'measured_window_sha256':document_digest(windows)}
        result['window']['safeguard_evidence']={'cost':{**binding,'status':'settled','attributable':True,'usd':'1.01'},'resource':{**binding,'metrics':{'gpu_memory_fraction':.95,'host_memory_fraction':.1,'host_cpu_percent':1.}}}
    value=compare_arms(left,right,protocol)
    assert value['safeguards']['attributable_cost']['status']=='rejected'
    assert value['safeguards']['resource']['status']=='rejected'
    assert value['status']=='rejected' and value['winner'] is None


def test_each_summary_metric_has_independent_p99_eligibility():
    from runpod_benchmark.episode2_analysis import _metric
    assert _metric([1.]*1000)['headline_percentile']=='p99'
    assert _metric([1.]*999)['headline_percentile']=='p95'
    assert _metric([1.]*20)['p99_label']=='descriptive p99'
    assert _metric([])['unavailable_reason']=='no applicable qualified observations'


def test_tool_event_distribution_has_its_own_applicable_count():
    from runpod_benchmark.episode2_analysis import summarize_episode2
    protocol=make_synthetic_protocol(); value=summarize_episode2(stable_run(protocol),protocol)
    assert value['metrics']['tool_event_latency_ms']['count']==12
    assert value['classes']['tool_call']['metrics']['tool_event_latency_ms']['count']==6
    assert value['classes']['short']['metrics']['tool_event_latency_ms']['available'] is False


def test_broad_class_interval_cannot_verify_a_subgroup_safeguard():
    from runpod_benchmark.episode2_analysis import compare_arms
    protocol=bounded_protocol(); left,right=stable_run(protocol),stable_run(protocol,arm='treatment')
    for result,reverse in ((left,False),(right,True)):
        for row in result['observations']:
            early=int(row['block_id'].split('-')[1])<=3
            duration=10 if early!=reverse else 50
            row['terminal_ns']=row['actual_send_ns']+duration
            row['e2e_ms']=duration/1e6
        rows={row['attempt_id']:row for row in result['observations']}
        for attempt in result['attempts']:
            if attempt['phase']=='measured':attempt['end_ns']=rows[attempt['attempt_id']]['terminal_ns']
    value=compare_arms(left,right,protocol)
    interval=value['classes']['short']['metrics']['e2e_ms']['interval']
    assert interval['low_ms']<0<interval['high_ms']
    assert value['classes']['short']['safeguards']['e2e_ms']['status']=='inconclusive'
    assert value['winner'] is None
