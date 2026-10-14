import json

import pytest

from test_episode1_sse_loopback import endpoint, event, request
from runpod_benchmark.streaming import StreamingError, stream_chat

TOOLS = [{"type": "function", "function": {"name": "lookup_inventory", "parameters": {"type": "object", "additionalProperties": False, "required": ["sku"], "properties": {"sku": {"const": "widget"}}}}}]


def tool_request(url):
    value = request(url)
    value.update(tools=TOOLS, tool_choice={"type": "function", "function": {"name": "lookup_inventory"}}, record_events=True)
    value["runtime_capabilities"].update(tools=True, tool_choice=True)
    return value


def chunks(arguments='{"sku":"widget"}', finish='tool_calls'):
    return [
        event({"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "call_fixture", "type": "function", "function": {"name": "lookup_inventory", "arguments": arguments[:7]}}]}, "finish_reason": None}]}),
        event({"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": arguments[7:]}}]}, "finish_reason": None}]}),
        event({"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}),
        event({"choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 8}}),
        b'data: [DONE]\n\n',
    ]


def test_fragmented_tool_only_stream_preserves_separate_event_times():
    with endpoint(chunks()) as url:
        result = stream_chat(tool_request(url))
    assert result['tool_calls'] == [{"id": "call_fixture", "type": "function", "function": {"name": "lookup_inventory", "arguments": '{"sku":"widget"}'}}]
    assert result['text'] == '' and result['ttft_ms'] is None
    assert result['content_span_ms'] is None
    assert result['first_content_ns'] is None and result['last_content_ns'] is None
    assert result['content_events'] == []
    assert len(result['tool_events']) == 2
    assert result['actual_send_ns'] <= result['tool_events'][0]['received_ns'] <= result['terminal_ns']
    assert result['input_tokens'] == 20 and result['output_tokens'] == 8


@pytest.mark.parametrize('arguments,finish', [('{','length'), ('{"sku":"widget","sku":"widget"}','tool_calls'), ('{"sku":NaN}','tool_calls'), ('{"sku":"other"}','tool_calls'), ('[]','tool_calls'), ('{"sku":"widget"}','stop')])
def test_tool_stream_rejects_invalid_or_truncated_calls(arguments, finish):
    with endpoint(chunks(arguments, finish)) as url:
        with pytest.raises(StreamingError):
            stream_chat(tool_request(url))


@pytest.mark.parametrize('mutation', ['second_index','changed_id','duplicate_name','wrong_name','boolean_index'])
def test_tool_identity_is_closed_and_single_call(mutation):
    data = chunks()
    fragment = {'index': 0, 'function': {'arguments': '"widget"}'}}
    if mutation == 'second_index': fragment['index'] = 1
    if mutation == 'changed_id': fragment['id'] = 'different'
    if mutation == 'duplicate_name': fragment['function']['name'] = 'lookup_inventory'
    if mutation == 'wrong_name':
        data[0] = event({'choices':[{'delta':{'tool_calls':[{'index':0,'id':'call_fixture','function':{'name':'other','arguments':'{"sku":'}}]}}]})
    if mutation == 'boolean_index': fragment['index'] = True
    data[1] = event({'choices':[{'delta':{'tool_calls':[fragment]}}]})
    with endpoint(data) as url:
        with pytest.raises(StreamingError): stream_chat(tool_request(url))


def test_unsupported_tool_capability_is_rejected_before_connection():
    value = tool_request('http://127.0.0.1:1/v1/chat/completions')
    value['runtime_capabilities']['tools'] = False
    with pytest.raises(StreamingError, match='unsupported optional request field: tools'):
        stream_chat(value)


def test_structured_response_format_is_sent_and_events_are_opt_in():
    data = [event({'choices':[{'delta':{'content':'{"answer":6,"unit":"items"}'},'finish_reason':'stop'}]}), event({'choices':[],'usage':{'prompt_tokens':12,'completion_tokens':9}}), b'data: [DONE]\n\n']
    with endpoint(data) as url:
        value = request(url)
        value.update(response_format={'type':'json_object'}, record_events=True)
        value['runtime_capabilities']['response_format'] = True
        result = stream_chat(value)
    assert len(result['content_events']) == 1 and result['tool_events'] == []
    assert result['content_events'][0]['text'] == '{"answer":6,"unit":"items"}'
    with endpoint(data) as url:
        legacy = stream_chat(request(url))
    assert 'content_events' not in legacy and 'tool_calls' not in legacy


def test_tool_byte_cap_remains_bounded():
    with endpoint(chunks('{"sku":"' + 'x' * 10000 + '"}')) as url:
        value = tool_request(url)
        value['max_response_bytes'] = 1024
        with pytest.raises(StreamingError, match='cap'): stream_chat(value)


@pytest.mark.parametrize('arguments', ['null', '{"sku":1e999}'])
def test_nonobject_or_nonfinite_tool_json_is_rejected(arguments):
    with endpoint(chunks(arguments)) as url:
        with pytest.raises(StreamingError): stream_chat(tool_request(url))


def test_failed_tools_retain_partial_event_evidence():
    with endpoint(chunks('{')) as url:
        with pytest.raises(StreamingError) as caught: stream_chat(tool_request(url))
    assert len(caught.value.tool_events) == 2
    assert caught.value.tool_events[0]['received_ns'] >= caught.value.actual_send_ns


def test_stream_turn_uses_real_transport_and_exact_input_usage():
    import time
    from runpod_benchmark.episode2_corpus import TOOL_FIXTURES, build_trace, make_synthetic_protocol
    from runpod_benchmark.episode2_sessions import SessionDriver, stream_turn
    session = SessionDriver(build_trace(make_synthetic_protocol()), 'wf-structured-001', TOOL_FIXTURES)
    turn = session.next_turn()
    data = [event({'choices':[{'delta':{'content':'{"answer":6,"unit":"items"}'},'finish_reason':'stop'}]}), event({'choices':[],'usage':{'prompt_tokens':12,'completion_tokens':9}}), b'data: [DONE]\n\n']
    with endpoint(data) as url:
        connection = request(url)
        connection['runtime_capabilities']['response_format'] = True
        connection.update(require_exact_prompt_tokens=True, expected_prompt_tokens=12)
        result = stream_turn(turn, connection, time.monotonic_ns)
    session.on_reply(result)
    assert result.text == '{"answer":6,"unit":"items"}' and result.input_tokens == 12
    assert session.next_turn() is None


def test_stream_turn_refuses_missing_input_usage():
    import time
    from runpod_benchmark.episode2_corpus import TOOL_FIXTURES, build_trace, make_synthetic_protocol
    from runpod_benchmark.episode2_sessions import SessionDriver, stream_turn
    turn = SessionDriver(build_trace(make_synthetic_protocol()), 'wf-short-001', TOOL_FIXTURES).next_turn()
    data = [event({'choices':[{'delta':{'content':'Equal work preserves all declared inputs.'},'finish_reason':'stop'}]}), event({'choices':[],'usage':{'completion_tokens':9}}), b'data: [DONE]\n\n']
    with endpoint(data) as url:
        with pytest.raises(StreamingError, match='input token'): stream_turn(turn, request(url), time.monotonic_ns)


def test_content_after_finish_is_rejected_by_episode2_dialect():
    data = [event({'choices':[{'delta':{'content':'first'},'finish_reason':'stop'}]}), event({'choices':[{'delta':{'content':' late'},'finish_reason':None}]}), event({'choices':[],'usage':{'prompt_tokens':12,'completion_tokens':9}}), b'data: [DONE]\n\n']
    with endpoint(data) as url:
        value = request(url); value['record_events'] = True
        with pytest.raises(StreamingError,match='after finish'): stream_chat(value)


@pytest.mark.parametrize('content',['','{"unexpected":true}'])
def test_episode2_preserves_completed_missing_tool_reply_and_actual_wire_fields(monkeypatch,content):
    from test_episode1_sse_loopback import Handler
    from runpod_benchmark.episode2_corpus import TOOL_FIXTURES,build_trace,make_synthetic_protocol
    from runpod_benchmark.episode2_sessions import SessionDriver,stream_turn
    captured=[]
    def post(handler):
        captured.append(json.loads(handler.rfile.read(int(handler.headers['Content-Length']))))
        handler.send_response(200);handler.send_header('Content-Type','text/event-stream');handler.end_headers()
        for chunk in handler.chunks:handler.wfile.write(chunk);handler.wfile.flush()
    monkeypatch.setattr(Handler,'do_POST',post)
    data=[event({'choices':[{'delta':{'content':content},'finish_reason':'length'}]}),event({'choices':[],'usage':{'prompt_tokens':20,'completion_tokens':8}}),b'data: [DONE]\n\n']
    with endpoint(data) as url:
        strict=tool_request(url);strict['tool_choice']='required'
        with pytest.raises(StreamingError,match='required declared tool call is missing'):stream_chat(strict)
        session=SessionDriver(build_trace(make_synthetic_protocol()),'wf-tool_call-001',TOOL_FIXTURES)
        turn=session.next_turn();turn['requested_output_tokens']=64
        connection=request(url);connection['runtime_capabilities'].update(tools=True,tool_choice=True)
        result=stream_turn(turn,connection)
    wire=captured[-1]
    assert wire['tools']==turn['tools'] and wire['tool_choice']=='required' and wire['max_tokens']==64
    assert wire['stream'] is True and wire['stream_options']['include_usage'] is True
    assert 'defer_missing_required_tool' not in wire
    assert result.text==content and result.tool_calls==[] and result.stop_reason=='length'
    assert result.input_tokens==20 and result.output_tokens==8
    assert result.actual_send_ns<=result.terminal_ns
    with pytest.raises(ValueError):session.on_reply(result)
    assert session.tool_observations==[] and session.next_turn() is None
    assert session.blocked_request_ids==['req-tool_call-001-t2']


@pytest.mark.parametrize('missing',['done','usage'])
def test_missing_tool_defer_never_accepts_incomplete_sse_or_missing_usage(missing):
    data=[event({'choices':[{'delta':{'content':'{}'},'finish_reason':'stop'}]}),event({'choices':[],'usage':{'prompt_tokens':20,'completion_tokens':8}}),b'data: [DONE]\n\n']
    if missing=='done':data=data[:-1]
    else:data.pop(1)
    with endpoint(data) as url:
        value=tool_request(url);value.update(tool_choice='required',defer_missing_required_tool=True)
        with pytest.raises(StreamingError):stream_chat(value)
