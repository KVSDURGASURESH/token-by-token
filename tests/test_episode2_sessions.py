from copy import deepcopy

import pytest

from runpod_benchmark.episode2_corpus import TOOL_FIXTURES, build_trace, make_synthetic_protocol


def driver(class_id):
    from runpod_benchmark.episode2_sessions import SessionDriver
    return SessionDriver(build_trace(make_synthetic_protocol()), f'wf-{class_id}-001', TOOL_FIXTURES)


def reply(text='', calls=None, stop='stop'):
    from runpod_benchmark.episode2_sessions import StreamReply
    return StreamReply(text=text, tool_calls=calls or [], actual_send_ns=10, first_content_ns=11 if text else None, last_content_ns=12 if text else None, terminal_ns=15, input_tokens=20, output_tokens=8, stop_reason=stop, content_events=[{'text':text,'received_ns':11}] if text else [], tool_events=[])


def tool_reply(arguments='{"sku":"widget"}'):
    return reply(calls=[{'id':'real_call','type':'function','function':{'name':'lookup_inventory','arguments':arguments}}], stop='tool_calls')


def test_fixture_executes_only_exact_valid_arguments_and_returns_copy():
    from runpod_benchmark.episode2_sessions import run_tool
    value = run_tool('lookup_inventory', {'sku':'widget'}, TOOL_FIXTURES)
    assert value == {'stock':6}
    value['stock'] = 99
    assert TOOL_FIXTURES['lookup_inventory']['result'] == {'stock':6}
    with pytest.raises(ValueError): run_tool('lookup_inventory', {'sku':'other'}, TOOL_FIXTURES)
    with pytest.raises(ValueError): run_tool('lookup_inventory', {'sku':'widget','extra':True}, TOOL_FIXTURES)


def test_pending_predecessor_cannot_release_successor():
    session = driver('conversation')
    first = session.next_turn()
    assert first['turn_id'] == 'turn-1' and first['messages']
    with pytest.raises(ValueError, match='pending'): session.next_turn()
    session.on_reply(reply('{"selected":"orange"}'))
    second = session.next_turn()
    assert second['predecessor_id'] == first['logical_request_id']
    assert 'orange' in second['messages'][0]['content']
    session.on_reply(reply('{"color":"orange"}'))
    assert session.next_turn() is None


@pytest.mark.parametrize('text', ['{bad', '{"selected":"blue"}', '{"selected":"orange","selected":"orange"}', '{"selected":"orange","extra":1}'])
def test_invalid_predecessor_halts_descendants_without_substitution(text):
    session = driver('conversation')
    session.next_turn()
    with pytest.raises(ValueError): session.on_reply(reply(text))
    assert session.next_turn() is None
    assert session.blocked_request_ids == ['req-conversation-001-t2']
    assert session.failure is not None


def test_reordered_semantic_json_yields_identical_successor_work():
    left, right = driver('agent_chain'), driver('agent_chain')
    left.next_turn(); right.next_turn()
    left.on_reply(reply('{ "sku" : "widget" }'))
    right.on_reply(reply('{"sku":"widget"}'))
    a, b = left.next_turn(), right.next_turn()
    assert a['messages_sha256'] == b['messages_sha256']
    assert a['messages'] == b['messages'] and a['tools']


def test_tool_result_is_actual_validated_call_then_canonical_successor():
    session = driver('tool_call')
    first = session.next_turn()
    assert first['tools']
    session.on_reply(tool_reply())
    second = session.next_turn()
    assert '"stock":6' in second['messages'][0]['content']
    assert session.tool_observations[0]['result'] == {'stock':6}
    assert session.tool_observations[0]['duration_ns'] >= 0
    session.on_reply(reply('{"answer":6}'))
    assert session.next_turn() is None


def test_tool_fixture_cannot_replace_missing_model_call():
    session = driver('tool_call')
    session.next_turn()
    with pytest.raises(ValueError): session.on_reply(reply('{"answer":6}'))
    assert session.tool_observations == [] and session.next_turn() is None


@pytest.mark.parametrize('arguments', ['{', '{"sku":"other"}', '{"sku":"widget","sku":"widget"}'])
def test_invalid_tool_predecessor_never_runs_fixture(arguments):
    session = driver('tool_call'); session.next_turn()
    with pytest.raises(ValueError): session.on_reply(tool_reply(arguments))
    assert session.tool_observations == []
    assert session.blocked_request_ids == ['req-tool_call-001-t2']


def test_agent_chain_requires_derived_final_answer():
    session = driver('agent_chain'); session.next_turn()
    session.on_reply(reply('{"sku":"widget"}')); session.next_turn()
    session.on_reply(tool_reply()); session.next_turn()
    with pytest.raises(ValueError): session.on_reply(reply('{"order":5}'))


@pytest.mark.parametrize('class_id,text', [('short','Equal work preserves inputs and requested outputs.'), ('structured','{"answer":6,"unit":"items"}'), ('code_reasoning','{"value":42,"expression":"6*7"}'), ('long_prefill','{"row_003":3,"row_127":127}')])
def test_purpose_written_classes_have_real_prompt_and_quality_gate(class_id,text):
    session = driver(class_id)
    turn = session.next_turn()
    assert len(turn['messages'][0]['content']) > 20
    session.on_reply(reply(text))
    assert session.next_turn() is None


def test_output_heavy_order_and_minimum_output_are_validated():
    session = driver('output_heavy'); session.next_turn()
    with pytest.raises(ValueError): session.on_reply(reply('brief'))


def test_wrong_tool_fixture_hash_is_rejected():
    from runpod_benchmark.episode2_sessions import SessionDriver
    fixtures = deepcopy(TOOL_FIXTURES); fixtures['lookup_inventory']['result']['stock'] = 5
    with pytest.raises(ValueError, match='fixture'): SessionDriver(build_trace(make_synthetic_protocol()), 'wf-tool_call-001', fixtures)


def test_failed_transport_retains_unsent_descendants():
    session = driver('agent_chain'); session.next_turn()
    session.on_failure('request_timeout')
    assert session.blocked_request_ids == ['req-agent_chain-001-t2','req-agent_chain-001-t3']
    assert session.next_turn() is None


def test_closed_json_key_order_does_not_change_semantic_state():
    from runpod_benchmark.episode2_sessions import validate_semantic
    turn = driver('structured').next_turn()
    assert validate_semantic(turn, reply('{"unit":"items","answer":6}')) == {'answer':6,'unit':'items'}
    with pytest.raises(ValueError): validate_semantic(turn, reply('{"unit":"items","answer":true}'))


def test_tool_only_tpot_and_content_ttft_are_unavailable():
    value = tool_reply()
    assert value.ttft_ms is None and value.tpot_ms is None and value.e2e_ms > 0


def test_output_heavy_valid_order_rejects_reordered_concepts():
    from runpod_benchmark.episode2_corpus import OUTPUT_CONCEPTS
    from runpod_benchmark.episode2_sessions import validate_semantic
    turn = driver('output_heavy').next_turn()
    text = '\n'.join(f'{index}. {name}: This declared concept explains measured work across consistent repeated trials with explicit evidence.' for index,name in enumerate(OUTPUT_CONCEPTS,1))
    value = reply(text); value.output_tokens = 300
    assert validate_semantic(turn,value)['concepts'] == list(OUTPUT_CONCEPTS)
    value.text = '\n'.join(reversed(text.splitlines()))
    with pytest.raises(ValueError): validate_semantic(turn,value)


def test_rendered_message_hash_tampering_blocks_request():
    from runpod_benchmark.episode2_contract import document_digest
    from runpod_benchmark.episode2_sessions import SessionDriver
    trace = build_trace(make_synthetic_protocol())
    trace['blocks'][0]['turns'][0]['messages_sha256'] = '0'*64
    trace['logical_sha256'] = document_digest(trace['blocks'])
    session = SessionDriver(trace,'wf-short-001',TOOL_FIXTURES)
    with pytest.raises(ValueError, match='continuation'): session.next_turn()
    assert session.failure['reason'] == 'continuation_mismatch'


def test_observation_schema_closes_stream_reply_and_tool_events():
    import json
    from dataclasses import asdict
    from pathlib import Path
    from jsonschema import Draft202012Validator
    schema = json.loads(Path('schemas/episode2-observation.schema.json').read_text())
    value = {'schema_version':'episode2.observation.v1', **asdict(tool_reply())}
    validator = Draft202012Validator(schema)
    validator.validate(value)
    value['provider_handle'] = 'private-canary'
    assert list(validator.iter_errors(value))
    value.pop('provider_handle')
    value['tool_calls'][0]['function']['arbitrary'] = True
    assert list(validator.iter_errors(value))


def test_protocol_output_cap_is_bound_to_pending_semantic_validation():
    from runpod_benchmark.episode2_sessions import SessionDriver
    protocol = make_synthetic_protocol()
    protocol['mixture']['classes']['short']['requested_output_tokens'] = 32
    session = SessionDriver(build_trace(protocol),'wf-short-001',TOOL_FIXTURES,protocol=protocol)
    turn = session.next_turn()
    assert turn['requested_output_tokens'] == 32
    value = reply('Equal work preserves all declared inputs.')
    value.output_tokens = 33
    with pytest.raises(ValueError,match='cap'): session.on_reply(value)


def test_tool_duration_uses_one_injected_clock_domain():
    from runpod_benchmark.episode2_sessions import SessionDriver
    values = iter([100,125])
    protocol = make_synthetic_protocol()
    session = SessionDriver(build_trace(protocol),'wf-tool_call-001',TOOL_FIXTURES,protocol=protocol,clock=lambda:next(values))
    session.next_turn(); session.on_reply(tool_reply())
    observation = session.tool_observations[0]
    assert observation['started_ns'] == 100 and observation['terminal_ns'] == 125
    assert observation['duration_ns'] == 25


@pytest.mark.parametrize('class_id', ['tool_call', 'agent_chain'])
def test_tool_turn_requests_identical_required_singleton_decoder_envelope(class_id):
    session = driver(class_id)
    turn = session.next_turn()
    if class_id == 'agent_chain':
        session.on_reply(reply('{"sku":"widget"}'))
        turn = session.next_turn()
    assert turn['tool_choice'] == 'required'
    assert len(turn['tools']) == 1
    assert turn['tools'][0]['function']['name'] == 'lookup_inventory'
