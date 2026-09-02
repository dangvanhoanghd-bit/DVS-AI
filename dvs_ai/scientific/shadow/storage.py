from __future__ import annotations
from collections import defaultdict
from typing import Protocol
from .models import ShadowObservation

class ShadowStorage(Protocol):
    def append(self, observation: ShadowObservation) -> None: ...
    def read_decision(self, decision_id: str) -> tuple[ShadowObservation, ...]: ...
    def read_all(self) -> tuple[ShadowObservation, ...]: ...

class InMemoryShadowStorage:
    def __init__(self) -> None:
        self._rows: list[ShadowObservation] = []
    def append(self, observation: ShadowObservation) -> None:
        self._rows.append(observation)
    def read_decision(self, decision_id: str) -> tuple[ShadowObservation, ...]:
        return tuple(x for x in self._rows if x.decision_id == decision_id)
    def read_all(self) -> tuple[ShadowObservation, ...]:
        return tuple(self._rows)
