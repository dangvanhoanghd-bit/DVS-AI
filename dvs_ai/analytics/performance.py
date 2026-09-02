from __future__ import annotations
from dataclasses import dataclass
from math import sqrt
from statistics import mean, pstdev
from dvs_ai.trading import ClosedTrade

@dataclass(frozen=True, slots=True)
class PerformanceReport:
    trades: int
    wins: int
    losses: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    profit_factor: float
    expectancy: float
    sharpe_like: float
    net_pnl: float

class PerformanceAnalyzer:
    @staticmethod
    def analyze(trades: list[ClosedTrade] | tuple[ClosedTrade, ...]) -> PerformanceReport:
        pnls = [float(t.net_pnl) for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        pf = float("inf") if gross_profit > 0 and gross_loss == 0 else (gross_profit / gross_loss if gross_loss else 0.0)
        expectancy = mean(pnls) if pnls else 0.0
        sigma = pstdev(pnls) if len(pnls) > 1 else 0.0
        sharpe = (expectancy / sigma * sqrt(len(pnls))) if sigma > 0 else 0.0
        return PerformanceReport(len(pnls), len(wins), len(losses), len(wins)/len(pnls) if pnls else 0.0,
            gross_profit, gross_loss, pf, expectancy, sharpe, sum(pnls))
