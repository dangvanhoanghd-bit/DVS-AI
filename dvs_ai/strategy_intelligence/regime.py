from __future__ import annotations

from dataclasses import dataclass

from .models import MarketRegime, MarketSnapshot


@dataclass(frozen=True, slots=True)
class RegimeThresholds:
    trend_strength: float = 0.6
    high_volatility: float = 0.035
    low_volatility: float = 0.008


class MarketRegimeDetector:
    """Deterministic, feature-driven detector. Missing inputs fail to UNKNOWN."""

    def __init__(self, thresholds: RegimeThresholds | None = None) -> None:
        self.thresholds = thresholds or RegimeThresholds()

    def detect(self, snapshot: MarketSnapshot) -> MarketRegime:
        f = snapshot.features
        trend = f.get("trend_strength")
        slope = f.get("trend_slope")
        volatility = f.get("volatility")
        if trend is None or slope is None or volatility is None:
            return MarketRegime.UNKNOWN
        if volatility >= self.thresholds.high_volatility:
            return MarketRegime.HIGH_VOLATILITY
        if volatility <= self.thresholds.low_volatility and abs(slope) < 0.1:
            return MarketRegime.LOW_VOLATILITY
        if trend >= self.thresholds.trend_strength:
            if slope > 0:
                return MarketRegime.TREND_UP
            if slope < 0:
                return MarketRegime.TREND_DOWN
        return MarketRegime.RANGE
