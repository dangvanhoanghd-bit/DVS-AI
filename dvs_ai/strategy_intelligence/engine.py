from __future__ import annotations

from .fusion import SignalFusionEngine
from .models import FusedSignal, MarketSnapshot, StrategySignal, SignalDirection
from .regime import MarketRegimeDetector
from .sdk import StrategyRegistry


class StrategyIntelligenceEngine:
    def __init__(self, registry: StrategyRegistry, detector: MarketRegimeDetector | None = None, fusion: SignalFusionEngine | None = None) -> None:
        self.registry = registry
        self.detector = detector or MarketRegimeDetector()
        self.fusion = fusion or SignalFusionEngine()

    def evaluate(self, snapshot: MarketSnapshot) -> FusedSignal:
        regime = self.detector.detect(snapshot)
        strategies = self.registry.all()
        signals_list: list[StrategySignal] = []
        for strategy in strategies:
            try:
                signal = strategy.evaluate(snapshot)
                if signal.strategy_id != strategy.strategy_id:
                    raise ValueError("strategy returned a mismatched strategy_id")
                signals_list.append(signal)
            except Exception as exc:
                signals_list.append(StrategySignal(
                    strategy_id=strategy.strategy_id,
                    direction=SignalDirection.NEUTRAL,
                    confidence=0.0,
                    reason_codes=(f"STRATEGY_EVALUATION_FAILED:{strategy.strategy_id}:{type(exc).__name__}",),
                ))
        signals = tuple(signals_list)
        supported = {s.strategy_id: s.supported_regimes for s in strategies}
        return self.fusion.fuse(signals, regime, supported)
