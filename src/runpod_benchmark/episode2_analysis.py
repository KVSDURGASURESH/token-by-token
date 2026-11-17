"""Raw pooled Episode 02 tails, paired block uncertainty and fail-closed safeguards."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math
import random
import re

from .episode2_contract import CLASS_IDS, document_digest, require
from .episode2_corpus import build_trace
from .episode2_validity import finite_nonnegative, matched_work, qualify_turn, validate_observations
from .metrics import linear_percentile

METRICS = ('e2e_ms', 'ttft_ms', 'tpot_ms', 'tool_event_latency_ms', 'workflow_e2e_ms')


def eligible_percentile(counts: list[int]) -> str:
    require(all(type(count) is int and count >= 0 for count in counts), 'invalid applicable observation count')
    return 'p99' if counts and min(counts) >= 1000 else 'p95'


def absolute_gap(values: list[float], q: float) -> float:
    require(bool(values), 'nonempty gap distribution required')
    require(type(q) in (int, float) and math.isfinite(q) and .5 <= q <= 1, 'tail quantile required')
    for value in values: finite_nonnegative(value, 'latency')
    return linear_percentile(values, q) - linear_percentile(values, .5)


def paired_block_interval(pairs: list[tuple[list[float], list[float]]], *, q: float,
                          seed: int = 42, resamples: int = 2000, confidence: float = .95) -> dict:
    require(6 <= len(pairs) <= 8 and type(seed) is int and seed >= 0, 'six through eight complete block pairs required')
    require(type(resamples) is int and 1 <= resamples <= 20000 and type(confidence) in (int, float) and 0 < confidence < 1, 'invalid bootstrap contract')
    for left, right in pairs:
        require(bool(left) and bool(right), 'every block pair needs applicable samples in both arms')
        absolute_gap(left, q); absolute_gap(right, q)
    def difference(selected):
        left = [value for index in selected for value in pairs[index][0]]
        right = [value for index in selected for value in pairs[index][1]]
        return absolute_gap(left, q) - absolute_gap(right, q)
    estimate = difference(range(len(pairs)))
    rng = random.Random(seed)
    draws = [difference([rng.randrange(len(pairs)) for _ in pairs]) for _ in range(resamples)]
    alpha = (1-confidence)/2
    return {'method':'paired_whole_block_bootstrap','block_pairs':len(pairs),'resamples':resamples,
            'confidence':confidence,'seed':seed,'estimate_ms':estimate,
            'low_ms':linear_percentile(draws,alpha),'high_ms':linear_percentile(draws,1-alpha)}


def _metric(values: list[float]) -> dict:
    count = len(values)
    return {'count':count, 'available':bool(count), 'unavailable_reason':None if count else 'no applicable qualified observations',
            'percentile_method':'linear_rank_n_minus_1','headline_percentile':eligible_percentile([count]),
            'p50':linear_percentile(values,.5), 'p95':linear_percentile(values,.95), 'p99':linear_percentile(values,.99),
            'p99_label':'eligible p99' if count >= 1000 else 'descriptive p99' if count else 'unavailable'}


def _trace(result: dict, protocol: dict) -> dict:
    trace = build_trace(protocol)
    trace['mode'] = result['window']['mode']
    return trace


def _qualified(row: dict, protocol: dict) -> dict:
    span = (row['last_content_ns']-row['first_content_ns'])/1e6 if row['first_content_ns'] is not None else None
    return qualify_turn({**row, 'content_span_ms':span},protocol)


def _counts(rows: list[dict], protocol: dict) -> dict:
    sent = [row for row in rows if row['attempt_id'] is not None]
    return {'scheduled_requests':len(rows),'attempted_requests':len(rows),'sent_requests':len(sent),
            'terminal_successful_requests':sum(row['success'] for row in rows),
            'qualified_requests':sum(_qualified(row,protocol)['qualified'] for row in rows),
            'error_requests':sum(row['status'] != 'success' for row in sent),
            'dropped_requests':sum(row['status']=='admission_dropped' for row in rows),
            'dependency_blocked_requests':sum(row['status']=='dependency_blocked' for row in rows),
            'cancelled_requests':sum(row['status']=='cancelled' for row in rows),
            'other_unsent_requests':sum(row['status'] in {'continuation_mismatch','warmup_failed'} for row in rows)}


def _vectors(result: dict, protocol: dict, class_id: str | None = None, block_id: str | None = None) -> dict:
    rows = [row for row in result['observations'] if (class_id is None or row['class_id']==class_id) and (block_id is None or row['block_id']==block_id)]
    qualified = [_qualified(row,protocol) for row in rows]
    vectors = {name:[row[name] for row in qualified if row[name] is not None] for name in METRICS[:-1]}
    vectors['workflow_e2e_ms'] = [row['workflow_e2e_ms'] for row in result['workflow_observations'] if row['success'] and (class_id is None or row['class_id']==class_id) and (block_id is None or row['block_id']==block_id)]
    return vectors


def _goodput(result: dict, protocol: dict, class_id: str | None = None) -> dict:
    duration = result['window']['measured_duration_ns']/1e9
    slos = {name:protocol['safeguards'][f'{name.removesuffix("_ms")}_slo_ms'] for name in ('e2e_ms','ttft_ms','tpot_ms') if f'{name.removesuffix("_ms")}_slo_ms' in protocol['safeguards']}
    if not slos or duration <= 0:
        return {'available':False,'reason':'nonempty frozen SLOs and positive measured duration required','qualified_requests':0,'qualified_tokens':None,'tokens_per_second':None}
    tokens = count = 0
    for row in result['observations']:
        if class_id is not None and row['class_id'] != class_id: continue
        value = _qualified(row,protocol)
        if value['qualified'] and all(value[name] is None or value[name] <= limit for name,limit in slos.items()):
            count += 1; tokens += row['output_tokens']
    return {'available':True,'reason':None,'qualified_requests':count,'qualified_tokens':tokens,'tokens_per_second':tokens/duration}


def _bound_evidence(result: dict, name: str) -> dict | None:
    evidence = result['window'].get('safeguard_evidence',{}).get(name)
    if not isinstance(evidence,dict): return None
    windows = [{'block_id':row['block_id'],'start_ns':row['start_ns'],'end_ns':row['end_ns']} for row in result['blocks']]
    if evidence.get('measured_window_sha256') != document_digest(windows) or not isinstance(evidence.get('source_sha256'),str) or re.fullmatch('[0-9a-f]{64}',evidence['source_sha256']) is None:
        return None
    fields={'source_sha256','measured_window_sha256'}
    if name=='cost':
        if set(evidence)!=fields|{'status','attributable','usd'} or evidence['status'] not in {'settled','provisional','unavailable'} or type(evidence['attributable']) is not bool or not isinstance(evidence['usd'],str): return None
        try:
            amount=Decimal(evidence['usd'])
            if not amount.is_finite() or amount<0: return None
        except InvalidOperation: return None
    elif name=='resource':
        names={'gpu_memory_fraction','host_memory_fraction','host_cpu_percent'}
        if set(evidence)!=fields|{'metrics'} or not isinstance(evidence['metrics'],dict) or set(evidence['metrics'])!=names: return None
        if any(type(value) not in (int,float) or not math.isfinite(value) or value<0 for value in evidence['metrics'].values()): return None
    return evidence


def summarize_episode2(result: dict, protocol: dict) -> dict:
    validate_observations(result,protocol,_trace(result,protocol))
    classes = {}
    for class_id in CLASS_IDS:
        rows = [row for row in result['observations'] if row['class_id']==class_id]
        classes[class_id] = {'counts':_counts(rows,protocol),'metrics':{name:_metric(values) for name,values in _vectors(result,protocol,class_id).items()}}
    metrics = {name:_metric(values) for name,values in _vectors(result,protocol).items()}
    counts = _counts(result['observations'],protocol)
    duration = result['window']['measured_duration_ns']/1e9
    terminal_tokens = sum(row['output_tokens'] for row in result['observations'] if row['success'])
    qualified_tokens = sum(row['output_tokens'] for row in result['observations'] if _qualified(row,protocol)['qualified'])
    cost = _bound_evidence(result,'cost')
    resource = _bound_evidence(result,'resource')
    return {'schema_version':'episode2.public-aggregate.v1','evidence_class':result['evidence_class'],
        'source_sha256':document_digest(result),'protocol_sha256':result['protocol_sha256'],'trace_sha256':result['trace_sha256'],
        'engine':result['engine'],'arm':result['arm'],'cell_id':result['cell_id'],
        'mode':result['window']['mode'],'temperature':result['window']['temperature'],
        'mixture':{'weights':dict(protocol['mixture']['weights']),'units_per_class':protocol['mixture']['units_per_class']},
        'counts':counts,'metrics':metrics,'classes':classes,
        'blocks':[{'block_id':block['block_id'],'counts':_counts([row for row in result['observations'] if row['block_id']==block['block_id']],protocol),'metrics':{name:_metric(values) for name,values in _vectors(result,protocol,block_id=block['block_id']).items()}} for block in result['blocks']],
        'output':{'terminal_success_tokens':terminal_tokens,'qualified_tokens':qualified_tokens,'tokens_per_second':terminal_tokens/duration if duration>0 else None},
        'error_rate':counts['error_requests']/counts['sent_requests'] if counts['sent_requests'] else None,
        'quality_fraction':counts['qualified_requests']/counts['scheduled_requests'],
        'goodput':_goodput(result,protocol),
        'cost_status':cost.get('status','unavailable') if cost and cost.get('status') in {'settled','provisional','unavailable'} else 'unavailable',
        'resource_status':'available' if resource else 'unavailable',
        'cleanup_status':result['window'].get('cleanup_status','unverified') if result['window'].get('cleanup_status') in {'verified','failed','unverified'} else 'unverified',
        'uncertainty':{'method':'paired_whole_block_bootstrap','independent_blocks':len(result['blocks']),'status':'requires_paired_arm_comparison'},
        'hypotheses':[],'arms_lineage':[]}


def _gate(status: str, reason: str | None = None) -> dict:
    return {'status':status,'reason':reason}


def _comparison_metric(left: dict, right: dict, protocol: dict, name: str, class_id: str | None = None) -> dict:
    a,b = _vectors(left,protocol,class_id)[name],_vectors(right,protocol,class_id)[name]
    label = eligible_percentile([len(a),len(b)]); q = .99 if label=='p99' else .95
    if not a or not b:
        return {'status':'inconclusive','percentile':label,'baseline_count':len(a),'treatment_count':len(b),'baseline_p50_ms':None,'treatment_p50_ms':None,'baseline_tail_ms':None,'treatment_tail_ms':None,'baseline_gap_ms':None,'treatment_gap_ms':None,'gap_difference_ms':None,'interval':None}
    pairs = [(_vectors(left,protocol,class_id,block['block_id'])[name],_vectors(right,protocol,class_id,block['block_id'])[name]) for block in left['blocks']]
    interval = None
    if all(a and b for a,b in pairs):
        interval = paired_block_interval(pairs,q=q,seed=protocol['uncertainty']['seed'],resamples=protocol['uncertainty']['resamples'],confidence=protocol['uncertainty']['confidence'])
    status = 'supported' if interval and interval['low_ms']>0 else 'rejected' if interval and interval['high_ms']<0 else 'inconclusive'
    return {'status':status,'percentile':label,'baseline_count':len(a),'treatment_count':len(b),
            'baseline_p50_ms':linear_percentile(a,.5),'treatment_p50_ms':linear_percentile(b,.5),
            'baseline_tail_ms':linear_percentile(a,q),'treatment_tail_ms':linear_percentile(b,q),
            'baseline_gap_ms':absolute_gap(a,q),'treatment_gap_ms':absolute_gap(b,q),
            'gap_difference_ms':absolute_gap(a,q)-absolute_gap(b,q),'interval':interval}


def compare_arms(baseline: dict, treatment: dict, protocol: dict) -> dict:
    left,right = summarize_episode2(baseline,protocol),summarize_episode2(treatment,protocol)
    matching = matched_work(baseline,treatment,protocol)
    safeguards = {}
    safe = protocol['safeguards']
    safeguards['material']=_gate('verified' if protocol['material']['execution_ready'] is True else 'inconclusive','material contract is not execution ready' if protocol['material']['execution_ready'] is not True else None)
    safeguards['work'] = _gate('verified' if matching['equivalent'] else 'rejected' if matching['status']=='incompatible' else 'inconclusive','; '.join(matching['reasons']) or None)
    safeguards['evidence_class'] = _gate('verified' if baseline['evidence_class']==treatment['evidence_class']=='recorded' else 'inconclusive','synthetic evidence cannot establish a measured winner' if baseline['evidence_class']!='recorded' else None)
    for name, field, threshold, direction in [('quality','quality_fraction',safe['quality_min'],'min'),('errors','error_rate',safe['error_rate_max'],'max')]:
        values=[left[field],right[field]]
        safeguards[name]=_gate('inconclusive' if any(value is None for value in values) else 'verified' if all(value>=threshold if direction=='min' else value<=threshold for value in values) else 'rejected')
    p50=right['metrics']['e2e_ms']['p50']; base_p50=left['metrics']['e2e_ms']['p50']
    safeguards['median']=_gate('inconclusive' if p50 is None or base_p50 is None else 'verified' if p50<=safe['median_ceiling_ms'] and p50<=base_p50 else 'rejected')
    floor=safe.get('admission_rate_min')
    rates=[sum(row['status']=='admitted' for row in result['admissions'])/len(result['admissions']) for result in (baseline,treatment)]
    safeguards['admission']=_gate('inconclusive' if floor is None else 'verified' if min(rates)>=floor else 'rejected')
    floor=safe.get('goodput_min_tokens_per_second')
    good=[value['goodput']['tokens_per_second'] for value in (left,right)]
    safeguards['goodput']=_gate('inconclusive' if floor is None or any(value is None for value in good) else 'verified' if min(good)>=floor else 'rejected')
    costs=[_bound_evidence(result,'cost') for result in (baseline,treatment)]
    cost_max=safe.get('cost_max_usd')
    try:
        costs_ok=cost_max is not None and all(cost and cost.get('status')=='settled' and cost.get('attributable') is True and isinstance(cost.get('usd'),str) and Decimal(cost['usd']).is_finite() and Decimal(cost['usd'])>=0 for cost in costs)
        safeguards['attributable_cost']=_gate('inconclusive' if not costs_ok else 'verified' if all(Decimal(cost['usd'])<=Decimal(cost_max) for cost in costs) else 'rejected')
    except InvalidOperation:
        safeguards['attributable_cost']=_gate('inconclusive','invalid attributable cost evidence')
    resources=[_bound_evidence(result,'resource') for result in (baseline,treatment)]
    bounds=safe.get('resource_max')
    resource_ok=isinstance(bounds,dict) and all(resource and isinstance(resource.get('metrics'),dict) and set(resource['metrics'])==set(bounds) and all(type(resource['metrics'][name]) in (int,float) and math.isfinite(resource['metrics'][name]) and resource['metrics'][name]>=0 for name in bounds) for resource in resources)
    safeguards['resource']=_gate('inconclusive' if not resource_ok else 'verified' if all(all(resource['metrics'][name]<=threshold for name,threshold in bounds.items()) for resource in resources) else 'rejected')
    safeguards['reset']=_gate('verified' if all(result['window'].get('readiness_status')=='verified' and result['window'].get('cache_reset_status')=='verified' for result in (baseline,treatment)) else 'inconclusive')
    desired_mode='open-loop' if any(cell['mode']=='open-loop' and cell['temperature']=='warm' for cell in protocol['cells']) else 'closed-loop'
    safeguards['primary_cell']=_gate('verified' if left['temperature']=='warm' and left['mode']==desired_mode else 'inconclusive','primary requires frozen warm stress cell or warm closed-loop fallback')
    overall_metrics={name:_comparison_metric(baseline,treatment,protocol,name) for name in METRICS}
    primary=overall_metrics['e2e_ms']
    subgroups={}
    subgroup_failed=False; subgroup_missing=False
    for class_id in CLASS_IDS:
        comparisons={name:_comparison_metric(baseline,treatment,protocol,name,class_id) for name in METRICS}
        a,b=left['classes'][class_id],right['classes'][class_id]
        n=a['counts']['scheduled_requests']; m=b['counts']['scheduled_requests']
        quality=n>0 and m>0 and a['counts']['qualified_requests']/n>=safe['quality_min'] and b['counts']['qualified_requests']/m>=safe['quality_min']
        med=comparisons['e2e_ms']; median_ok=med['treatment_p50_ms'] is not None and med['baseline_p50_ms'] is not None and med['treatment_p50_ms']<=safe['median_ceiling_ms'] and med['treatment_p50_ms']<=med['baseline_p50_ms']
        class_error_rates=[group['counts']['error_requests']/group['counts']['sent_requests'] if group['counts']['sent_requests'] else None for group in (a,b)]
        class_admissions=[[row for row in result['admissions'] if row['class_id']==class_id] for result in (baseline,treatment)]
        class_rates=[sum(row['status']=='admitted' for row in rows)/len(rows) if rows else None for rows in class_admissions]
        class_good=[_goodput(result,protocol,class_id)['tokens_per_second'] for result in (baseline,treatment)]
        gates={'errors':_gate('inconclusive' if any(value is None for value in class_error_rates) else 'verified' if max(class_error_rates)<=safe['error_rate_max'] else 'rejected'),
               'admission':_gate('inconclusive' if 'admission_rate_min' not in safe or any(value is None for value in class_rates) else 'verified' if min(class_rates)>=safe['admission_rate_min'] else 'rejected'),
               'goodput':_gate('inconclusive' if any(value is None for value in class_good) else 'verified' if class_good[1]>=class_good[0] else 'rejected'),
               'quality':_gate('verified' if quality else 'rejected'),'median':_gate('verified' if median_ok else 'rejected' if med['treatment_p50_ms'] is not None else 'inconclusive')}
        for name,comparison in comparisons.items():
            if name=='tool_event_latency_ms':
                continue  # Diagnostic applicability is separate from frozen content SLOs.
            if comparison['baseline_count']==comparison['treatment_count']==0:
                gates[name]=_gate('inconclusive','no applicable class observations')
            elif comparison['status']=='rejected': gates[name]=_gate('rejected','class tail gap worsened')
            elif comparison['treatment_p50_ms'] is not None and comparison['baseline_p50_ms'] is not None and comparison['treatment_p50_ms']>comparison['baseline_p50_ms']:
                gates[name]=_gate('rejected','absolute class metric median worsened')
            elif f'{name.removesuffix("_ms")}_slo_ms' in safe and comparison['treatment_tail_ms'] is not None and comparison['treatment_tail_ms']>safe[f'{name.removesuffix("_ms")}_slo_ms']:
                gates[name]=_gate('rejected','absolute class metric tail exceeds frozen SLO')
            elif comparison['interval'] is not None and comparison['interval']['low_ms']<0:
                gates[name]=_gate('inconclusive','paired class interval cannot exclude worsening')
            elif name!='workflow_e2e_ms' and f'{name.removesuffix("_ms")}_slo_ms' not in safe:
                gates[name]=_gate('inconclusive','metric SLO is not frozen')
            else: gates[name]=_gate('verified' if comparison['interval'] is not None else 'inconclusive')
        subgroup_failed |= any(value['status']=='rejected' for value in gates.values())
        subgroup_missing |= any(value['status']=='inconclusive' for value in gates.values())
        subgroups[class_id]={'metrics':comparisons,'safeguards':gates}
    rejected=any(value['status']=='rejected' for value in safeguards.values()) or subgroup_failed or primary['status']=='rejected'
    verified=all(value['status']=='verified' for value in safeguards.values()) and not subgroup_missing and primary['status']=='supported'
    status='rejected' if rejected else 'accepted' if verified else 'inconclusive'
    return {'schema_version':'episode2.comparison.v1','protocol_sha256':left['protocol_sha256'],'trace_sha256':left['trace_sha256'],
            'baseline_source_sha256':left['source_sha256'],'treatment_source_sha256':right['source_sha256'],
            'primary_metric':'warm_'+left['mode']+'_request_e2e_ms' if left['temperature']=='warm' else 'cold_'+left['mode']+'_request_e2e_ms',
            'matched_work':matching,'primary':primary,'metrics':overall_metrics,'classes':subgroups,'safeguards':safeguards,'status':status,
            'winner':'treatment' if status=='accepted' else None}
