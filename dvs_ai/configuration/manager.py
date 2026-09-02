from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from collections.abc import Callable, Mapping

Validator = Callable[[Mapping[str, object]], None]

@dataclass(frozen=True)
class ConfigSnapshot:
    version: int
    digest: str
    data: Mapping[str, object]

class VersionedConfigManager:
    def __init__(self, initial: Mapping[str, object], validator: Validator | None = None) -> None:
        self._validator = validator
        self._history: list[dict[str, object]] = []
        self.apply(initial)

    @staticmethod
    def _digest(data: Mapping[str, object]) -> str:
        return sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

    def apply(self, data: Mapping[str, object]) -> ConfigSnapshot:
        candidate = deepcopy(dict(data))
        if self._validator:
            self._validator(candidate)
        self._history.append(candidate)
        return self.current

    @property
    def current(self) -> ConfigSnapshot:
        data = deepcopy(self._history[-1])
        return ConfigSnapshot(len(self._history), self._digest(data), data)

    def rollback(self, version: int) -> ConfigSnapshot:
        if version < 1 or version > len(self._history):
            raise ValueError("unknown configuration version")
        return self.apply(self._history[version - 1])
