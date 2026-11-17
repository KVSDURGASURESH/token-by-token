"""Compute declared signature predicates from qualified recorded signal samples."""
from __future__ import annotations
from copy import deepcopy
import math
from .episode2_contract import canonical_bytes,document_digest,require
from .episode2_corpus import build_trace
from .episode2_telemetry import align_signals
from .episode2_validity import validate_observations,matched_work

HYPOTHESIS_KEYS={'id','mechanism','predicted_signature','confounders','control','required_signals','observations','intervention_lineage','disposition','limits'}
PREDICATE_KEYS={'signal','statistic','operator','threshold'}


def validate_hypothesis(hypothesis: dict) -> None:
    require(isinstance(hypothesis,dict) and set(hypothesis)==HYPOTHESIS_KEYS,'hypothesis fields are closed')
    require(hypothesis['disposition'] in {'supported','rejected','inconclusive'},'invalid disposition')
    for key in ('id','mechanism','control'):
        require(isinstance(hypothesis[key],str) and 1<=len(hypothesis[key])<=1024,f'invalid hypothesis {key}')
    for key in ('confounders','required_signals','observations','intervention_lineage','limits'):
        require(isinstance(hypothesis[key],list) and len(hypothesis[key])<=128 and all(isinstance(v,str) and 1<=len(v)<=1024 for v in hypothesis[key]),f'invalid hypothesis {key}')
    require(hypothesis['required_signals'] and len(set(hypothesis['required_signals']))==len(hypothesis['required_signals']),'required signal identities missing or duplicated')
    signature=hypothesis['predicted_signature']
    if isinstance(signature,str):
        require(1<=len(signature)<=1024,'invalid signature description')
        return  # Legacy prose remains a proposal, never a computed causal verdict.
    require(isinstance(signature,dict) and set(signature)=={'description','predicates','confounder_predicates'},'typed signature fields are closed')
    require(isinstance(signature['description'],str) and 1<=len(signature['description'])<=1024,'invalid signature description')
    require(isinstance(signature['predicates'],list) and 1<=len(signature['predicates'])<=32,'bounded signature predicates required')
    require(isinstance(signature['confounder_predicates'],dict) and set(signature['confounder_predicates'])==set(hypothesis['confounders']),'all confounders require declared sample predicates')
    for predicate in signature['predicates']+list(signature['confounder_predicates'].values()):
        require(isinstance(predicate,dict) and set(predicate)==PREDICATE_KEYS,'predicate fields are closed')
        require(predicate['signal'] in hypothesis['required_signals'],'predicate signal is not predeclared')
        require(predicate['statistic'] in {'mean','minimum','maximum'},'unsupported predicate statistic')
        require(predicate['operator'] in {'ge','gt','le','lt'},'unsupported predicate operator')
        require(type(predicate['threshold']) in (int,float) and math.isfinite(predicate['threshold']),'finite predicate threshold required')


def has_required_signals(hypothesis: dict,evidence: dict) -> bool:
    return set(hypothesis['required_signals'])<=set(evidence.get('available_signals',[]))


def _predicate(predicate,rows,blocks):
    operators={'ge':lambda a,b:a>=b,'gt':lambda a,b:a>b,'le':lambda a,b:a<=b,'lt':lambda a,b:a<b}
    for block in blocks:
        block_id=block["block_id"]
        matched=[row for row in rows if row['name']==predicate['signal'] and row['block_id']==block_id and row['available']]
        if len(matched)!=1:return None
        row=matched[0]
        values=[s['value'] for s in row['samples'] if block['start_ns']<=s['timestamp_ns']<=block['end_ns']]
        if not values:return None
        statistic={'mean':lambda v:sum(v)/len(v),'minimum':min,'maximum':max}[predicate['statistic']](values)
        if not operators[predicate['operator']](statistic,predicate['threshold']):return False
    return True


def _qualified(evidence,hypothesis):
    if not isinstance(evidence,dict) or set(evidence)!={'protocol','result','signals'}:return None
    protocol,result=evidence['protocol'],evidence['result']
    if protocol.get('classification')!='recorded' or result.get('evidence_class')!='recorded':return None
    validate_observations(result,protocol,build_trace(protocol))
    if any(not row['work_equivalent'] for row in result['observations']):return None
    aligned=align_signals(result,evidence['signals'],protocol)
    if not has_required_signals(hypothesis,aligned):return None
    blocks=result['blocks']
    signature=hypothesis['predicted_signature']
    values=[_predicate(p,aligned['signals'],blocks) for p in signature['predicates']]
    confounders=[_predicate(p,aligned['signals'],blocks) for p in signature['confounder_predicates'].values()]
    if any(v is None for v in values) or any(v is not True for v in confounders):return None
    return all(values),document_digest(evidence)


def evaluate_hypothesis(hypothesis: dict,evidence: dict,intervention: dict|None) -> dict:
    canonical_bytes([hypothesis,evidence,intervention]);validate_hypothesis(hypothesis)
    output=deepcopy(hypothesis);output.update(disposition='inconclusive',observations=[],intervention_lineage=[],limits=[])
    if not isinstance(hypothesis['predicted_signature'],dict):
        output['limits'].append('A prose or boolean signature is not a typed predicate over qualified samples.')
        return output
    baseline=_qualified(evidence,hypothesis)
    if baseline is None:
        output['limits'].append('Recorded qualified block signals and confounder sample controls are required.')
        return output
    output['observations'].append(baseline[1])
    if intervention is None:
        output['limits'].append('No recorded controlled intervention; correlation supports only a proposal.')
        return output
    fields={'id','hypothesis_id','evidence','control'}
    require(isinstance(intervention,dict) and set(intervention)==fields,'intervention fields are closed')
    require(isinstance(intervention['id'],str) and 1<=len(intervention['id'])<=256,'invalid intervention id')
    control=intervention['control']
    require(isinstance(control,dict) and set(control)=={'description','before','after'},'intervention control fields are closed')
    followup=_qualified(intervention['evidence'],hypothesis)
    left,right=evidence['result'],intervention['evidence']['result']
    match=matched_work(left,right,evidence['protocol'])
    allowed_missing={'changed effective configuration lacks verified treatment binding'}
    if (followup is None or followup[1]==baseline[1] or intervention['hypothesis_id']!=hypothesis['id'] or
        left['execution_id']==right['execution_id'] or left['engine']!=right['engine'] or
        control['description']!=hypothesis['control'] or not isinstance(control['before'],dict) or not isinstance(control['after'],dict) or
        document_digest(control['before'])!=left['effective_config_sha256'] or document_digest(control['after'])!=right['effective_config_sha256'] or
        canonical_bytes(control['before'])==canonical_bytes(control['after']) or
        match['status']=='incompatible' or set(match['reasons'])-allowed_missing):
        output['limits'].append('Distinct recorded equal-work intervention with bound changed configuration is required.')
        return output
    output['observations'].append(followup[1]);output['intervention_lineage'].append(intervention['id'])
    output['disposition']='supported' if baseline[0] and followup[0] else 'rejected'
    output['limits']=['Disposition applies only to the predeclared predicates, control, and measured workload; source authority requires independent evidence review.']
    return output
