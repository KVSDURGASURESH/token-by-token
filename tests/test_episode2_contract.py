"""Formal Episode 02 mixed-workflow protocol and trace tests."""

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from runpod_benchmark.episode2_contract import document_digest, validate_protocol, validate_trace
from runpod_benchmark.episode2_corpus import build_trace, make_synthetic_protocol, trace_digest


ROOT = Path(__file__).resolve().parents[1]


def test_every_block_preserves_all_eight_workflow_classes():
    protocol = make_synthetic_protocol(blocks=6)
    validate_protocol(protocol)
    trace = build_trace(protocol)
    assert len(trace["blocks"]) == 6
    for block in trace["blocks"]:
        assert set(block["class_counts"].values()) == {1}
        assert len(block["class_counts"]) == 8
        assert len(block["workflows"]) == 8
        assert len(block["turns"]) == 12
    validate_trace(trace, protocol)


@pytest.mark.parametrize("blocks", [0, 5, 9, True])
def test_invalid_block_count_is_rejected(blocks):
    with pytest.raises(ValueError):
        validate_protocol(make_synthetic_protocol(blocks=blocks))


def test_protocol_binds_canonical_catalog_identity_and_is_never_execution_ready():
    protocol = make_synthetic_protocol()
    expected = hashlib.sha256((ROOT / "public-data/contracts/episode-catalog.v2.json").read_bytes()).hexdigest()
    assert protocol["episode"] == 2
    assert protocol["title"] == "Equal-work runtime baseline"
    assert protocol["catalog_sha256"] == expected
    assert protocol["classification"] == "synthetic_mock"
    assert protocol["material"]["execution_ready"] is False


def test_wrong_weights_undefined_classes_and_mutable_material_fail_closed():
    protocol = make_synthetic_protocol()
    protocol["mixture"]["weights"]["short"] = 2
    with pytest.raises(ValueError, match="weights"):
        validate_protocol(protocol)

    protocol = make_synthetic_protocol()
    protocol["mixture"]["weights"]["unknown"] = 1
    with pytest.raises(ValueError, match="classes"):
        validate_protocol(protocol)

    for field, value in (("model_revision", "main"), ("vllm_image", "repo/image:latest")):
        protocol = make_synthetic_protocol()
        protocol["material"][field] = value
        with pytest.raises(ValueError, match="immutable"):
            validate_protocol(protocol)


def test_output_and_context_limits_are_validated():
    protocol = make_synthetic_protocol()
    protocol["mixture"]["classes"]["output_heavy"]["requested_output_tokens"] = 513
    with pytest.raises(ValueError, match="output"):
        validate_protocol(protocol)

    protocol = make_synthetic_protocol()
    protocol["mixture"]["classes"]["long_prefill"]["input_tokens_max"] = 5000
    with pytest.raises(ValueError, match="context"):
        validate_protocol(protocol)


def test_trace_rejects_cycles_duplicates_and_changed_tool_fixture_hash():
    protocol = make_synthetic_protocol()
    trace = build_trace(protocol)
    trace["blocks"][0]["turns"][0]["predecessor_id"] = trace["blocks"][0]["turns"][0]["logical_request_id"]
    trace["logical_sha256"] = document_digest(trace["blocks"])
    with pytest.raises(ValueError, match="cycle"):
        validate_trace(trace, protocol)

    trace = build_trace(protocol)
    trace["blocks"][0]["turns"][1]["logical_request_id"] = trace["blocks"][0]["turns"][0]["logical_request_id"]
    trace["logical_sha256"] = document_digest(trace["blocks"])
    with pytest.raises(ValueError, match="duplicate"):
        validate_trace(trace, protocol)

    changed = build_trace(protocol)
    changed["tool_fixtures_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="tool fixture"):
        validate_trace(changed, protocol)


def test_trace_digest_is_deterministic_and_logical_ids_replay_across_blocks():
    protocol = make_synthetic_protocol(blocks=6)
    first = build_trace(protocol)
    second = build_trace(protocol)
    assert trace_digest(first) == trace_digest(second)
    ids_by_block = [
        [turn["logical_request_id"] for turn in block["turns"]]
        for block in first["blocks"]
    ]
    assert all(ids == ids_by_block[0] for ids in ids_by_block[1:])


def test_committed_synthetic_fixture_matches_generated_protocol():
    fixture = json.loads((ROOT / "tests/fixtures/episode2/protocol.synthetic.json").read_text())
    assert fixture == make_synthetic_protocol()


def test_generated_protocol_and_trace_match_published_schemas():
    protocol = make_synthetic_protocol()
    trace = build_trace(protocol)
    for name, value in (("episode2-protocol.schema.json", protocol), ("episode2-trace.schema.json", trace)):
        schema = json.loads((ROOT / "schemas" / name).read_text())
        assert list(Draft202012Validator(schema).iter_errors(value)) == []


def rehash(trace):
    trace['logical_sha256'] = document_digest(trace['blocks'])
    return trace


@pytest.mark.parametrize('section', ['order_policy', 'warmup_reset', 'quality', 'metrics', 'uncertainty', 'safeguards'])
def test_nested_protocol_contract_rejects_unbound_fields(section):
    protocol = make_synthetic_protocol()
    protocol[section]['unbound_override'] = True
    with pytest.raises(ValueError):
        validate_protocol(protocol)


@pytest.mark.parametrize('section,field,value', [
    ('uncertainty', 'minimum_blocks', 1),
    ('uncertainty', 'seed', True),
    ('metrics', 'p99_min_n', 10),
    ('warmup_reset', 'warmup_requests', True),
    ('safeguards', 'error_rate_max', -1),
    ('safeguards', 'quality_min', 2),
])
def test_protocol_rejects_invalid_science_contract(section, field, value):
    protocol = make_synthetic_protocol()
    protocol[section][field] = value
    with pytest.raises(ValueError):
        validate_protocol(protocol)


def test_two_turn_cycle_is_rejected():
    protocol = make_synthetic_protocol()
    trace = build_trace(protocol)
    turns = [t for t in trace['blocks'][0]['turns'] if t['class_id'] == 'conversation']
    turns[0]['predecessor_id'] = turns[1]['logical_request_id']
    with pytest.raises(ValueError, match='cycle'):
        validate_trace(rehash(trace), protocol)


@pytest.mark.parametrize('mutation', ['counts', 'weights', 'missing_workflow', 'session', 'missing_turn', 'messages_hash', 'extra_turn_field', 'mode', 'eligibility', 'corpus_ref'])
def test_trace_is_checked_against_the_actual_workload_contract(mutation):
    protocol = make_synthetic_protocol()
    trace = build_trace(protocol)
    block = trace['blocks'][0]
    if mutation == 'counts':
        block['class_counts']['short'] = 200
    elif mutation == 'weights':
        block['class_weights']['short'] = 5
    elif mutation == 'missing_workflow':
        block['workflows'].pop()
    elif mutation == 'session':
        block['turns'][0]['session_id'] = 'other'
    elif mutation == 'missing_turn':
        block['turns'].pop()
    elif mutation == 'messages_hash':
        block['turns'][0]['messages_sha256'] = 'not-a-hash'
    elif mutation == 'extra_turn_field':
        block['turns'][0]['unbound'] = True
    elif mutation == 'mode':
        trace['mode'] = 'open-loop'
    elif mutation == 'eligibility':
        block['turns'][0]['eligibility'] = 'predecessor_valid'
    elif mutation == 'corpus_ref':
        block['turns'][0]['corpus_ref'] = 'unbound-corpus'
    with pytest.raises(ValueError):
        validate_trace(rehash(trace), protocol)


def test_mixture_turn_counts_cannot_change_corpus_graph():
    protocol = make_synthetic_protocol()
    protocol['mixture']['classes']['agent_chain']['turns'] = 1
    with pytest.raises(ValueError):
        validate_protocol(protocol)


def test_strict_json_ingestion_rejects_duplicate_and_nonfinite_values():
    from runpod_benchmark.episode2_contract import loads_strict_json
    for payload in ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}']:
        with pytest.raises(ValueError):
            loads_strict_json(payload)


def test_published_schema_rejects_unknown_nested_science_fields():
    protocol = make_synthetic_protocol()
    protocol['uncertainty']['unbound'] = True
    schema = json.loads((ROOT / 'schemas/episode2-protocol.schema.json').read_text())
    assert list(Draft202012Validator(schema).iter_errors(protocol))


def test_catalog_and_fixture_digests_match_actual_source_content():
    for field in ['catalog_sha256', 'tool_fixtures_sha256']:
        protocol = make_synthetic_protocol()
        protocol[field] = 'f' * 64
        with pytest.raises(ValueError):
            build_trace(protocol)


def test_committed_tool_fixture_matches_the_generated_content():
    from runpod_benchmark.episode2_corpus import TOOL_FIXTURES
    assert json.loads((ROOT / 'tests/fixtures/episode2/tool-fixtures.json').read_text()) == TOOL_FIXTURES


def test_trace_hashes_bind_initial_and_expected_continuation_messages():
    from runpod_benchmark.episode2_corpus import initial_messages, build_continuation
    protocol = make_synthetic_protocol()
    trace = build_trace(protocol)
    initial = next(t for t in trace['blocks'][0]['turns'] if t['class_id'] == 'short')
    successor = next(t for t in trace['blocks'][0]['turns'] if t['class_id'] == 'conversation' and t['turn_id'] == 'turn-2')
    assert initial['messages_sha256'] == document_digest(initial_messages(initial))
    assert successor['messages_sha256'] == document_digest(build_continuation(successor, {'selected': 'orange'}, None))
    for block in trace['blocks']:
        block['turns'][0]['messages_sha256'] = 'f' * 64
    with pytest.raises(ValueError):
        validate_trace(rehash(trace), protocol)


def test_concrete_public_corpus_has_indexed_table_and_ordered_reference_concepts():
    from runpod_benchmark.episode2_corpus import initial_messages, OUTPUT_CONCEPTS
    long = initial_messages({'class_id': 'long_prefill', 'turn_id': 'turn-1'})[0]['content']
    assert 'row_003=3' in long and 'row_127=127' in long and 'row_255=255' in long
    heavy = initial_messages({'class_id': 'output_heavy', 'turn_id': 'turn-1'})[0]['content']
    assert len(OUTPUT_CONCEPTS) == 16
    assert all(concept in heavy for concept in OUTPUT_CONCEPTS)


def test_canonical_continuation_rejects_divergent_or_unbound_state():
    from runpod_benchmark.episode2_corpus import build_continuation
    turn = {'class_id': 'conversation', 'turn_id': 'turn-2'}
    with pytest.raises(ValueError):
        build_continuation(turn, {'selected': 'blue'}, None)
    with pytest.raises(ValueError):
        build_continuation(turn, {'selected': 'orange', 'free_prose': 'unbound'}, None)
    tool_turn = {'class_id': 'tool_call', 'turn_id': 'turn-2'}
    with pytest.raises(ValueError):
        build_continuation(tool_turn, {'name': 'lookup_inventory', 'arguments': {'sku': 'widget'}}, {'stock': 8})


@pytest.mark.parametrize('mutation', ['synthetic_ready', 'revision', 'image', 'seed', 'unbounded_id', 'override_object'])
def test_schema_runtime_negative_parity(mutation):
    protocol = make_synthetic_protocol()
    if mutation == 'synthetic_ready':
        protocol['material']['execution_ready'] = True
    elif mutation == 'revision':
        protocol['material']['model_revision'] = 'main'
    elif mutation == 'image':
        protocol['material']['vllm_image'] = 'repo/image:latest'
    elif mutation == 'seed':
        protocol['seed'] = 2**32
    elif mutation == 'unbounded_id':
        protocol['campaign_id'] = 'a' * 513
    elif mutation == 'override_object':
        protocol['material']['common_launch_overrides'] = [{'flag': 'unbound'}]
    schema = json.loads((ROOT / 'schemas/episode2-protocol.schema.json').read_text())
    assert list(Draft202012Validator(schema).iter_errors(protocol))
    with pytest.raises(ValueError):
        validate_protocol(protocol)
