from __future__ import annotations

from collections.abc import Sequence

from .models import BacktestReport, BacktestTrade, MarketSnapshot, SignalDirection
from .sdk import StrategyPlugin
from .scores import StrategyScoreRegistry


class StrategyBacktester:
    """Single-position, next-bar execution replay with no exchange connectivity."""

    def __init__(self, holding_bars: int = 1, fee_rate: float = 0.0) -> None:
        if holding_bars < 1:
            raise ValueError("holding_bars must be >= 1")
        if fee_rate < 0:
            raise ValueError("fee_rate must be non-negative")
        self.holding_bars = holding_bars
        self.fee_rate = fee_rate

    def run(self, strategy: StrategyPlugin, snapshots: Sequence[MarketSnapshot], scores: StrategyScoreRegistry | None = None) -> BacktestReport:
        trades: list[BacktestTrade] = []
        equity = peak = 1.0
        max_drawdown = 0.0
        last_entry = -self.holding_bars
        for i in range(0, max(0, len(snapshots) - self.holding_bars)):
            if i < last_entry + self.holding_bars:
                continue
            signal = strategy.evaluate(snapshots[i])
            if signal.direction is SignalDirection.NEUTRAL:
                continue
            j = i + self.holding_bars
            entry = snapshots[i].close
            exit_price = snapshots[j].close
            raw = (exit_price - entry) / entry
            if signal.direction is SignalDirection.SHORT:
                raw = -raw
            result = raw - (2.0 * self.fee_rate)
            trade = BacktestTrade(strategy.strategy_id, signal.direction, i, j, entry, exit_price, result)
            trades.append(trade)
            if scores is not None:
                scores.record(strategy.strategy_id, result)
            equity *= 1.0 + result
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, (peak - equity) / peak if peak else 0.0)
            last_entry = i
        wins = sum(t.return_pct > 0 for t in trades)
        return BacktestReport(
            strategy_id=strategy.strategy_id,
            trades=tuple(trades),
            total_return=equity - 1.0,
            win_rate=wins / len(trades) if trades else 0.0,
            max_drawdown=max_drawdown,
        )
