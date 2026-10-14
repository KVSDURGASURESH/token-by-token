"""Strict model-response validation and canonical dependent Episode 02 sessions.

Tool fixtures supply local tool results only after an actual validated model call.
No fixture supplies a model response or rescues a divergent trajectory.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
import time
from typing import Any, Callable

from .episode2_contract import canonical_bytes, document_digest, loads_strict_json, validate_trace
from .episode2_corpus import CLASS_SPECS, build_continuation, initial_messages
from .streaming import StreamingError, stream_chat


@dataclass
class StreamReply:
    text: str
    tool_calls: list[dict]
    actual_send_ns: int
    first_content_ns: int | None
    last_content_ns: int | None
    terminal_ns: int
    input_tokens: int
    output_tokens: int
    stop_reason: str
    content_events: list[dict]
    tool_events: list[dict]

    def __post_init__(self) -> None:
        for name in ('actual_send_ns', 'terminal_ns', 'input_tokens', 'output_tokens'):
            value = getattr(self, name)
            if type(value) is not int or value < (1 if 'tokens' in name else 0):
                raise ValueError('exact nonnegative timing and positive token counts required')
        if self.terminal_ns < self.actual_send_ns:
            raise ValueError('terminal precedes send')
        if not isinstance(self.text, str) or len(self.text.encode('utf-8')) > 65536:
            raise ValueError('bounded response text required')
        if not isinstance(self.tool_calls, list) or len(self.tool_calls) > 1:
            raise ValueError('single model tool call required')
        if self.text:
            if any(type(value) is not int for value in (self.first_content_ns, self.last_content_ns)) or not self.actual_send_ns <= self.first_content_ns <= self.last_content_ns <= self.terminal_ns:
                raise ValueError('content timestamps required and ordered')
        elif self.first_content_ns is not None or self.last_content_ns is not None:
            raise ValueError('tool-only reply has no content timestamps')
        if self.stop_reason not in {'stop', 'length', 'tool_calls'}:
            raise ValueError('unsupported terminal stop reason')
        for events, fields in ((self.content_events, {'received_ns', 'text'}), (self.tool_events, {'received_ns', 'delta'})):
            if not isinstance(events, list) or len(events) > 65536:
                raise ValueError('bounded event list required')
            previous = self.actual_send_ns
            for event in events:
                if not isinstance(event, dict) or set(event) != fields or type(event['received_ns']) is not int or not previous <= event['received_ns'] <= self.terminal_ns:
                    raise ValueError('event timestamps required and ordered')
                previous = event['received_ns']
        canonical_bytes(self.tool_calls)

    @property
    def ttft_ms(self) -> float | None:
        return (self.first_content_ns - self.actual_send_ns) / 1e6 if self.first_content_ns is not None else None

    @property
    def tpot_ms(self) -> float | None:
        if self.first_content_ns is None or self.output_tokens < 2:
            return None
        return (self.last_content_ns - self.first_content_ns) / 1e6 / (self.output_tokens - 1)

    @property
    def e2e_ms(self) -> float:
        return (self.terminal_ns - self.actual_send_ns) / 1e6


def stream_turn(turn: dict, connection: dict, clock: Callable[[], int] = time.monotonic_ns) -> StreamReply:
    """Use only the operator-resolved bounded connection and actual transport usage."""
    if document_digest(turn['messages']) != turn['messages_sha256']:
        raise ValueError('rendered messages differ from frozen turn')
    request = dict(connection)
    request.update(messages=turn['messages'], maximum_output_tokens=turn['requested_output_tokens'], record_events=True, defer_missing_required_tool=True)
    for name in ('tools', 'tool_choice', 'response_format'):
        request.pop(name, None)
        if name in turn:
            request[name] = deepcopy(turn[name])
    value = stream_chat(request, clock=clock)
    if type(value['input_tokens']) is not int or value['input_tokens'] < 1:
        raise StreamingError('exact streamed input token usage is required')
    return StreamReply(**{name: value[name] for name in StreamReply.__dataclass_fields__})


def run_tool(name: str, arguments: dict, fixtures: dict) -> dict:
    fixture = fixtures.get(name)
    if not isinstance(fixture, dict) or not {'arguments', 'result'} <= set(fixture) or not set(fixture) <= {'arguments', 'result', 'schema'} or canonical_bytes(arguments) != canonical_bytes(fixture['arguments']):
        raise ValueError('tool call does not match fixture contract')
    if not isinstance(arguments, dict) or not isinstance(fixture['result'], dict):
        raise ValueError('tool arguments and result must be objects')
    canonical_bytes(fixture['result'])
    return deepcopy(fixture['result'])


def _exact(actual: Any, expected: dict) -> dict:
    if not isinstance(actual, dict) or canonical_bytes(actual) != canonical_bytes(expected):
        raise ValueError('model response violates closed semantic contract')
    return deepcopy(actual)


def validate_semantic(turn: dict, reply: StreamReply) -> dict:
    reply.__post_init__()
    class_id, turn_id = turn['class_id'], turn['turn_id']
    tool_turn = (class_id == 'tool_call' and turn_id == 'turn-1') or (class_id == 'agent_chain' and turn_id == 'turn-2')
    if reply.output_tokens > turn.get('requested_output_tokens', CLASS_SPECS[class_id][2]):
        raise ValueError('delivered output exceeds declared cap')
    if tool_turn:
        if reply.stop_reason != 'tool_calls' or len(reply.tool_calls) != 1 or reply.text.strip():
            raise ValueError('actual declared tool call required')
        call = reply.tool_calls[0]
        if not isinstance(call, dict) or set(call) != {'id', 'type', 'function'} or call['type'] != 'function' or not isinstance(call['id'], str) or not 1 <= len(call['id']) <= 256:
            raise ValueError('invalid tool identity')
        function = call['function']
        if not isinstance(function, dict) or set(function) != {'name', 'arguments'} or function['name'] != 'lookup_inventory' or not isinstance(function['arguments'], str):
            raise ValueError('invalid tool function')
        arguments = _exact(loads_strict_json(function['arguments']), {'sku': 'widget'})
        return {'name': function['name'], 'arguments': arguments}
    if reply.tool_calls or reply.stop_reason != 'stop':
        raise ValueError('complete natural-stop model content required')
    if class_id == 'short':
        text = reply.text.strip()
        if not 4 <= len(text.split()) <= 64 or '\n' in text or text[-1:] not in '.!?' or len(re.findall(r'[.!?](?:\s|$)', text)) != 1:
            raise ValueError('one nonempty explanatory sentence required')
        return {'text': text}
    if class_id == 'output_heavy':
        from .episode2_corpus import OUTPUT_CONCEPTS
        lines = reply.text.strip().splitlines()
        if len(lines) != len(OUTPUT_CONCEPTS) or not 256 <= reply.output_tokens <= 512:
            raise ValueError('ordered summary output length required')
        for index, (line, concept) in enumerate(zip(lines, OUTPUT_CONCEPTS), 1):
            prefix = f'{index}. {concept}: '
            if not line.startswith(prefix) or not 12 <= len(line[len(prefix):].split()) <= 18:
                raise ValueError('ordered concept and explanation contract required')
        return {'concepts': list(OUTPUT_CONCEPTS), 'output_tokens': reply.output_tokens}
    value = loads_strict_json(reply.text)
    if class_id == 'long_prefill':
        return _exact(value, {'row_003': 3, 'row_127': 127})
    if class_id == 'structured':
        return _exact(value, {'answer': 6, 'unit': 'items'})
    if class_id == 'code_reasoning':
        return _exact(value, {'value': 42, 'expression': '6*7'})
    if class_id == 'conversation':
        return _exact(value, {'selected': 'orange'} if turn_id == 'turn-1' else {'color': 'orange'})
    if class_id == 'tool_call':
        return _exact(value, {'answer': 6})
    if class_id == 'agent_chain':
        return _exact(value, {'sku': 'widget'} if turn_id == 'turn-1' else {'order': 4})
    raise ValueError('undefined workflow class')


class SessionDriver:
    """One pending turn per workflow; invalid predecessors permanently block descendants."""
    def __init__(self, trace: dict, workflow_id: str, fixtures: dict, *, block_id: str | None = None, protocol: dict | None = None, clock: Callable[[], int] = time.monotonic_ns):
        if protocol is not None:
            validate_trace(trace, protocol)
        if document_digest(fixtures) != trace['tool_fixtures_sha256']:
            raise ValueError('tool fixture digest mismatch')
        if document_digest(trace['blocks']) != trace['logical_sha256']:
            raise ValueError('logical trace digest mismatch')
        blocks = trace['blocks']
        selected = [block for block in blocks if block_id is None or block['block_id'] == block_id]
        if not selected:
            raise ValueError('block unavailable')
        block = selected[0]
        turns = [deepcopy(turn) for turn in block['turns'] if turn['workflow_id'] == workflow_id]
        if not turns or len({turn['logical_request_id'] for turn in turns}) != len(turns):
            raise ValueError('workflow unavailable or duplicate turns')
        previous = None
        for index, turn in enumerate(turns, 1):
            if turn['turn_id'] != f'turn-{index}' or turn['predecessor_id'] != previous or turn['class_id'] != turns[0]['class_id'] or turn['session_id'] != turns[0]['session_id']:
                raise ValueError('workflow predecessor order mismatch')
            previous = turn['logical_request_id']
        self.output_caps = {name: spec[2] for name, spec in CLASS_SPECS.items()} if protocol is None else {name: spec['requested_output_tokens'] for name, spec in protocol['mixture']['classes'].items()}
        self.block_id = block['block_id']
        self.turns = turns
        self.fixtures = deepcopy(fixtures)
        self.clock = clock
        self.index = 0
        self.pending: dict | None = None
        self.semantic: dict | None = None
        self.tool_result: dict | None = None
        self.tool_observations: list[dict] = []
        self.blocked_request_ids: list[str] = []
        self.failure: dict | None = None

    def next_turn(self) -> dict | None:
        if self.failure is not None or self.index == len(self.turns):
            return None
        if self.pending is not None:
            raise ValueError('predecessor reply is pending')
        turn = deepcopy(self.turns[self.index])
        messages = initial_messages(turn) if self.semantic is None else build_continuation(turn, self.semantic, self.tool_result)
        if document_digest(messages) != turn['messages_sha256']:
            self.on_failure('continuation_mismatch')
            raise ValueError('canonical continuation differs from frozen trace')
        turn.update(messages=messages, requested_output_tokens=self.output_caps[turn['class_id']], block_id=self.block_id)
        tool_turn = (turn['class_id'] == 'tool_call' and self.index == 0) or (turn['class_id'] == 'agent_chain' and self.index == 1)
        if tool_turn:
            name = turn['tool_fixture_ref']
            fixture = self.fixtures[name]
            turn['tools'] = [{'type': 'function', 'function': {'name': name, 'parameters': deepcopy(fixture['schema'])}}]
            turn['tool_choice'] = 'required'
        elif turn['class_id'] not in {'short', 'output_heavy'}:
            turn['response_format'] = {'type': 'json_object'}
        self.pending = deepcopy(turn)
        return turn

    def on_reply(self, reply: StreamReply) -> None:
        if self.pending is None or self.failure is not None:
            raise ValueError('no pending request')
        try:
            semantic = validate_semantic(self.pending, reply)
            tool_result = None
            if reply.tool_calls:
                start = self.clock()
                tool_result = run_tool(semantic['name'], semantic['arguments'], self.fixtures)
                end = self.clock()
                self.tool_observations.append({'logical_request_id': self.pending['logical_request_id'], 'name': semantic['name'], 'result': deepcopy(tool_result), 'started_ns': start, 'terminal_ns': end, 'duration_ns': end - start})
            self.semantic = semantic
            self.tool_result = tool_result
            self.pending = None
            self.index += 1
        except ValueError:
            self.on_failure('semantic_invalid')
            raise

    def on_failure(self, reason: str) -> None:
        if self.failure is not None:
            return
        if not isinstance(reason, str) or not 1 <= len(reason) <= 128 or not reason.replace('_', '').replace('-', '').isalnum():
            raise ValueError('bounded failure classification required')
        if self.index >= len(self.turns):
            raise ValueError('workflow already complete')
        self.failure = {'logical_request_id': self.turns[self.index]['logical_request_id'], 'reason': reason}
        self.blocked_request_ids = [turn['logical_request_id'] for turn in self.turns[self.index + 1:]]
        self.pending = None
