"""Conservative window and clock qualification for Episode 02 signals."""
from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from .episode2_contract import canonical_bytes, require

MAX_CLOCK_UNCERTAINTY_NS = 1_000_000
SIGNAL_KEYS = {'name','runtime','version','unit','scope','source','execution_id','engine','arm','cell_id','block_id','clock_domain','window','cadence_ns','offset_ns','uncertainty_ns','kind','samples','unavailable_reason'}
# These are normalized quantities, not claims that every engine exposes them.
SIGNAL_UNITS = {
    'queue_wait_ms':'ms', 'prefill_ms':'ms', 'decode_ms':'ms',
    'client_send_lag_ms':'ms', 'client_eligible_send_lag_ms':'ms',
    'client_loop_lag_ms':'ms', 'transport_rtt_ms':'ms',
    'gpu_utilization_percent':'percent', 'gpu_memory_bytes':'bytes',
    'host_cpu_percent':'percent', 'host_memory_bytes':'bytes',
    'running_requests':'requests', 'waiting_requests':'requests',
    'kv_cache_percent':'percent', 'cache_hit_tokens':'tokens',
    'preemption_count':'events', 'batch_size':'requests',
}


def _integer(value: Any, *, nonnegative: bool = True) -> int:
    require(type(value) is int and (not nonnegative or value >= 0), 'invalid signal timestamp/integer')
    return value


def _window(value: Any) -> tuple[int,int]:
    require(isinstance(value,dict) and set(value)=={'start_ns','end_ns'},'invalid signal window')
    start,end=_integer(value['start_ns']),_integer(value['end_ns'])
    require(start < end,'empty or backward signal window')
    return start,end


def align_signals(result: dict, signals: list[dict], protocol: dict) -> dict:
    """Preserve missing coverage/attribution; never guess a native metric or clock."""
    canonical_bytes(signals)
    require(isinstance(signals,list) and len(signals)<=128,'bounded signal list required')
    measured_start,measured_end=_window({key:result['window'][key] for key in ('start_ns','end_ns')})
    aligned=[]
    identities=set()
    blocks=result.get('blocks',[])
    require(isinstance(blocks,list),'invalid measured block list')
    block_windows={block['block_id']:_window({key:block[key] for key in ('start_ns','end_ns')}) for block in blocks}
    require(len(block_windows)==len(blocks),'duplicate measured block identity')
    for raw in signals:
        require(isinstance(raw,dict) and set(raw)==SIGNAL_KEYS,'signal fields are closed')
        row=deepcopy(raw)
        for key in ('name','runtime','version','unit','scope','source','execution_id','engine','arm','cell_id','block_id','clock_domain','kind'):
            require(isinstance(row[key],str) and 1<=len(row[key])<=256,f'invalid signal {key}')
        require(row['scope'] in {'runtime','gpu','host','client'},'invalid signal scope')
        require(row['kind'] in {'gauge','counter'},'invalid signal kind')
        key=tuple(row[k] for k in ('name','execution_id','engine','arm','cell_id','block_id'))
        require(key not in identities,'duplicate signal identity');identities.add(key)
        start,end=_window(row['window'])
        cadence=_integer(row['cadence_ns']);require(cadence>0,'positive signal cadence required')
        offset=_integer(row['offset_ns'],nonnegative=False)
        uncertainty=_integer(row['uncertainty_ns'])
        require(isinstance(row['samples'],list) and len(row['samples'])<=100000,'bounded signal samples required')
        samples=[];last=None
        for sample in row['samples']:
            require(isinstance(sample,dict) and set(sample)=={'timestamp_ns','value','process_attributed'},'sample fields are closed')
            stamp=_integer(sample['timestamp_ns'])
            require(last is None or stamp>last,'signal sample timestamps must increase')
            require(start<=stamp<=end,'sample outside declared signal window');last=stamp
            value=sample['value']
            require(type(value) in (int,float) and math.isfinite(value) and value>=0,'signal value must be finite/nonnegative')
            require(type(sample['process_attributed']) is bool,'attribution boolean required')
            samples.append({**sample,'timestamp_ns':stamp+offset})
        require(row['unavailable_reason'] is None or (isinstance(row['unavailable_reason'],str) and 1<=len(row['unavailable_reason'])<=512),'invalid unavailable reason')
        reason=row['unavailable_reason']
        if block_windows and row['block_id'] not in block_windows:reason='block window binding unavailable'
        block_start,block_end=block_windows.get(row['block_id'],(measured_start,measured_end))
        if reason is None and any(row[k]!=result.get(k) for k in ('execution_id','engine','arm','cell_id')):reason='execution identity mismatch'
        if reason is None and row['runtime']!=result['engine']:reason='runtime identity mismatch'
        if reason is None and row['version']!=result.get('runtime_version',result.get('window',{}).get('runtime_version')):reason='runtime version is absent or mismatched'
        if reason is None and SIGNAL_UNITS.get(row['name'])!=row['unit']:reason='unmapped metric or incompatible unit'
        if reason is None and row['clock_domain'] not in {'client_monotonic','remote_monotonic'}:reason='unsupported clock domain'
        if reason is None and row['clock_domain']=='client_monotonic' and offset!=0:reason='client clock offset must be zero'
        if reason is None and uncertainty>MAX_CLOCK_UNCERTAINTY_NS:reason='clock uncertainty exceeds bound'
        if reason is None and (start+offset>block_start or end+offset<block_end):reason='measured window coverage unavailable'
        if reason is None and (not samples or samples[0]['timestamp_ns']>block_start+cadence or samples[-1]['timestamp_ns']<block_end-cadence or len(samples)==1):reason='sample coverage unavailable'
        if reason is None and any(b['timestamp_ns']-a['timestamp_ns']>2*cadence for a,b in zip(samples,samples[1:])):reason='sampling cadence gap'
        if reason is None and row['scope']=='gpu' and any(not s['process_attributed'] for s in samples):reason='GPU process attribution unavailable'
        if reason is None and row['kind']=='counter' and any(b['value']<a['value'] for a,b in zip(samples,samples[1:])):reason='counter reset in measured window'
        row['source_clock_domain']=row['clock_domain']
        row['clock_domain']='client_monotonic'
        row['window']={'start_ns':start+offset,'end_ns':end+offset}
        row['samples']=samples
        row['available']=reason is None
        row['unavailable_reason']=reason
        aligned.append(row)
    return {'clock_policy':'episode2.alignment.v1','maximum_clock_uncertainty_ns':MAX_CLOCK_UNCERTAINTY_NS,'available_signals':sorted({r['name'] for r in aligned if r['available']}),'signals':aligned,'limits':['Alignment qualifies observations; metric source/default mapping must be independently verified.','Clock uncertainty is retained; aligned correlation alone does not establish causation.']}
