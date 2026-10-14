"""No-spend optimization proposals from recorded controlled mechanism evidence."""
from __future__ import annotations
from copy import deepcopy
import math
import hashlib
from .episode2_contract import HEX,canonical_bytes,document_digest,require,validate_protocol,validate_trace
from .episode2_corpus import build_trace

GROUP_FLAGS={
    'chunked_prefill':{'chunked_prefill','max_num_batched_tokens','chunked_prefill_size','max_prefill_tokens'},
    'prefix_reuse':{'prefix_caching','radix_cache','cache_salt'},
    'batching':{'max_num_seqs','max_running_requests','max_batch_size'},
}
CONTROL_KEYS={'engine','version','help_sha256','defaults_sha256','hypothesis_id','group','before','after','support','coupled_flags','cache_reset_verified','evidence_class','runtime_proof','hypothesis_evidence'}


def _hash(value):return isinstance(value,str) and HEX.fullmatch(value) is not None


def work_digest(protocol: dict) -> str:
    frozen=deepcopy(protocol)
    frozen.pop('campaign_id')
    frozen['material']['execution_ready']=False
    return document_digest(frozen)


def _supports(value,rule):
    if not isinstance(rule,dict) or not set(rule)<={'type','minimum','maximum','enum'} or 'type' not in rule:return False
    types={'integer':(int,), 'number':(int,float),'boolean':(bool,),'string':(str,)}
    if type(value) not in types.get(rule['type'],()):return False
    if type(value) in (int,float) and not math.isfinite(value):return False
    if 'enum' in rule and not any(type(value) is type(v) and value==v for v in rule['enum']):return False
    if 'minimum' in rule and value<rule['minimum']:return False
    if 'maximum' in rule and value>rule['maximum']:return False
    return True


PINNED_VERSIONS={'vllm':'0.29.0','sglang':'0.5.20'}
# Public normalized control names are tied to the pinned native CLI flags.
NATIVE_FLAGS={'vllm':{'max_num_batched_tokens':'--max-num-batched-tokens','max_num_seqs':'--max-num-seqs','prefix_caching':'--enable-prefix-caching'},'sglang':{'chunked_prefill_size':'--chunked-prefill-size','max_prefill_tokens':'--max-prefill-tokens','max_running_requests':'--max-running-requests','radix_cache':'--disable-radix-cache'}}


def _runtime_proved(control,protocol):
    proof=control['runtime_proof'];engine=control['engine']
    if not isinstance(proof,dict) or set(proof)!={'help_text','defaults','image_digest'}:return False
    text=proof['help_text'];defaults=proof['defaults']
    if control['version']!=PINNED_VERSIONS.get(engine):return False
    if not isinstance(text,str) or not 1<=len(text)<=1024*1024 or hashlib.sha256(text.encode()).hexdigest()!=control['help_sha256']:return False
    if control['version'] not in text or proof['image_digest']!=protocol['material'][f'{engine}_image']:return False
    if not isinstance(defaults,dict) or set(defaults)!={'version','parameters'} or defaults['version']!=control['version'] or document_digest(defaults)!=control['defaults_sha256']:return False
    if not isinstance(defaults['parameters'],dict):return False
    for flag,value in control['before'].items():
        native=NATIVE_FLAGS[engine].get(flag)
        if native is None or native not in text or flag not in defaults['parameters'] or canonical_bytes(value)!=canonical_bytes(defaults['parameters'][flag]):return False
        # A caller cannot invent a broader supported scalar type/range.
        expected={'type':'boolean'} if flag in {'prefix_caching','radix_cache'} else {'type':'integer','minimum':1,'maximum':1048576}
        if control['support'].get(flag)!=expected:return False
    return True


def select_arms(hypotheses: list[dict],controls: dict,protocol: dict) -> list[dict]:
    """Return fully bound proposals only; no provider operation or spend authority."""
    canonical_bytes([hypotheses,controls,protocol])
    from .episode2_rca import HYPOTHESIS_KEYS,validate_hypothesis,evaluate_hypothesis
    supported={}
    for hypothesis in hypotheses:
        if not isinstance(hypothesis,dict) or set(hypothesis)!=HYPOTHESIS_KEYS:continue
        validate_hypothesis(hypothesis)
        if hypothesis['disposition']=='supported' and isinstance(hypothesis['predicted_signature'],dict) and hypothesis['intervention_lineage'] and len(set(hypothesis['observations']))>=2 and all(_hash(v) for v in hypothesis['observations']):
            require(hypothesis['id'] not in supported,'duplicate supported hypothesis')
            supported[hypothesis['id']]=hypothesis
    if not supported:return []
    validate_protocol(protocol)
    require(isinstance(controls,dict) and set(controls)=={'vllm','sglang'},'engine control map is closed')
    proposals=[]
    for engine,items in controls.items():
        require(isinstance(items,list) and len(items)<=64,'bounded control list required')
        for control in items:
            if not isinstance(control,dict) or set(control)!=CONTROL_KEYS:continue
            group=control['group'];before=control['before'];after=control['after']
            hypothesis=supported.get(control['hypothesis_id'])
            if hypothesis is None or group not in GROUP_FLAGS or any(group.replace('_',' ') in v or group in v for v in protocol['exclusions']):continue
            if control['engine']!=engine or control['evidence_class']!='recorded' or control['cache_reset_verified'] is not True:continue
            if not _hash(control['help_sha256']) or control['defaults_sha256']!=protocol['material'][f'{engine}_defaults_sha256']:continue
            if not isinstance(control['version'],str) or not control['version'] or len(control['version'])>64:continue
            if not isinstance(before,dict) or not isinstance(after,dict) or set(before)!=set(after) or not after or not set(after)<=GROUP_FLAGS[group]:continue
            if canonical_bytes(before)==canonical_bytes(after):continue
            support=control['support']
            if not isinstance(support,dict) or set(support)!=set(after) or any(not _supports(v,support[k]) or not _supports(before[k],support[k]) for k,v in after.items()):continue
            if not _runtime_proved(control,protocol):continue
            proof=control['hypothesis_evidence']
            if not isinstance(proof,dict) or set(proof)!={'baseline','intervention'}:continue
            evaluated=evaluate_hypothesis(hypothesis,proof['baseline'],proof['intervention'])
            if evaluated!=hypothesis or work_digest(proof['baseline']['protocol'])!=work_digest(protocol):continue
            if proof['intervention']['control']['before']!=before or proof['intervention']['control']['after']!=after:continue
            coupled=control['coupled_flags']
            if not isinstance(coupled,list) or len(coupled)>16 or any(not isinstance(v,str) or v not in after for v in coupled):continue
            proposal={'schema_version':'episode2.arm-proposal.v1','arm_id':f'{engine}-{group}-{len(proposals)+1}','engine':engine,'runtime_version':control['version'],'hypothesis_id':hypothesis['id'],'evidence_sha256':list(hypothesis['observations']),'control_sha256':document_digest(control),'source_protocol_sha256':document_digest(protocol),'frozen_work_sha256':work_digest(protocol),'trace_sha256':document_digest(build_trace(protocol)),'changed_group':group,'configuration_before':deepcopy(before),'configuration_after':deepcopy(after),'coupled_flags':list(coupled),'limits':['Attribution is limited to the declared control group and controlled evidence.','A new compiled plan and exact paid approval are required before any rerun.'],'execution_ready':False,'paid_approval_required':True}
            proposal['proposal_sha256']=document_digest(proposal)
            proposals.append(proposal)
    return proposals


def build_rerun(protocol: dict,proposal: dict,trace: dict) -> dict:
    """Preserve work; treatment settings stay in the separately compiled arm binding."""
    validate_trace(trace,protocol)
    require(proposal.get('schema_version')=='episode2.arm-proposal.v1','invalid proposal schema')
    sealed=deepcopy(proposal);digest=sealed.pop('proposal_sha256',None)
    require(digest==document_digest(sealed),'proposal changed after selection')
    require(proposal['source_protocol_sha256']==document_digest(protocol) and proposal['frozen_work_sha256']==work_digest(protocol),'frozen work changed')
    require(proposal['trace_sha256']==document_digest(trace),'rerun trace changed')
    require(proposal['execution_ready'] is False and proposal['paid_approval_required'] is True,'proposal is never spend authority')
    require(proposal['changed_group'] in GROUP_FLAGS and set(proposal['configuration_after'])<=GROUP_FLAGS[proposal['changed_group']],'unsupported optimization group')
    rerun=deepcopy(protocol)
    rerun['campaign_id']=protocol['campaign_id']+'-rerun-'+proposal['proposal_sha256'][:12]
    rerun['material']['execution_ready']=False
    validate_protocol(rerun)
    require(work_digest(rerun)==proposal['frozen_work_sha256'],'rerun changed delivered-work contract')
    return rerun
