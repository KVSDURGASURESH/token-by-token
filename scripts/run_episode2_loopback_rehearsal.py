#!/usr/bin/env python3
"""Private synthetic Episode 02 rehearsal through real localhost SSE transport."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from runpod_benchmark.episode2_contract import canonical_bytes, document_digest, loads_strict_json
from runpod_benchmark.episode2_corpus import OUTPUT_CONCEPTS, build_trace, expected_messages, make_synthetic_protocol
from runpod_benchmark.episode2_runner import run_campaign, validate_replay_pair
from runpod_benchmark.episode2_sessions import stream_turn


def fixture_response(turn: dict) -> dict:
    """Synthetic server content only; never imported by the measured session driver."""
    class_id, number = turn['class_id'], turn['turn_id']
    tool = (class_id == 'tool_call' and number == 'turn-1') or (class_id == 'agent_chain' and number == 'turn-2')
    contents = {
        'short': 'Equal work compares identical declared tasks and validated model outputs.',
        'long_prefill': '{"row_003":3,"row_127":127}',
        'structured': '{"answer":6,"unit":"items"}',
        'code_reasoning': '{"value":42,"expression":"6*7"}',
        'conversation': '{"selected":"orange"}' if number == 'turn-1' else '{"color":"orange"}',
        'tool_call': '{"answer":6}',
        'agent_chain': '{"sku":"widget"}' if number == 'turn-1' else '{"order":4}',
        'output_heavy': '\n'.join(f'{i}. {concept}: This declared concept keeps all measured comparisons aligned across repeated controlled workloads and observations.' for i, concept in enumerate(OUTPUT_CONCEPTS, 1)),
    }
    return {'tool': tool, 'text': contents[class_id], 'input_tokens': 2400 if class_id == 'long_prefill' else 32,
            'output_tokens': 300 if class_id == 'output_heavy' else 12}


def event(value: dict) -> bytes:
    return b'data: ' + canonical_bytes(value) + b'\n\n'


@contextmanager
def loopback(trace: dict):
    fixtures = {document_digest(expected_messages(turn)): fixture_response(turn) for turn in trace['blocks'][0]['turns']}
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if self.path != '/v1/chat/completions' or not 1 <= size <= 131072:
                    raise ValueError('bounded loopback request required')
                payload = loads_strict_json(self.rfile.read(size))
                fixture = fixtures[document_digest(payload['messages'])]
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                if fixture['tool']:
                    arguments = '{"sku":"widget"}'
                    chunks = [event({'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': 0, 'id': 'call_loopback',
                        'type': 'function', 'function': {'name': 'lookup_inventory', 'arguments': arguments[:7]}}]}, 'finish_reason': None}]}),
                        event({'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': 0, 'function': {'arguments': arguments[7:]}}]}, 'finish_reason': None}]}),
                        event({'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}]})]
                else:
                    content = fixture['text']
                    middle = max(1, len(content) // 2)
                    chunks = [event({'choices': [{'index': 0, 'delta': {'content': content[:middle]}, 'finish_reason': None}]}),
                              event({'choices': [{'index': 0, 'delta': {'content': content[middle:]}, 'finish_reason': 'stop'}]})]
                chunks += [event({'choices': [], 'usage': {'prompt_tokens': fixture['input_tokens'], 'completion_tokens': fixture['output_tokens']}}), b'data: [DONE]\n\n']
                for chunk in chunks:
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (KeyError, TypeError, ValueError):
                self.send_error(400, 'Invalid synthetic fixture request')
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1/chat/completions'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def private_json(path: Path, value: object) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(canonical_bytes(value) + b'\n')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path, help='new private directory; an existing path is rejected')
    parser.add_argument('--blocks', type=int, choices=(6, 7, 8), default=6)
    parser.add_argument('--mode', choices=('closed-loop', 'open-loop'), default='closed-loop')
    args = parser.parse_args(argv)
    output = args.output.absolute()
    output.mkdir(mode=0o700, exist_ok=False)
    protocol = make_synthetic_protocol(blocks=args.blocks, mode=args.mode)
    trace = build_trace(protocol)
    private_json(output / 'protocol.json', protocol)
    private_json(output / 'trace.json', trace)
    manifest = {'evidence_class': 'synthetic_mock', 'status': 'running', 'execution_ready': False,
                'transport': 'http_loopback_sse', 'provider_calls': 0, 'mode': args.mode,
                'token_counts': 'synthetic_fixture_usage_not_measured_tokenization', 'results': []}
    try:
        with loopback(trace) as url:
            def sender_factory(engine, _arm, _cell_id):
                connection = {'url': url, 'runtime_id': engine, 'model': 'fixture/model', 'seed': protocol['seed'],
                    'timeout_seconds': 5, 'max_response_bytes': 131072,
                    'runtime_capabilities': {name: True for name in ('streaming_sse', 'done_event', 'streamed_usage',
                        'exact_completion_tokens', 'tools', 'tool_choice', 'response_format')}}
                return lambda turn: stream_turn(turn, connection, time.monotonic_ns)
            campaign = run_campaign(protocol, trace, arm_ids=['defaults'], execution_id='episode2-loopback',
                                    sender_factory=sender_factory)
        for index, result in enumerate(campaign['results'], 1):
            filename = f'result-{index}.json'
            private_json(output / filename, result)
            manifest['results'].append(filename)
        try:
            validate_replay_pair(campaign['results'][0], campaign['results'][1])
        except ValueError:
            manifest['comparison'] = {'status': 'non_equivalent', 'qualified_for_comparison': False,
                                      'reason': 'retained_work_or_trajectory_mismatch'}
        else:
            manifest['comparison'] = {'status': 'equivalent', 'qualified_for_comparison': True, 'reason': None}
        private_json(output / 'order.json', {'evidence_class': 'synthetic_mock', 'order': campaign['order']})
        manifest['status'] = 'verified_synthetic_rehearsal'
        manifest['protocol_sha256'] = document_digest(protocol)
        manifest['trace_sha256'] = document_digest(trace)
        private_json(output / 'manifest.json', manifest)
        print(json.dumps({'evidence_class': 'synthetic_mock', 'status': manifest['status'], 'output': str(output)}))
        return 0
    except Exception:
        manifest['status'] = 'failed_synthetic_rehearsal'
        private_json(output / 'manifest.json', manifest)
        raise


if __name__ == '__main__':
    raise SystemExit(main())
