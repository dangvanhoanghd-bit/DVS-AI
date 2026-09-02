from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import MarketRegime, MarketSnapshot, StrategySignal


@runtime_checkable
class StrategyPlugin(Protocol):
    strategy_id: str
    version: str
    supported_regimes: frozenset[MarketRegime]

    def evaluate(self, snapshot: MarketSnapshot) -> StrategySignal:
        ...


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, StrategyPlugin] = {}

    def register(self, strategy: StrategyPlugin) -> None:
        if not isinstance(strategy, StrategyPlugin):
            raise TypeError("strategy does not satisfy StrategyPlugin protocol")
        key = strategy.strategy_id.strip()
        if not key:
            raise ValueError("strategy_id is required")
        if key in self._strategies:
            raise ValueError(f"strategy already registered: {key}")
        self._strategies[key] = strategy

    def get(self, strategy_id: str) -> StrategyPlugin:
        return self._strategies[strategy_id]

    def all(self) -> tuple[StrategyPlugin, ...]:
        return tuple(self._strategies[key] for key in sorted(self._strategies))
