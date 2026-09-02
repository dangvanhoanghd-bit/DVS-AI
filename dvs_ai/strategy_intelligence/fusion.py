from __future__ import annotations

from .models import FusedSignal, MarketRegime, SignalDirection, StrategySignal
from .scores import StrategyScoreRegistry


class SignalFusionEngine:
    def __init__(
        self,
        score_registry: StrategyScoreRegistry | None = None,
        minimum_confidence: float = 0.55,
        minimum_margin: float = 0.10,
    ) -> None:
        if not 0 <= minimum_confidence <= 1 or not 0 <= minimum_margin <= 1:
            raise ValueError("thresholds must be between 0 and 1")
        self.scores = score_registry or StrategyScoreRegistry()
        self.minimum_confidence = minimum_confidence
        self.minimum_margin = minimum_margin

    def fuse(
        self,
        signals: tuple[StrategySignal, ...],
        regime: MarketRegime,
        supported_regimes: dict[str, frozenset[MarketRegime]] | None = None,
    ) -> FusedSignal:
        long_score = short_score = total_weight = 0.0
        contributors: list[str] = []
        reasons: list[str] = []
        for signal in signals:
            supported = (supported_regimes or {}).get(signal.strategy_id)
            if supported is not None and regime not in supported and MarketRegime.UNKNOWN not in supported:
                reasons.append(f"STRATEGY_REGIME_MISMATCH:{signal.strategy_id}")
                continue
            weight = self.scores.weight(signal.strategy_id)
            weighted = weight * signal.confidence
            total_weight += weight
            contributors.append(signal.strategy_id)
            reasons.extend(signal.reason_codes)
            if signal.direction is SignalDirection.LONG:
                long_score += weighted
            elif signal.direction is SignalDirection.SHORT:
                short_score += weighted

        if total_weight <= 0:
            return FusedSignal(SignalDirection.NEUTRAL, 0.0, regime, (), tuple(dict.fromkeys(reasons + ["FUSION_NO_ELIGIBLE_SIGNAL"])), 0.0, 0.0)

        long_norm = long_score / total_weight
        short_norm = short_score / total_weight
        confidence = max(long_norm, short_norm)
        margin = abs(long_norm - short_norm)
        if confidence < self.minimum_confidence or margin < self.minimum_margin:
            direction = SignalDirection.NEUTRAL
            reasons.append("FUSION_CONSENSUS_INSUFFICIENT")
        else:
            direction = SignalDirection.LONG if long_norm > short_norm else SignalDirection.SHORT
            reasons.append("FUSION_CONSENSUS_CONFIRMED")
        return FusedSignal(
            direction=direction,
            confidence=confidence,
            regime=regime,
            contributors=tuple(contributors),
            reason_codes=tuple(dict.fromkeys(reasons)),
            long_score=long_norm,
            short_score=short_norm,
        )
