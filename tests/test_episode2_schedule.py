"""Scheduling contract: paired blocks and arrivals independent of response timing."""
from collections import Counter

import pytest

from runpod_benchmark.episode2_corpus import build_trace, make_synthetic_protocol
from runpod_benchmark.episode2_schedule import compile_arrivals, compile_order, eligible_send_ns


@pytest.mark.parametrize('blocks', [6, 7, 8])
def test_order_pairs_each_engine_and_arm_once_per_block(blocks):
    protocol = make_synthetic_protocol(blocks=blocks)
    rows = compile_order(protocol, ['defaults', 'treatment-1'])
    assert len(rows) == blocks * 4
    assert rows == compile_order(protocol, ['defaults', 'treatment-1'])
    for index in range(1, blocks + 1):
        entries = [row for row in rows if row['block_id'] == f'block-{index:02d}']
        assert {(row['engine'], row['arm']) for row in entries} == {
            ('vllm', 'defaults'), ('vllm', 'treatment-1'),
            ('sglang', 'defaults'), ('sglang', 'treatment-1'),
        }
    first_engines = Counter(rows[index * 4]['engine'] for index in range(blocks))
    assert abs(first_engines['vllm'] - first_engines['sglang']) <= 1
    first_arms = Counter(rows[index * 4]['arm'] for index in range(blocks))
    assert abs(first_arms['defaults'] - first_arms['treatment-1']) <= 1


@pytest.mark.parametrize('arms', [[], ['defaults', 'defaults'], [''], [True], ['x'] * 9])
def test_invalid_arm_set_rejected_before_scheduling(arms):
    with pytest.raises(ValueError):
        compile_order(make_synthetic_protocol(), arms)


def test_arrivals_keep_quiet_burst_and_recovery_without_completion_input():
    protocol = make_synthetic_protocol(mode='open-loop')
    block = build_trace(protocol)['blocks'][0]
    rows = compile_arrivals(protocol, block, start_ns=1000)
    assert [row['scheduled_ns'] - 1000 for row in rows[:3]] == [0, 100_000_000, 200_000_000]
    assert [row['phase'] for row in rows] == ['quiet'] * 3 + ['burst'] * 4 + ['recovery']
    assert rows == compile_arrivals(protocol, block, start_ns=1000)
    assert [row['workflow_id'] for row in rows] == [row['workflow_id'] for row in block['workflows']]
    assert all(row['scheduled_ns'] > prior['scheduled_ns'] for prior, row in zip(rows, rows[1:]))
    assert all(row['interarrival_ns'] == row['scheduled_ns'] - prior['scheduled_ns'] for prior, row in zip(rows, rows[1:]))


@pytest.mark.parametrize('scheduled,predecessor,want', [(0, None, 0), (100, 50, 100), (100, 200, 200), (100, 0, 100)])
def test_dependency_eligibility_is_separate_from_scheduled_arrival(scheduled, predecessor, want):
    assert eligible_send_ns(scheduled, predecessor) == want


@pytest.mark.parametrize('scheduled,predecessor', [(-1, None), (True, None), (0, False), (0, -1), (1.0, None)])
def test_invalid_timestamp_rejected(scheduled, predecessor):
    with pytest.raises(ValueError):
        eligible_send_ns(scheduled, predecessor)
