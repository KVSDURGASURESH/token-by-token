from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class SyntheticRequest:
    request_id: str
    users: int
    seed: int
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class SyntheticEvent:
    sequence: int
    kind: str
    monotonic_ms: int
    payload: Mapping[str, object]

    @classmethod
    def create(cls, sequence: int, kind: str, payload: Mapping[str, object]) -> "SyntheticEvent":
        return cls(sequence=sequence, kind=kind, monotonic_ms=sequence * 10, payload=MappingProxyType(dict(payload)))

    def to_json(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "monotonic_ms": self.monotonic_ms,
            "payload": dict(self.payload),
            "sequence": self.sequence,
        }

