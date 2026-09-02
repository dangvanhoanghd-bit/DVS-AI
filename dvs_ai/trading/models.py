from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

class PositionSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"

class OrderStatus(str, Enum):
    FILLED = "FILLED"
    REJECTED = "REJECTED"

@dataclass(frozen=True, slots=True)
class PaperOrder:
    order_id: str
    decision_id: str
    symbol: str
    side: PositionSide
    quantity: float
    fill_price: float
    fee: float
    status: OrderStatus
    reason_codes: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

@dataclass(frozen=True, slots=True)
class ClosedTrade:
    trade_id: str
    symbol: str
    side: PositionSide
    quantity: float
    entry_price: float
    exit_price: float
    gross_pnl: float
    fees: float
    net_pnl: float
    opened_at: datetime
    closed_at: datetime
    decision_id: str

@dataclass(slots=True)
class Position:
    symbol: str
    side: PositionSide
    quantity: float
    entry_price: float
    opened_at: datetime
    decision_id: str
    entry_fee: float = 0.0

    def unrealized_pnl(self, mark_price: float) -> float:
        direction = 1.0 if self.side is PositionSide.LONG else -1.0
        return (float(mark_price) - self.entry_price) * self.quantity * direction
