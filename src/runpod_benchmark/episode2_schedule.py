"""Reproducible pairing and a versioned synthetic open-loop arrival policy."""
from __future__ import annotations

from copy import deepcopy
import random

from .episode2_contract import require, validate_protocol


SYNTHETIC_ARRIVAL_POLICY = {
    'version': 'episode2.seeded_burst.v1',
    'quiet_workflows': 3,
    'quiet_interarrival_ns': 100_000_000,
    'burst_fraction': 0.5,
    'burst_interarrival_ms_min': 5,
    'burst_interarrival_ms_max': 15,
    'recovery_interarrival_ns': 100_000_000,
    'overflow': 'reject_whole_workflow',
}


def _timestamp(value: int) -> None:
    require(type(value) is int and 0 <= value <= 2**63 - 1, 'invalid monotonic timestamp')


def eligible_send_ns(scheduled_ns: int, predecessor_valid_ns: int | None) -> int:
    _timestamp(scheduled_ns)
    if predecessor_valid_ns is not None:
        _timestamp(predecessor_valid_ns)
    return max(scheduled_ns, predecessor_valid_ns if predecessor_valid_ns is not None else scheduled_ns)


def compile_order(protocol: dict, arm_ids: list[str]) -> list[dict]:
    """Pair engines/arms within every block; counterbalance first position by block."""
    validate_protocol(protocol)
    require(isinstance(arm_ids, list) and 1 <= len(arm_ids) <= 8, 'bounded arm list required')
    require(all(isinstance(arm, str) and 1 <= len(arm) <= 128 for arm in arm_ids), 'invalid arm identity')
    require(len(set(arm_ids)) == len(arm_ids), 'duplicate arm identity')
    rng = random.Random(protocol['seed'])
    engines = ['vllm', 'sglang']
    arms = list(arm_ids)
    rng.shuffle(engines)
    rng.shuffle(arms)
    rows = []
    for cell in protocol['cells']:
        for index in range(protocol['repetition_blocks']):
            engine_order = engines if index % 2 == 0 else engines[::-1]
            offset = index % len(arms)
            arm_order = arms[offset:] + arms[:offset]
            for engine in engine_order:
                for arm in arm_order:
                    rows.append({'ordinal': len(rows), 'block_id': f'block-{index + 1:02d}',
                                 'engine': engine, 'arm': arm, 'cell_id': cell['cell_id']})
    return rows


def compile_arrivals(protocol: dict, block: dict, *, start_ns: int = 0) -> list[dict]:
    """Return fixed workflow arrivals; no response/completion is an input.

    The v1 constants define synthetic rehearsal only. Recorded scheduling requires
    a later compiled, owner-reviewed numeric arrival and admission contract.
    """
    validate_protocol(protocol)
    _timestamp(start_ns)
    require(protocol['classification'] == 'synthetic_mock', 'recorded arrivals require compiled schedule authority')
    workflows = block.get('workflows')
    require(isinstance(workflows, list) and workflows, 'workflows required')
    rng = random.Random(protocol['seed'])
    quiet = min(3, len(workflows))
    burst = min(max(1, len(workflows) // 2), max(0, len(workflows) - quiet - 1))
    offset = 0
    rows = []
    for index, workflow in enumerate(workflows):
        if index < quiet:
            phase, delta = 'quiet', (0 if index == 0 else 100_000_000)
        elif index < quiet + burst:
            phase = 'burst'
            delta = 100_000_000 if index == quiet else rng.randint(5, 15) * 1_000_000
        else:
            phase, delta = 'recovery', 100_000_000
        offset += delta
        scheduled = start_ns + offset
        _timestamp(scheduled)
        rows.append({**deepcopy(workflow), 'phase': phase, 'scheduled_ns': scheduled,
                     'offset_ns': offset, 'interarrival_ns': delta})
    return rows
