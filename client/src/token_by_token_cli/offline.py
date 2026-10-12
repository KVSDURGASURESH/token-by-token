from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
import random

from .model import SyntheticEvent, SyntheticRequest


def run_synthetic_episode(
    manifest: Mapping[str, object],
    *,
    users: int,
    seed: int,
    stop_requested: Callable[[], bool],
) -> Iterator[SyntheticEvent]:
    declared_levels = manifest["load_levels"]
    if users not in declared_levels:
        raise ValueError(f"users={users} is not declared for episode {manifest['episode']}")
    if seed < 0 or seed > 2_147_483_647:
        raise ValueError("seed must be between 0 and 2147483647")

    episode = int(manifest["episode"])
    rng = random.Random((episode + 1) * 1_000_003 + seed + users * 97)
    sequence = 0

    def event(kind: str, payload: Mapping[str, object]) -> SyntheticEvent:
        nonlocal sequence
        value = SyntheticEvent.create(sequence, kind, payload)
        sequence += 1
        return value

    if stop_requested():
        yield event("run_interrupted", {"classification": "synthetic_mock", "completed_events": 0})
        return
    yield event(
        "plan",
        {
            "classification": "synthetic_mock",
            "episode": episode,
            "protocol": manifest["protocol"],
            "seed": seed,
            "users": users,
        },
    )

    for arm_index, arm in enumerate(("synthetic-a", "synthetic-b")):
        if stop_requested():
            yield event("run_interrupted", {"classification": "synthetic_mock", "completed_events": sequence})
            return
        yield event("arm_started", {"arm": arm})
        if stop_requested():
            yield event("run_interrupted", {"classification": "synthetic_mock", "completed_events": sequence})
            return
        request = SyntheticRequest(
            request_id=f"mock-{arm_index:02d}-0000",
            users=users,
            seed=seed,
            input_tokens=rng.randint(128, 512),
            output_tokens=rng.randint(32, 128),
        )
        yield event(
            "request",
            {
                "arm": arm,
                "input_tokens": request.input_tokens,
                "output_tokens": request.output_tokens,
                "request_id": request.request_id,
                "seed": request.seed,
                "users": request.users,
            },
        )
        duration_ms = 1_000 + users * 25 + arm_index * 100
        yield event(
            "metric",
            {
                "arm": arm,
                "name": "synthetic_output_tokens_per_second",
                "unit": "tok/s",
                "value": request.output_tokens * 1_000 // duration_ms,
            },
        )
        yield event("arm_completed", {"arm": arm, "requests": 1})

    yield event("run_completed", {"arms": 2, "classification": "synthetic_mock", "requests": 2})

