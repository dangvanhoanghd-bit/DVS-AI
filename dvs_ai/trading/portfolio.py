from __future__ import annotations
from dataclasses import dataclass, field
from .models import ClosedTrade, Position

@dataclass(slots=True)
class PaperPortfolio:
    starting_balance: float = 10_000.0
    cash_balance: float = field(init=False)
    positions: dict[str, Position] = field(default_factory=dict)
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    peak_equity: float = field(init=False)

    def __post_init__(self) -> None:
        if self.starting_balance <= 0:
            raise ValueError("starting_balance must be positive")
        self.cash_balance = float(self.starting_balance)
        self.peak_equity = float(self.starting_balance)

    @property
    def realized_pnl(self) -> float:
        return sum(t.net_pnl for t in self.closed_trades)

    def equity(self, marks: dict[str, float] | None = None) -> float:
        marks = marks or {}
        unrealized = sum(p.unrealized_pnl(marks.get(symbol, p.entry_price)) for symbol, p in self.positions.items())
        value = self.cash_balance + unrealized
        self.peak_equity = max(self.peak_equity, value)
        return value

    def drawdown(self, marks: dict[str, float] | None = None) -> float:
        equity = self.equity(marks)
        return 0.0 if self.peak_equity <= 0 else max(0.0, (self.peak_equity - equity) / self.peak_equity)
