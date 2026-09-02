from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class SignalDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class MarketRegime(str, Enum):
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    symbol: str
    timeframe: str
    close: float
    features: Mapping[str, float] = field(default_factory=dict)
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.symbol.strip() or not self.timeframe.strip():
            raise ValueError("symbol and timeframe are required")
        if self.close <= 0:
            raise ValueError("close must be positive")
        object.__setattr__(self, "symbol", self.symbol.upper().strip())
        object.__setattr__(self, "timeframe", self.timeframe.strip())
        object.__setattr__(self, "features", MappingProxyType(dict(self.features)))


@dataclass(frozen=True, slots=True)
class StrategySignal:
    strategy_id: str
    direction: SignalDirection
    confidence: float
    reason_codes: tuple[str, ...] = ()
    metadata: Mapping[str, float | str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.strategy_id.strip():
            raise ValueError("strategy_id is required")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class FusedSignal:
    direction: SignalDirection
    confidence: float
    regime: MarketRegime
    contributors: tuple[str, ...]
    reason_codes: tuple[str, ...]
    long_score: float
    short_score: float


@dataclass(frozen=True, slots=True)
class StrategyScore:
    strategy_id: str
    observations: int
    wins: int
    losses: int
    net_return: float
    win_rate: float
    reliability: float
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    strategy_id: str
    direction: SignalDirection
    entry_index: int
    exit_index: int
    entry_price: float
    exit_price: float
    return_pct: float


@dataclass(frozen=True, slots=True)
class BacktestReport:
    strategy_id: str
    trades: tuple[BacktestTrade, ...]
    total_return: float
    win_rate: float
    max_drawdown: float
