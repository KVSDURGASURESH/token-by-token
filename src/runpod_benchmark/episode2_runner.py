"""Bounded Episode 02 rehearsal scheduling with complete logical denominators.

The injected sender owns bounded transport cancellation/timeouts. Cancellation
stops new dispatch and drains already-started bounded sends; it never retries.
Recorded execution requires freshly recompiled authority and private lifecycle attestations.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
import time
from typing import Callable

from .episode2_contract import document_digest, require, validate_trace
from .episode2_corpus import TOOL_FIXTURES, trace_digest
from .episode2_schedule import SYNTHETIC_ARRIVAL_POLICY, compile_arrivals, compile_order, eligible_send_ns
from .episode2_sessions import SessionDriver, StreamReply


RUN_KEYS = {'protocol_sha256', 'trace_sha256', 'execution_id', 'engine', 'arm', 'cell_id',
            'evidence_class', 'physical_gpu_private_ref', 'blocks', 'observations',
            'workflow_observations', 'admissions', 'attempts', 'window', 'effective_config_sha256'}


CONTEXT_FIELDS = {'compiled_plan', 'plan_sha256', 'protocol_sha256', 'trace_sha256',
                  'material_sha256', 'execution_id', 'physical_gpu_private_ref',
                  'evidence_class', 'guard_nonce', 'guard_epoch_ns', 'guard_deadline_ns'}


def _compiler():
    from .episode2_preflight import _compiler as compiler
    return compiler()


def _ongoing_sources_verified(material):
    from .episode2_preflight import _files_verified, CODE_FILES, ROOT
    root = material['artifact_root']
    entries = [*material['provider_evidence'], *material['build_artifacts'],
               *material['model']['artifacts'], *material['tokenizer']['artifacts'],
               *material['tokenizer']['admission_artifacts'], *material['static_attestations'],
               material['compiler_review']]
    # The same file can support several proofs. Verify its bytes once, while
    # refusing different claims about one retained path.
    retained = {}
    for entry in entries:
        if entry['path'] in retained and retained[entry['path']] != entry:
            return False
        retained[entry['path']] = entry
    return (_files_verified(material['code_files'], str(ROOT), required_paths=CODE_FILES)
            and _files_verified(list(retained.values()), root))


def _execution_context(context, protocol, trace, execution_id, order, now, *, verified_snapshot=None):
    require(isinstance(context, dict) and set(context) == CONTEXT_FIELDS, 'closed compiled execution context required')
    plan = context['compiled_plan']
    require(plan.get('execution_ready') is True, 'compiled execution plan is not ready')
    if verified_snapshot is None:
        require(_compiler().plan_digest(plan) == context['plan_sha256'], 'current compiled plan changed')
    else:
        # Only run_campaign retains this snapshot after fresh initial validation.
        # Continuing one owned allocation grants no new creation authority.
        require(document_digest(context) == verified_snapshot, 'owned execution snapshot changed')
        require(_ongoing_sources_verified(plan['manifest']['episode2']['material']), 'current source or material changed')
    binding = plan['manifest']['episode2']
    require(binding['protocol'] == protocol and binding['trace'] == trace and binding['schedule'] == order,
            'compiled protocol, trace or schedule mismatch')
    for name, value in [('protocol', protocol), ('trace', trace), ('material', binding['material'])]:
        require(context[name + '_sha256'] == document_digest(value), 'compiled context digest mismatch')
    require(context['execution_id'] == execution_id, 'compiled execution identity mismatch')
    require(context['evidence_class'] in {'recorded', 'synthetic_mock'}, 'invalid execution evidence class')
    for name in ('physical_gpu_private_ref', 'guard_nonce'):
        require(isinstance(context[name], str) and 1 <= len(context[name]) <= 128, 'private execution binding missing')
    epoch, deadline = context['guard_epoch_ns'], context['guard_deadline_ns']
    require(type(epoch) is int and type(deadline) is int and 0 <= epoch <= now < deadline,
            'monotonic guard horizon elapsed')
    maximum = sum(binding['inputs']['phase_budgets'].values()) * 1_000_000_000
    require(0 < deadline - epoch <= maximum, 'guard horizon exceeds compiled bound')
    require(all(cell['mode'] == 'closed-loop' for cell in protocol['cells']), 'recorded arrivals require compiled numeric schedule')
    return binding


def _attestation(value, row, context, now, *, stopped=False):
    identities = {'plan_sha256', 'execution_id', 'engine', 'arm', 'cell_id', 'block_id', 'physical_gpu_private_ref'}
    expected = {key: (row[key] if key in row else context[key]) for key in identities}
    extra = {'runtime_ready', 'smoke_verified', 'defaults_verified', 'cache_reset_verified', 'epoch_id', 'guard'}
    fields = identities | {'status'} | (set() if stopped else extra)
    label = 'drain' if stopped else 'runtime'
    require(isinstance(value, dict) and set(value) == fields, f'closed {label} attestation required')
    require(all(value[key] == expected[key] for key in identities), f'{label} lifecycle identity mismatch')
    require(value['status'] == ('stopped' if stopped else 'verified'), f'{label} lifecycle unverified')
    if stopped:
        return
    require(all(value[key] is True for key in ('runtime_ready', 'smoke_verified', 'defaults_verified', 'cache_reset_verified')),
            'runtime readiness, smoke, defaults or cache reset unverified')
    require(isinstance(value['epoch_id'], str) and value['epoch_id'], 'runtime epoch required')
    guard = value['guard']
    require(isinstance(guard, dict) and set(guard) == {'nonce', 'observed_ns', 'deadline_ns', 'roles', 'caffeinate'}, 'closed guard attestation required')
    cleanup = context['compiled_plan']['manifest']['episode2']['cleanup']
    policy = cleanup['guard_policy'] if cleanup['mode'] == 'local_only_acknowledged' else cleanup['independent_watchdog']
    stale_ns = policy['heartbeat_stale_after_seconds'] * 1_000_000_000
    require(guard['nonce'] == context['guard_nonce'] and guard['deadline_ns'] == context['guard_deadline_ns'], 'guard nonce or monotonic deadline changed')
    require(type(guard['observed_ns']) is int and 0 <= now - guard['observed_ns'] <= stale_ns, 'fresh guard observation required')
    require(type(guard['caffeinate']) is bool and (cleanup['mode'] != 'local_only_acknowledged' or guard['caffeinate']), 'local guard caffeinate required')
    roles = guard['roles']
    require(isinstance(roles, list) and len(roles) == 2 and {r.get('role') for r in roles} == {'primary', 'secondary'}, 'two guard roles required')
    for role in roles:
        require(set(role) == {'role', 'pid', 'heartbeat_ns', 'nonce', 'source_sha256'}, 'closed guard role required')
        require(type(role['pid']) is int and role['pid'] > 0 and type(role['heartbeat_ns']) is int and 0 <= now-role['heartbeat_ns'] <= stale_ns,
                'fresh guard heartbeat required')
        require(role['nonce'] == context['guard_nonce'] and role['source_sha256'] == policy['watchdog_script_sha256'], 'guard source or nonce mismatch')
    require(roles[0]['pid'] != roles[1]['pid'], 'independent guard processes required')


def _cell_blocks(protocol: dict, trace: dict, *, engine: str, arm: str, cell_id: str,
             execution_id: str, send: Callable[[dict], StreamReply],
             clock: Callable[[], int] = time.monotonic_ns,
             stop: Callable[[], bool] = lambda: False, execution_context: dict | None = None) -> dict:
    validate_trace(trace, protocol)
    require((protocol['classification'] == 'synthetic_mock' and protocol['material']['execution_ready'] is False and execution_context is None)
            or (protocol['classification'] == 'recorded' and execution_context is not None),
            'recorded execution requires compiled material, cost and cleanup authority')
    require(engine in {'vllm', 'sglang'}, 'unsupported engine')
    for value in (arm, cell_id, execution_id):
        require(isinstance(value, str) and 1 <= len(value) <= 128, 'bounded execution identity required')
    cells = [cell for cell in protocol['cells'] if cell['cell_id'] == cell_id]
    require(len(cells) == 1 and cells[0]['mode'] == trace['mode'], 'trace/cell load mode mismatch')
    cell = cells[0]
    limit = cell['concurrency']
    result = {key: [] for key in ('blocks', 'observations', 'workflow_observations', 'admissions', 'attempts')}
    result.update(protocol_sha256=document_digest(protocol), trace_sha256=trace_digest(trace),
                  execution_id=execution_id, engine=engine, arm=arm, cell_id=cell_id,
                  evidence_class=execution_context['evidence_class'] if execution_context else 'synthetic_mock',
                  physical_gpu_private_ref=execution_context['physical_gpu_private_ref'] if execution_context else None,
                  effective_config_sha256=document_digest({'defaults_sha256': protocol['material'][f'{engine}_defaults_sha256'],
                      'common_launch_overrides': protocol['material']['common_launch_overrides'],
                      'harness_version': protocol['material']['harness_version']}))
    excluded = []
    max_requests = max_workflows = 0
    cancelled = False

    def now() -> int:
        value = clock()
        eligible_send_ns(value, None)
        return value

    def stopping() -> bool:
        nonlocal cancelled
        flag = stop()
        require(type(flag) is bool, 'stop callback must return boolean')
        cancelled = cancelled or flag
        return cancelled

    def perform(turn: dict) -> tuple:
        start = now()
        try:
            reply = send(deepcopy(turn))
            require(isinstance(reply, StreamReply), 'sender must return StreamReply')
            reply.__post_init__()
            return reply, None, start, now()
        except Exception as exc:
            # Never serialize exception messages: transport details may be private.
            return None, exc, start, now()

    with ThreadPoolExecutor(max_workers=limit, thread_name_prefix='episode2') as pool:
        for block in trace['blocks']:
            block_id = block['block_id']
            base = {'execution_id': execution_id, 'engine': engine, 'arm': arm, 'cell_id': cell_id, 'block_id': block_id}
            warmup_start = now()
            warmup_ok = True
            warmup_count = 0
            for index in range(protocol['warmup_reset']['warmup_requests']):
                if stopping():
                    break
                driver = SessionDriver(trace, block['workflows'][0]['workflow_id'], TOOL_FIXTURES,
                                       block_id=block_id, protocol=protocol, clock=clock)
                turn = driver.next_turn()
                turn.update(phase='warmup', scheduled_ns=now(), eligible_ns=now())
                reply, error, started, finished = perform(turn)
                if error is None:
                    try:
                        driver.on_reply(reply)
                    except ValueError:
                        error = ValueError()
                warmup_count += 1
                result['attempts'].append({**base, 'attempt_id': f'{execution_id}/{engine}/{arm}/{cell_id}/{block_id}/warmup-{index + 1}',
                    'logical_request_id': turn['logical_request_id'], 'phase': 'warmup',
                    'start_ns': started, 'end_ns': finished, 'status': 'success' if error is None else 'warmup_failed'})
                if error is not None:
                    require(execution_context is None, 'recorded warmup failed; abort campaign')
                    warmup_ok = False
                    break
            excluded.append({'block_id': block_id, 'phase': 'warmup', 'start_ns': warmup_start,
                             'end_ns': now(), 'attempted': warmup_count,
                             'status': 'cancelled' if cancelled else ('verified' if warmup_ok else 'failed')})
            start = now()
            if cell['mode'] == 'open-loop':
                arrivals = compile_arrivals(protocol, block, start_ns=start)
            else:
                arrivals = [{**deepcopy(workflow), 'phase': 'closed-loop', 'scheduled_ns': start,
                             'offset_ns': 0, 'interarrival_ns': 0} for workflow in block['workflows']]
            pending = {}
            active = {}
            arrival_index = 0
            scheduled_horizon_ns = max(100_000_000, arrivals[-1]['offset_ns'] + 100_000_000)
            block_record = {'block_id': block_id, 'class_counts': deepcopy(block['class_counts']),
                            'class_weights': deepcopy(block['class_weights']), 'start_ns': start,
                            'end_ns': None, 'arrivals': deepcopy(arrivals), 'scheduled_horizon_ns': scheduled_horizon_ns}
            result['blocks'].append(block_record)

            def observation(turn: dict, state: dict, status: str) -> dict:
                row = {**base, **{key: turn[key] for key in ('logical_request_id', 'workflow_id', 'session_id',
                       'turn_id', 'class_id', 'predecessor_id', 'messages_sha256')}}
                row.update(schema_version='episode2.observation.v1', campaign_id=protocol['campaign_id'], status=status, attempt_id=None, success=False, semantic_valid=False, work_equivalent=False,
                           schema_valid=False, tool_valid=False, quality_valid=False, text=None, tool_calls=[],
                           evidence_class=result['evidence_class'], protocol_sha256=result['protocol_sha256'],
                           trace_sha256=result['trace_sha256'], tool_fixtures_sha256=protocol['tool_fixtures_sha256'],
                           effective_config_sha256=result['effective_config_sha256'],
                           requested_output_tokens=protocol['mixture']['classes'][turn['class_id']]['requested_output_tokens'],
                           scheduled_ns=state['scheduled_ns'], eligible_ns=None, predecessor_valid_ns=None,
                           actual_send_ns=None, first_content_ns=None, last_content_ns=None, terminal_ns=None,
                           validation_terminal_ns=None, dependency_wait_ns=None, send_lag_ns=None,
                           eligible_send_lag_ns=None, ttft_ms=None, tpot_ms=None, e2e_ms=None,
                           input_tokens=None, output_tokens=None, stop_reason=None, content_events=[], tool_events=[],
                           tool_duration_ns=0)
                return row

            def finish_workflow(state: dict, status: str) -> None:
                terminal = now() if state['started_ns'] is not None else None
                result['workflow_observations'].append({**base, 'workflow_id': state['workflow_id'],
                    'session_id': state['session_id'], 'class_id': state['class_id'],
                    'scheduled_ns': state['scheduled_ns'], 'actual_start_ns': state['started_ns'],
                    'terminal_ns': terminal, 'status': status, 'success': status == 'success',
                    'workflow_e2e_ms': (terminal - state['scheduled_ns']) / 1e6 if terminal is not None else None})
                active.pop(state['workflow_id'], None)

            def unsent(state: dict, status: str, *, offset: int = 0) -> None:
                for turn in state['turns'][offset:]:
                    result['observations'].append(observation(turn, state, status))

            def dispatch(state: dict) -> None:
                nonlocal max_requests, max_workflows
                if stopping():
                    unsent(state, 'cancelled', offset=state['index'])
                    finish_workflow(state, 'cancelled')
                    return
                try:
                    turn = state['driver'].next_turn()
                except ValueError:
                    require(execution_context is None, 'recorded continuation mismatch; abort campaign')
                    unsent(state, 'continuation_mismatch', offset=state['index'])
                    finish_workflow(state, 'continuation_mismatch')
                    return
                require(turn is not None, 'session ended before scheduled turns')
                eligible = eligible_send_ns(state['scheduled_ns'], state['predecessor_valid_ns'])
                turn.update(phase='measured', scheduled_ns=state['scheduled_ns'], eligible_ns=eligible)
                future = pool.submit(perform, turn)
                pending[future] = (state, turn, eligible)
                max_requests = max(max_requests, len(pending))
                max_workflows = max(max_workflows, len(active))

            def admit(arrival: dict, forced_status: str | None = None) -> None:
                state = {**arrival, 'turns': [turn for turn in block['turns'] if turn['workflow_id'] == arrival['workflow_id']],
                         'index': 0, 'started_ns': None, 'predecessor_valid_ns': None}
                if cell['mode'] == 'closed-loop' and forced_status is None:
                    state['scheduled_ns'] = now()
                status = forced_status or ('dropped' if len(pending) >= limit else 'admitted')
                result['admissions'].append({**base, 'workflow_id': state['workflow_id'], 'session_id': state['session_id'],
                    'class_id': state['class_id'], 'scheduled_ns': state['scheduled_ns'], 'decision_ns': now(), 'status': status})
                if status != 'admitted':
                    unsent(state, 'admission_dropped' if status == 'dropped' else status)
                    finish_workflow(state, status)
                    return
                state['driver'] = SessionDriver(trace, state['workflow_id'], TOOL_FIXTURES,
                                               block_id=block_id, protocol=protocol, clock=clock)
                active[state['workflow_id']] = state
                dispatch(state)

            while arrival_index < len(arrivals) or pending:
                stopped = stopping()
                # Complete only finished bounded sends. No wait for an independent arrival.
                finished = [future for future in pending if future.done()]
                for future in finished:
                    state, turn, eligible = pending.pop(future)
                    reply, error, attempted_ns, finished_ns = future.result()
                    row = observation(turn, state, 'success')
                    attempt_id = f'{execution_id}/{engine}/{arm}/{cell_id}/{block_id}/{turn["logical_request_id"]}/attempt-1'
                    actual_send = reply.actual_send_ns if reply is not None else attempted_ns
                    if state['started_ns'] is None:
                        state['started_ns'] = actual_send
                    row.update(attempt_id=attempt_id, actual_send_ns=actual_send, eligible_ns=eligible,
                        predecessor_valid_ns=state['predecessor_valid_ns'], dependency_wait_ns=eligible-state['scheduled_ns'],
                        send_lag_ns=actual_send-state['scheduled_ns'], eligible_send_lag_ns=actual_send-eligible)
                    if reply is not None:
                        row.update(success=True, text=reply.text, tool_calls=deepcopy(reply.tool_calls),
                            first_content_ns=reply.first_content_ns, last_content_ns=reply.last_content_ns,
                            terminal_ns=reply.terminal_ns, input_tokens=reply.input_tokens, output_tokens=reply.output_tokens,
                            stop_reason=reply.stop_reason, content_events=deepcopy(reply.content_events),
                            tool_events=deepcopy(reply.tool_events), ttft_ms=reply.ttft_ms, tpot_ms=reply.tpot_ms,
                            e2e_ms=reply.e2e_ms)
                    else:
                        row['terminal_ns'] = finished_ns
                        for name in ('content_events', 'tool_events'):
                            events = getattr(error, name, ())
                            row[name] = deepcopy(list(events)) if isinstance(events, (list, tuple)) else []
                    if error is not None:
                        row['status'] = 'transport_error'
                        state['driver'].on_failure('transport_error')
                    elif actual_send < eligible or reply.terminal_ns > now():
                        row['success'] = False
                        row['status'] = 'timing_invalid'
                        state['driver'].on_failure('timing_invalid')
                    else:
                        try:
                            state['driver'].on_reply(reply)
                            row['semantic_valid'] = row['work_equivalent'] = True
                            row['schema_valid'] = row['tool_valid'] = row['quality_valid'] = True
                        except ValueError:
                            row['status'] = 'semantic_invalid'
                    row['validation_terminal_ns'] = now()
                    row['tool_duration_ns'] = sum(item['duration_ns'] for item in state['driver'].tool_observations
                                                   if item['logical_request_id'] == turn['logical_request_id'])
                    result['observations'].append(row)
                    result['attempts'].append({**base, 'attempt_id': attempt_id, 'logical_request_id': turn['logical_request_id'],
                        'phase': 'measured', 'start_ns': actual_send, 'end_ns': row['terminal_ns'], 'status': row['status']})
                    state['index'] += 1
                    state['predecessor_valid_ns'] = row['validation_terminal_ns']
                    if row['status'] != 'success':
                        unsent(state, 'dependency_blocked', offset=state['index'])
                        finish_workflow(state, row['status'])
                    elif state['index'] == len(state['turns']):
                        finish_workflow(state, 'success')
                    else:
                        dispatch(state)
                while arrival_index < len(arrivals):
                    arrival = arrivals[arrival_index]
                    forced = 'cancelled' if stopped else ('warmup_failed' if not warmup_ok else None)
                    if forced is None:
                        if cell['mode'] == 'closed-loop' and len(active) >= limit:
                            break
                        if cell['mode'] == 'open-loop' and now() < arrival['scheduled_ns']:
                            break
                    arrival_index += 1
                    admit(arrival, forced)
                if pending:
                    wait(tuple(pending), timeout=0.001, return_when=FIRST_COMPLETED)
                elif arrival_index < len(arrivals):
                    time.sleep(0.001)
            block_record['end_ns'] = now()
            yield block_record
    observations = result['observations']
    measured_duration = sum(row['end_ns'] - row['start_ns'] for row in result['blocks'])
    scheduled_duration = sum(row['scheduled_horizon_ns'] for row in result['blocks'])
    sent = [row for row in observations if row['attempt_id'] is not None]
    successes = [row for row in observations if row['status'] == 'success']
    offered_denominator = scheduled_duration if cell['mode'] == 'open-loop' else measured_duration
    def rate(count: int, duration: int) -> float | None:
        return count * 1e9 / duration if duration > 0 else None
    result['window'] = {'start_ns': result['blocks'][0]['start_ns'], 'end_ns': result['blocks'][-1]['end_ns'],
        'clock_domain': 'client_monotonic', 'mode': cell['mode'], 'temperature': cell['temperature'],
        'measured_duration_ns': measured_duration, 'scheduled_duration_ns': scheduled_duration,
        'excluded_windows': excluded, 'readiness_status': 'verified' if execution_context else 'unverified', 'cache_reset_status': 'verified' if execution_context else 'unverified',
        'offered_workflows_per_second': rate(len(result['workflow_observations']), offered_denominator),
        'offered_requests_per_second': rate(len(observations), offered_denominator),
        'achieved_requests_per_second': rate(len(successes), measured_duration),
        'scheduled_workflows': len(result['workflow_observations']), 'scheduled_requests': len(observations),
        'attempted_requests': len(sent), 'successful_requests': len(successes),
        'error_requests': len([row for row in sent if row['status'] != 'success']),
        'admitted_workflows': sum(row['status'] == 'admitted' for row in result['admissions']),
        'dropped_workflows': sum(row['status'] == 'dropped' for row in result['admissions']),
        'cancelled_requests': sum(row['status'] == 'cancelled' for row in observations),
        'dependency_blocked_requests': sum(row['status'] == 'dependency_blocked' for row in observations),
        'max_in_flight_requests': max_requests, 'max_active_workflows': max_workflows,
        'arrival_policy': deepcopy(SYNTHETIC_ARRIVAL_POLICY) if cell['mode'] == 'open-loop' else {'version': 'completion.v1'},
        'cancelled': cancelled}
    if execution_context:
        result['window']['runtime_version'] = execution_context['compiled_plan']['manifest']['episode2']['material']['images'][engine]['version']
    result['window']['arrival_policy_sha256'] = document_digest(result['window']['arrival_policy'])
    require(set(result) == RUN_KEYS, 'run result fields are closed')
    return result


def run_cell(protocol: dict, trace: dict, *, engine: str, arm: str, cell_id: str,
             execution_id: str, send: Callable[[dict], StreamReply],
             clock: Callable[[], int] = time.monotonic_ns,
             stop: Callable[[], bool] = lambda: False) -> dict:
    """Run all blocks for one arm/cell; campaigns should use run_campaign to pair order."""
    iterator = _cell_blocks(protocol, trace, engine=engine, arm=arm, cell_id=cell_id,
                            execution_id=execution_id, send=send, clock=clock, stop=stop)
    try:
        while True:
            next(iterator)
    except StopIteration as complete:
        return complete.value
    finally:
        iterator.close()


def run_campaign(protocol: dict, trace: dict, *, arm_ids: list[str], execution_id: str,
                 sender_factory: Callable[[str, str, str], Callable[[dict], StreamReply]],
                 clock: Callable[[], int] = time.monotonic_ns,
                 stop: Callable[[], bool] = lambda: False,
                 execution_context: dict | None = None,
                 before_block: Callable[[dict], dict] | None = None,
                 after_block: Callable[[dict], dict] | None = None) -> dict:
    """Execute paired blocks with a drain/start barrier on one physical allocation.

    The operator owns authorization, providers, bounded startup and teardown. This
    runner never creates resources or interprets paid approval text. Recorded
    run_cell is deliberately unavailable because it bypasses counterbalancing.
    """
    order = compile_order(protocol, arm_ids)
    context = deepcopy(execution_context)
    recorded = protocol['classification'] == 'recorded'
    if recorded:
        require(callable(before_block) and callable(after_block), 'recorded execution requires compiled lifecycle callbacks')
        _execution_context(context, protocol, trace, execution_id, order, clock())
        verified_snapshot = document_digest(context)
    else:
        require(context is None and before_block is None and after_block is None, 'synthetic rehearsal does not accept recorded authority')
    def stopping():
        return stop() or (recorded and clock() >= context['guard_epoch_ns'] + (context['guard_deadline_ns']-context['guard_epoch_ns'])*75//100)
    iterators, results, epochs = {}, [], set()
    try:
        for row in order:
            key = (row['engine'], row['arm'], row['cell_id'])
            if recorded:
                _execution_context(context, protocol, trace, execution_id, order, clock(), verified_snapshot=verified_snapshot)
                require(not stopping(), '75 percent traffic stop threshold reached')
            try:
                if recorded:
                    attestation = before_block(deepcopy(row))
                    _attestation(attestation, row, context, clock())
                    require(attestation['epoch_id'] not in epochs, 'runtime epoch was reused')
                    epochs.add(attestation['epoch_id'])
                if key not in iterators:
                    iterators[key] = _cell_blocks(protocol, trace, engine=key[0], arm=key[1], cell_id=key[2],
                        execution_id=execution_id, send=sender_factory(*key), clock=clock, stop=stopping,
                        execution_context=context)
                block = next(iterators[key])
                require(block['block_id'] == row['block_id'], 'compiled block order mismatch')
            finally:
                if recorded:
                    # Even a failed startup can have created a server process.
                    _attestation(after_block(deepcopy(row)), row, context, clock(), stopped=True)
            if recorded:
                require(clock() < context['guard_epoch_ns'] + (context['guard_deadline_ns']-context['guard_epoch_ns'])*85//100,
                        '85 percent export and teardown threshold reached')
        for iterator in iterators.values():
            try:
                next(iterator)
            except StopIteration as complete:
                results.append(complete.value)
            else:
                raise ValueError('uncompiled repetition block')
    finally:
        for iterator in iterators.values():
            iterator.close()
    return {'evidence_class': context['evidence_class'] if context else 'synthetic_mock', 'order': order, 'results': results}


def validate_replay_pair(left: dict, right: dict) -> None:
    """Reject incomparable trajectories while leaving both complete results intact."""
    for value in (left, right):
        require(isinstance(value, dict) and set(value) == RUN_KEYS, 'run result fields are closed')
    for name in ('protocol_sha256', 'trace_sha256', 'cell_id', 'evidence_class'):
        require(left[name] == right[name], f'replay {name} mismatch')
    for name in ('mode', 'temperature', 'arrival_policy_sha256'):
        require(left['window'][name] == right['window'][name], f'replay {name} mismatch')
    def indexed(result: dict) -> dict:
        rows = {}
        for row in result['observations']:
            key = (row['block_id'], row['logical_request_id'])
            require(key not in rows, 'duplicate replay identity')
            require(row['status'] == 'success' and row['semantic_valid'] is True and row['work_equivalent'] is True,
                    'non-equivalent replay trajectories retained')
            rows[key] = row
        require(len(rows) == result['window']['scheduled_requests'] and rows, 'replay observations incomplete')
        return rows
    left_rows, right_rows = indexed(left), indexed(right)
    require(set(left_rows) == set(right_rows), 'replay scheduled identities mismatch')
    fields = ('workflow_id', 'session_id', 'turn_id', 'class_id', 'predecessor_id', 'messages_sha256',
              'requested_output_tokens', 'input_tokens', 'output_tokens', 'stop_reason')
    for key, row in left_rows.items():
        require(all(row[name] == right_rows[key][name] for name in fields), 'non-equivalent requested or delivered work')
