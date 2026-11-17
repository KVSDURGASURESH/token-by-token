"""Episode 02 logical accounting and independently checked work qualification."""
from __future__ import annotations

import math
from typing import Any

from .episode2_contract import canonical_bytes, document_digest, require, validate_trace
from .episode2_corpus import trace_digest
from .episode2_runner import RUN_KEYS
from .episode2_sessions import StreamReply, validate_semantic

UNSENT = {'dependency_blocked', 'admission_dropped', 'cancelled', 'warmup_failed', 'continuation_mismatch'}
SENT = {'success', 'semantic_invalid', 'transport_error', 'timing_invalid'}
FLAGS = ('success', 'semantic_valid', 'work_equivalent', 'schema_valid', 'tool_valid', 'quality_valid')
TIMES = ('scheduled_ns', 'eligible_ns', 'predecessor_valid_ns', 'actual_send_ns', 'first_content_ns', 'last_content_ns', 'terminal_ns', 'validation_terminal_ns', 'dependency_wait_ns', 'send_lag_ns', 'eligible_send_lag_ns', 'tool_duration_ns')
OBS_FIELDS = {'schema_version', 'campaign_id', 'execution_id', 'engine', 'arm', 'cell_id', 'block_id', 'logical_request_id', 'workflow_id', 'session_id', 'turn_id', 'class_id', 'predecessor_id', 'messages_sha256', 'status', 'attempt_id', 'text', 'tool_calls', 'evidence_class', 'protocol_sha256', 'trace_sha256', 'tool_fixtures_sha256', 'effective_config_sha256', 'requested_output_tokens', 'ttft_ms', 'tpot_ms', 'e2e_ms', 'input_tokens', 'output_tokens', 'stop_reason', 'content_events', 'tool_events'} | set(TIMES) | set(FLAGS)


def finite_nonnegative(value: Any, label: str) -> float:
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0, f'invalid {label}')
    return float(value)


def applicable_tpot(content_span_ms: float, output_tokens: int) -> float | None:
    span = finite_nonnegative(content_span_ms, 'content span')
    require(type(output_tokens) is int and output_tokens >= 0, 'invalid exact output count')
    return span / (output_tokens - 1) if output_tokens >= 2 else None


def qualify_turn(observation: dict, protocol: dict) -> dict:
    """Qualify a row; full identity/protocol validation belongs at result entry."""
    success = observation.get('success')
    require(type(success) is bool, 'success must be boolean')
    for name in ('ttft_ms', 'e2e_ms', 'content_span_ms'):
        if observation.get(name) is not None:
            finite_nonnegative(observation[name], name)
    tokens = observation.get('output_tokens')
    if tokens is not None:
        require(type(tokens) is int and tokens >= 0, 'invalid exact output count')
    qualified = success and all(observation.get(name) is True for name in ('quality_valid', 'schema_valid', 'tool_valid', 'work_equivalent'))
    minimum = protocol.get('quality', {}).get('minimum_output_tokens', 1)
    require(type(minimum) is int and minimum >= 1, 'invalid minimum output count')
    qualified = qualified and type(tokens) is int and tokens >= minimum and observation.get('e2e_ms') is not None
    content = observation.get('ttft_ms') is not None
    tool_latency=None
    if qualified and observation.get('tool_events'):
        first=observation['tool_events'][0].get('received_ns')
        sent=observation.get('actual_send_ns')
        require(type(first) is int and type(sent) is int and 0<=sent<=first, 'invalid tool event timing')
        tool_latency=(first-sent)/1e6
    tpot = applicable_tpot(observation['content_span_ms'], tokens) if qualified and content and observation.get('content_span_ms') is not None else None
    return {'terminal_success': success, 'qualified': qualified,
            'ttft_ms': observation.get('ttft_ms') if qualified and content else None,
            'e2e_ms': observation.get('e2e_ms') if qualified else None,
            'tpot_ms': tpot, 'tool_event_latency_ms':tool_latency, 'content_applicable': qualified and content,
            'output_tokens': tokens if qualified else None}


def _equal_number(actual: Any, expected: float, label: str) -> None:
    value = finite_nonnegative(actual, label)
    require(math.isclose(value, expected, rel_tol=1e-9, abs_tol=1e-9), f'{label} does not match event boundaries')


def _reply(row: dict) -> StreamReply:
    return StreamReply(**{name: row[name] for name in StreamReply.__dataclass_fields__})


def _inside_block(value: Any, block: dict, label: str, *, offered_future: bool = False) -> None:
    if value is None:
        return
    upper=block['start_ns']+block['scheduled_horizon_ns'] if offered_future else block['end_ns']
    require(type(value) is int and block['start_ns']<=value<=upper, f'{label} outside measured block/window')


def _scope(row: dict, result: dict) -> None:
    for name in ('execution_id', 'engine', 'arm', 'cell_id'):
        require(row.get(name) == result[name], f'denominator {name} mismatch')


def _tool_event_match(reply: StreamReply) -> None:
    if not reply.tool_calls:
        require(not reply.tool_events, 'tool events without model call')
        return
    assembled = {'id':'', 'type':'function', 'function':{'name':'', 'arguments':''}}
    for event in reply.tool_events:
        delta = event['delta']
        require(isinstance(delta,dict) and type(delta.get('index')) is int and delta['index']==0 and set(delta)<={'index','id','type','function'}, 'invalid tool event fragment')
        require(delta.get('type','function')=='function', 'invalid tool event type')
        if delta.get('id') is not None:
            require(isinstance(delta['id'],str) and not assembled['id'], 'duplicate tool event identity')
            assembled['id']=delta['id']
        function=delta.get('function',{})
        require(isinstance(function,dict) and set(function)<={'name','arguments'}, 'invalid tool function event')
        for name in ('name','arguments'):
            value=function.get(name,'')
            if name=='name' and value is None:
                continue
            require(isinstance(value,str), 'invalid tool event text')
            assembled['function'][name]+=value
    require(canonical_bytes([assembled])==canonical_bytes(reply.tool_calls), 'tool call/event mismatch')


def validate_observations(result: dict, protocol: dict, trace: dict) -> None:
    validate_trace(trace, protocol)
    require(isinstance(result, dict) and set(result) == RUN_KEYS, 'run result fields are closed')
    canonical_bytes(result)
    require(result['protocol_sha256'] == document_digest(protocol) and result['trace_sha256'] == trace_digest(trace), 'result contract digest mismatch')
    require(result['evidence_class'] == protocol['classification'], 'evidence classification mismatch')
    cell = next((item for item in protocol['cells'] if item['cell_id'] == result['cell_id']), None)
    require(cell is not None and cell['mode'] == trace['mode'], 'result cell mismatch')
    require(result['engine'] in {'vllm', 'sglang'}, 'unsupported engine')
    window = result['window']
    require(isinstance(window, dict) and window['clock_domain'] == 'client_monotonic' and window['mode'] == cell['mode'] and window['temperature'] == cell['temperature'], 'window domain/cell mismatch')
    expected = {(block['block_id'], turn['logical_request_id']): turn for block in trace['blocks'] for turn in block['turns']}
    blocks = {block['block_id']: block for block in result['blocks']}
    require(len(blocks) == len(result['blocks']) == protocol['repetition_blocks'] and set(blocks) == {block['block_id'] for block in trace['blocks']}, 'block identity mismatch')
    for block in result['blocks']:
        for name in ('start_ns', 'end_ns'):
            require(type(block[name]) is int and block[name] >= 0, 'invalid block timestamp')
        require(block['end_ns'] >= block['start_ns'], 'block ends before start')
        require(type(block['scheduled_horizon_ns']) is int and block['scheduled_horizon_ns']>0, 'invalid offered block horizon')
        require(block['class_counts'] == {name: protocol['mixture']['units_per_class'] for name in protocol['mixture']['classes']} and block['class_weights'] == protocol['mixture']['weights'], 'block mixture mismatch')
    require(all(previous['end_ns']<=following['start_ns'] for previous,following in zip(result['blocks'],result['blocks'][1:])), 'measured block windows overlap or are reordered')
    seen = {}
    for row in result['observations']:
        require(isinstance(row, dict) and set(row) == OBS_FIELDS, 'observation fields are closed')
        require(row['schema_version'] == 'episode2.observation.v1' and row['campaign_id'] == protocol['campaign_id'], 'observation campaign/version mismatch')
        key = (row['block_id'], row['logical_request_id'])
        require(key in expected and key not in seen, 'missing, wrong or duplicate logical identity')
        seen[key] = row
        turn = expected[key]
        for name in ('workflow_id', 'session_id', 'turn_id', 'class_id', 'predecessor_id', 'messages_sha256'):
            require(row[name] == turn[name], f'observation {name} mismatch')
        for name in ('execution_id', 'engine', 'arm', 'cell_id', 'evidence_class', 'protocol_sha256', 'trace_sha256', 'effective_config_sha256'):
            require(row[name] == result[name], f'observation {name} mismatch')
        require(row['tool_fixtures_sha256'] == protocol['tool_fixtures_sha256'], 'tool fixture binding mismatch')
        require(row['requested_output_tokens'] == protocol['mixture']['classes'][row['class_id']]['requested_output_tokens'], 'requested work mismatch')
        require(row['status'] in UNSENT | SENT and all(type(row[name]) is bool for name in FLAGS), 'invalid status or validity flags')
        for name in TIMES:
            value = row[name]
            require(value is None or (type(value) is int and value >= 0), f'invalid {name}')
        require(row['scheduled_ns'] is not None, 'scheduled identity lacks schedule')
        block=blocks[row['block_id']]
        for name in ('scheduled_ns','eligible_ns','predecessor_valid_ns','actual_send_ns','first_content_ns','last_content_ns','terminal_ns','validation_terminal_ns'):
            _inside_block(row[name],block,name,offered_future=name=='scheduled_ns' and row['status'] in {'cancelled','warmup_failed'})
        for event in row['content_events']+row['tool_events']:
            require(isinstance(event,dict) and type(event.get('received_ns')) is int, 'event timestamp missing')
            _inside_block(event['received_ns'],block,'stream event')
        require(row['tool_duration_ns']<=block['end_ns']-block['start_ns'], 'tool duration exceeds measured block/window')
        if row['success'] and row['terminal_ns'] is not None and row['validation_terminal_ns'] is not None:
            require(row['tool_duration_ns']<=row['validation_terminal_ns']-row['terminal_ns'], 'tool duration exceeds workflow validation interval')
        for name in ('ttft_ms', 'tpot_ms', 'e2e_ms'):
            if row[name] is not None:
                finite_nonnegative(row[name], name)
        if row['status'] in UNSENT:
            require(row['attempt_id'] is None and row['actual_send_ns'] is None and row['terminal_ns'] is None and row['input_tokens'] is None and row['output_tokens'] is None and row['text'] is None and not row['content_events'] and not row['tool_events'] and not row['tool_calls'] and not any(row[name] for name in FLAGS), 'unsent row carries measured evidence')
            continue
        require(isinstance(row['attempt_id'], str) and row['attempt_id'] and row['actual_send_ns'] is not None and row['terminal_ns'] is not None and row['validation_terminal_ns'] is not None, 'sent identity/timing unavailable')
        if row['success']:
            reply = _reply(row)
            _tool_event_match(reply)
            require(row['eligible_ns'] is not None and row['actual_send_ns'] >= row['eligible_ns'] >= row['scheduled_ns'] and row['validation_terminal_ns'] >= row['terminal_ns'], 'successful timestamp order mismatch')
            _equal_number(row['e2e_ms'], reply.e2e_ms, 'E2E')
            if reply.first_content_ns is not None:
                _equal_number(row['ttft_ms'], reply.ttft_ms, 'TTFT')
                require(bool(reply.content_events) and reply.content_events[0]['received_ns'] == reply.first_content_ns and reply.content_events[-1]['received_ns'] == reply.last_content_ns, 'content boundary/event mismatch')
                require(''.join(item['text'] for item in reply.content_events) == reply.text, 'content text/event mismatch')
                if reply.tpot_ms is not None:
                    _equal_number(row['tpot_ms'], reply.tpot_ms, 'TPOT')
                else:
                    require(row['tpot_ms'] is None, 'one-token TPOT is unavailable')
            else:
                require(row['ttft_ms'] is None and row['tpot_ms'] is None and not reply.content_events and bool(reply.tool_calls) and bool(reply.tool_events), 'tool-only content timing fabricated')
            spec = protocol['mixture']['classes'][row['class_id']]
            require(spec['input_tokens_min'] <= reply.input_tokens <= spec['input_tokens_max'] and reply.input_tokens + reply.output_tokens <= protocol['material']['context_window'], 'exact tokenizer context band mismatch')
            semantic_ok = True
            try:
                validate_semantic({**turn, 'requested_output_tokens': spec['requested_output_tokens']}, reply)
            except ValueError:
                semantic_ok = False
            require(semantic_ok == row['semantic_valid'], 'semantic validity claim mismatch')
            if row['status'] == 'success':
                require(semantic_ok and all(row[name] for name in FLAGS), 'successful row lacks quality/work validity')
            else:
                require(not row['quality_valid'] and not row['work_equivalent'], 'failed quality row claims equivalent work')
            for name, expected_duration in (('dependency_wait_ns', row['eligible_ns'] - row['scheduled_ns']), ('send_lag_ns', row['actual_send_ns'] - row['scheduled_ns']), ('eligible_send_lag_ns', row['actual_send_ns'] - row['eligible_ns'])):
                require(row[name] == expected_duration, f'{name} boundary mismatch')
    require(set(seen) == set(expected), 'scheduled observations incomplete')
    attempts = {}
    for attempt in result['attempts']:
        require(isinstance(attempt, dict) and isinstance(attempt['attempt_id'], str) and attempt['attempt_id'] not in attempts, 'duplicate attempt identity')
        _scope(attempt,result)
        require(set(attempt)=={'execution_id','engine','arm','cell_id','block_id','attempt_id','logical_request_id','phase','start_ns','end_ns','status'}, 'attempt fields are closed')
        require((attempt['block_id'],attempt['logical_request_id']) in expected, 'attempt logical identity mismatch')
        require(type(attempt['start_ns']) is int and type(attempt['end_ns']) is int and 0<=attempt['start_ns']<=attempt['end_ns'], 'invalid attempt boundaries')
        attempts[attempt['attempt_id']] = attempt
        require(attempt['phase'] in {'warmup', 'measured'}, 'invalid attempt phase')
        if attempt['phase']=='measured':
            _inside_block(attempt['start_ns'],blocks[attempt['block_id']],'measured attempt start')
            _inside_block(attempt['end_ns'],blocks[attempt['block_id']],'measured attempt terminal')
    exclusions={item['block_id']:item for item in window['excluded_windows']}
    require(len(exclusions)==len(window['excluded_windows']) and set(exclusions)==set(blocks), 'warmup exclusion windows incomplete')
    for block_id,exclusion in exclusions.items():
        warmups=[item for item in attempts.values() if item['phase']=='warmup' and item['block_id']==block_id]
        require(exclusion['phase']=='warmup' and exclusion['attempted']==len(warmups) and len(warmups)<=protocol['warmup_reset']['warmup_requests'], 'warmup attempt/exclusion mismatch')
        require(type(exclusion['start_ns']) is int and type(exclusion['end_ns']) is int and 0<=exclusion['start_ns']<=exclusion['end_ns']<=blocks[block_id]['start_ns'], 'warmup window boundary mismatch')
        require(all(exclusion['start_ns']<=item['start_ns']<=item['end_ns']<=exclusion['end_ns'] for item in warmups), 'warmup attempts outside excluded window')
        if exclusion['status']=='verified':
            require(len(warmups)==protocol['warmup_reset']['warmup_requests'] and all(item['status']=='success' for item in warmups), 'verified warmup evidence incomplete')
    sent = [row for row in seen.values() if row['attempt_id'] is not None]
    measured = {key: value for key, value in attempts.items() if value['phase'] == 'measured'}
    require({row['attempt_id'] for row in sent} == set(measured) and len(sent) == len(measured), 'measured attempt/logical identity mismatch')
    for row in sent:
        attempt = measured[row['attempt_id']]
        require(attempt['logical_request_id'] == row['logical_request_id'] and attempt['block_id'] == row['block_id'] and attempt['start_ns'] == row['actual_send_ns'] and attempt['end_ns'] == row['terminal_ns'] and attempt['status'] == row['status'], 'attempt evidence mismatch')
        if row['predecessor_id'] is not None:
            parent = seen[(row['block_id'], row['predecessor_id'])]
            require(parent['status'] == 'success' and row['predecessor_valid_ns'] == parent['validation_terminal_ns'] and row['eligible_ns'] >= parent['validation_terminal_ns'], 'sent descendant lacks validated predecessor')
    expected_workflows = {(block['block_id'], workflow['workflow_id']): workflow for block in trace['blocks'] for workflow in block['workflows']}
    workflows = {}
    members_by_workflow = {}
    for row in seen.values():
        members_by_workflow.setdefault((row['block_id'],row['workflow_id']),[]).append(row)
    for row in result['workflow_observations']:
        _scope(row,result)
        require(set(row)=={'execution_id','engine','arm','cell_id','block_id','workflow_id','session_id','class_id','scheduled_ns','actual_start_ns','terminal_ns','status','success','workflow_e2e_ms'}, 'workflow fields are closed')
        key = (row['block_id'], row['workflow_id'])
        require(key in expected_workflows and key not in workflows, 'duplicate or unexpected workflow identity')
        workflows[key] = row
        members = members_by_workflow[key]
        require(row['class_id'] == expected_workflows[key]['class_id'] and row['session_id'] == expected_workflows[key]['session_id'], 'workflow identity mismatch')
        require(type(row['scheduled_ns']) is int and row['scheduled_ns']>=0 and all(item['scheduled_ns']==row['scheduled_ns'] for item in members), 'workflow schedule mismatch')
        block=blocks[row['block_id']]
        _inside_block(row['scheduled_ns'],block,'workflow schedule',offered_future=row['actual_start_ns'] is None and row['status'] in {'cancelled','warmup_failed'})
        _inside_block(row['actual_start_ns'],block,'workflow actual start')
        _inside_block(row['terminal_ns'],block,'workflow terminal')
        require((row['actual_start_ns'] is None)==(row['terminal_ns'] is None), 'workflow actual boundary availability mismatch')
        if row['actual_start_ns'] is not None:
            require(row['actual_start_ns']<=row['terminal_ns'], 'workflow terminal precedes actual start')
        require(row['success'] is all(item['status'] == 'success' for item in members), 'workflow success denominator mismatch')
        if row['terminal_ns'] is not None:
            require(type(row['terminal_ns']) is int and row['terminal_ns'] >= row['scheduled_ns'], 'invalid workflow boundary')
            if row['success']:
                require(row['terminal_ns']>=max(item['validation_terminal_ns'] for item in members), 'workflow ends before validated descendants')
            _equal_number(row['workflow_e2e_ms'], (row['terminal_ns'] - row['scheduled_ns']) / 1e6, 'workflow E2E')
        else:
            require(row['workflow_e2e_ms'] is None and not row['success'], 'unsent workflow duration fabricated')
    require(set(workflows) == set(expected_workflows), 'scheduled workflows incomplete')
    for row in result['admissions']:
        _scope(row,result)
        require(set(row)=={'execution_id','engine','arm','cell_id','block_id','workflow_id','session_id','class_id','scheduled_ns','decision_ns','status'}, 'admission fields are closed')
        key=(row['block_id'],row['workflow_id'])
        require(key in expected_workflows and row['class_id']==expected_workflows[key]['class_id'] and row['session_id']==expected_workflows[key]['session_id'], 'admission identity mismatch')
        block=blocks[row['block_id']]
        _inside_block(row['decision_ns'],block,'admission decision')
        _inside_block(row['scheduled_ns'],block,'admission schedule',offered_future=row['status'] in {'cancelled','warmup_failed'})
        require(row['scheduled_ns']==workflows[key]['scheduled_ns'], 'admission/workflow schedule mismatch')
        if row['status'] in {'admitted','dropped'}:
            require(row['decision_ns']>=row['scheduled_ns'], 'admission decision precedes offered arrival')
        require(row['status'] in {'admitted','dropped','cancelled','warmup_failed'} and type(row['scheduled_ns']) is int and row['scheduled_ns']>=0 and type(row['decision_ns']) is int and row['decision_ns']>=0, 'invalid admission status/timing')
    admissions = {(row['block_id'], row['workflow_id']): row for row in result['admissions']}
    require(len(admissions) == len(result['admissions']) and set(admissions) == set(expected_workflows), 'admission denominator mismatch')
    totals = {'scheduled_requests': len(seen), 'scheduled_workflows': len(workflows), 'attempted_requests': len(sent), 'successful_requests': sum(row['status'] == 'success' for row in seen.values()), 'error_requests': sum(row['status'] != 'success' for row in sent), 'cancelled_requests': sum(row['status'] == 'cancelled' for row in seen.values()), 'dependency_blocked_requests': sum(row['status'] == 'dependency_blocked' for row in seen.values())}
    for name, count in totals.items():
        require(type(window.get(name)) is int and window[name] == count, f'window {name} denominator mismatch')
    require(window['admitted_workflows']==sum(row['status']=='admitted' for row in admissions.values()) and window['dropped_workflows']==sum(row['status']=='dropped' for row in admissions.values()), 'admission window denominator mismatch')
    require(window['start_ns']==result['blocks'][0]['start_ns'] and window['end_ns']==result['blocks'][-1]['end_ns'], 'measurement window boundary mismatch')
    require(type(window['measured_duration_ns']) is int and window['measured_duration_ns']>=0, 'invalid measured block duration sum')
    require(window['measured_duration_ns'] == sum(block['end_ns'] - block['start_ns'] for block in result['blocks']), 'measured duration mismatch')


def matched_work(left: dict, right: dict, protocol: dict | None = None) -> dict:
    """Return sanitized matching disposition; private GPU lineage never leaves this gate."""
    reasons, missing = [], []
    for name in ('protocol_sha256', 'trace_sha256', 'cell_id', 'evidence_class'):
        if left.get(name) != right.get(name): reasons.append(f'{name} differs')
    for name in ('mode', 'temperature', 'arrival_policy_sha256'):
        if left.get('window', {}).get(name) != right.get('window', {}).get(name): reasons.append(f'{name} differs')
    lineage = [value.get('physical_gpu_private_ref') for value in (left, right)]
    if any(not isinstance(value,str) or not value for value in lineage): missing.append('physical GPU lineage unavailable')
    elif lineage[0] != lineage[1]: reasons.append('physical allocation differs')
    if left.get('engine') == right.get('engine') and left.get('effective_config_sha256') != right.get('effective_config_sha256'):
        missing.append('changed effective configuration lacks verified treatment binding')
    tolerance = protocol.get('quality', {}).get('output_length_tolerance_fraction') if protocol else None
    if tolerance is None: missing.append('delivered-output tolerance is not frozen')
    else: require(type(tolerance) in (int, float) and math.isfinite(tolerance) and 0 <= tolerance <= 1, 'invalid output tolerance')
    rows = [{(row['block_id'], row['logical_request_id']): row for row in value['observations']} for value in (left, right)]
    if set(rows[0]) != set(rows[1]): reasons.append('scheduled identities differ')
    else:
        for key, row in rows[0].items():
            other = rows[1][key]
            if any(row[name] != other[name] for name in ('workflow_id', 'session_id', 'turn_id', 'class_id', 'predecessor_id', 'messages_sha256', 'requested_output_tokens', 'input_tokens', 'stop_reason')):
                reasons.append('requested or semantic trajectory differs'); break
            if row['work_equivalent'] is not True or other['work_equivalent'] is not True:
                missing.append('one or more trajectories are unqualified'); break
            if tolerance is not None and abs(row['output_tokens'] - other['output_tokens']) > row['output_tokens'] * tolerance:
                reasons.append('delivered output exceeds frozen tolerance'); break
    status = 'incompatible' if reasons else 'inconclusive' if missing else 'equivalent'
    return {'status': status, 'equivalent': status == 'equivalent', 'reasons': sorted(set(reasons + missing))}
