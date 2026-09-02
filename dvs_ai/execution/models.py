from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class ExecutionMode(str, Enum):
    PAPER = "PAPER"
    TESTNET = "TESTNET"
    LIVE = "LIVE"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    RECONCILIATION_FAILED = "RECONCILIATION_FAILED"


@dataclass(frozen=True)
class ExecutionIntent:
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float | None = None
    stop_price: float | None = None
    reduce_only: bool = False
    leverage: int = 1
    client_order_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.upper().replace("/", "").split(":")[0])
        object.__setattr__(self, "quantity", max(0.0, float(self.quantity)))
        object.__setattr__(self, "leverage", max(1, min(125, int(self.leverage))))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata or {})))


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    normalized_intent: ExecutionIntent | None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionResult:
    accepted: bool
    mode: ExecutionMode
    status: OrderStatus
    symbol: str
    client_order_id: str
    exchange_order_id: str = ""
    filled_quantity: float = 0.0
    average_price: float = 0.0
    fee_paid: float = 0.0
    message: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", MappingProxyType(dict(self.raw or {})))


@dataclass(frozen=True)
class CircuitBreakerState:
    blocked: bool
    reasons: tuple[str, ...]
    daily_pnl: float
    consecutive_losses: int
    open_exposure: float
    daily_trades: int
    api_error_rate: float
    market_data_age_seconds: float
