from dataclasses import dataclass

import pytest

from dvs_ai.strategy_intelligence import (
    MarketRegime,
    MarketRegimeDetector,
    MarketSnapshot,
    SignalDirection,
    SignalFusionEngine,
    StrategyBacktester,
    StrategyIntelligenceEngine,
    StrategyRegistry,
    StrategyScoreRegistry,
    StrategySignal,
)


def snap(price=100.0, **features):
    return MarketSnapshot("btcusdt", "15m", price, features)


@dataclass
class FixedStrategy:
    strategy_id: str
    direction: SignalDirection
    confidence: float = 0.8
    version: str = "1.0"
    supported_regimes: frozenset[MarketRegime] = frozenset(MarketRegime)

    def evaluate(self, snapshot):
        return StrategySignal(self.strategy_id, self.direction, self.confidence, (f"{self.strategy_id.upper()}_SIGNAL",))


def test_market_snapshot_is_normalized_and_immutable():
    s = snap(100, rsi=55)
    assert s.symbol == "BTCUSDT"
    with pytest.raises(TypeError):
        s.features["rsi"] = 1


def test_regime_detector_is_deterministic_and_fail_closed():
    detector = MarketRegimeDetector()
    assert detector.detect(snap()) is MarketRegime.UNKNOWN
    assert detector.detect(snap(trend_strength=.8, trend_slope=.4, volatility=.02)) is MarketRegime.TREND_UP
    assert detector.detect(snap(trend_strength=.8, trend_slope=-.4, volatility=.02)) is MarketRegime.TREND_DOWN
    assert detector.detect(snap(trend_strength=.2, trend_slope=0, volatility=.05)) is MarketRegime.HIGH_VOLATILITY


def test_strategy_registry_rejects_duplicates():
    r = StrategyRegistry(); r.register(FixedStrategy("alpha", SignalDirection.LONG))
    with pytest.raises(ValueError): r.register(FixedStrategy("alpha", SignalDirection.SHORT))


def test_score_registry_shrinks_small_samples_and_updates_weight():
    scores = StrategyScoreRegistry()
    assert scores.weight("new") == .5
    scores.record("good", .1); scores.record("good", .2); scores.record("good", -.1)
    score = scores.get("good")
    assert score.observations == 3 and score.wins == 2 and score.losses == 1
    assert .5 < score.reliability < 1


def test_fusion_prefers_higher_reliability_strategy():
    scores = StrategyScoreRegistry()
    for _ in range(10): scores.record("long", .01)
    for _ in range(10): scores.record("short", -.01)
    fusion = SignalFusionEngine(scores, minimum_confidence=.3, minimum_margin=.05)
    out = fusion.fuse((StrategySignal("long", SignalDirection.LONG, .8), StrategySignal("short", SignalDirection.SHORT, .8)), MarketRegime.RANGE)
    assert out.direction is SignalDirection.LONG


def test_fusion_neutral_on_conflict():
    out = SignalFusionEngine(minimum_confidence=.4, minimum_margin=.2).fuse(
        (StrategySignal("a", SignalDirection.LONG, .8), StrategySignal("b", SignalDirection.SHORT, .8)), MarketRegime.RANGE
    )
    assert out.direction is SignalDirection.NEUTRAL
    assert "FUSION_CONSENSUS_INSUFFICIENT" in out.reason_codes


def test_fusion_filters_regime_incompatible_strategy():
    fusion = SignalFusionEngine(minimum_confidence=.4, minimum_margin=.05)
    signals = (StrategySignal("trend", SignalDirection.LONG, .9), StrategySignal("range", SignalDirection.SHORT, .9))
    supported = {"trend": frozenset({MarketRegime.TREND_UP}), "range": frozenset({MarketRegime.RANGE})}
    out = fusion.fuse(signals, MarketRegime.TREND_UP, supported)
    assert out.direction is SignalDirection.LONG
    assert any(x.startswith("STRATEGY_REGIME_MISMATCH") for x in out.reason_codes)


def test_intelligence_engine_evaluates_registered_strategies():
    registry = StrategyRegistry(); registry.register(FixedStrategy("a", SignalDirection.LONG)); registry.register(FixedStrategy("b", SignalDirection.LONG))
    out = StrategyIntelligenceEngine(registry).evaluate(snap(trend_strength=.8, trend_slope=.3, volatility=.02))
    assert out.direction is SignalDirection.LONG and set(out.contributors) == {"a", "b"}


def test_backtester_long_and_score_registry():
    strategy = FixedStrategy("long", SignalDirection.LONG)
    prices = [100, 110, 100, 120]
    snapshots = [snap(p) for p in prices]
    scores = StrategyScoreRegistry()
    report = StrategyBacktester(holding_bars=1).run(strategy, snapshots, scores)
    assert len(report.trades) == 3
    assert report.trades[0].return_pct == pytest.approx(.1)
    assert scores.get("long").observations == 3


def test_backtester_short_direction_and_fees():
    strategy = FixedStrategy("short", SignalDirection.SHORT)
    report = StrategyBacktester(holding_bars=1, fee_rate=.001).run(strategy, [snap(100), snap(90)])
    assert report.total_return == pytest.approx(.098)


def test_backtester_validates_inputs():
    with pytest.raises(ValueError): StrategyBacktester(holding_bars=0)
    with pytest.raises(ValueError): StrategyBacktester(fee_rate=-1)


def test_intelligence_engine_contains_strategy_exceptions():
    @dataclass
    class BrokenStrategy:
        strategy_id: str = "broken"
        version: str = "1.0"
        supported_regimes: frozenset[MarketRegime] = frozenset(MarketRegime)
        def evaluate(self, snapshot):
            raise RuntimeError("boom")

    registry = StrategyRegistry(); registry.register(BrokenStrategy())
    out = StrategyIntelligenceEngine(registry).evaluate(snap())
    assert out.direction is SignalDirection.NEUTRAL
    assert any(code.startswith("STRATEGY_EVALUATION_FAILED:broken") for code in out.reason_codes)


def test_strategy_score_json_round_trip(tmp_path):
    from dvs_ai.strategy_intelligence import JsonStrategyScoreStorage
    scores = StrategyScoreRegistry(); scores.record("alpha", .1); scores.record("alpha", -.02)
    storage = JsonStrategyScoreStorage(tmp_path / "scores.json")
    storage.save(scores.snapshot())
    restored = StrategyScoreRegistry(); restored.restore(storage.load())
    assert restored.get("alpha").observations == 2
    assert restored.get("alpha").net_return == pytest.approx(.08)


def test_strategy_decision_bridge_neutral_is_fail_closed():
    from dvs_ai.scientific.contracts import ScientificLifecycleState
    from dvs_ai.scientific.decision import DecisionAdapter, DecisionAction
    from dvs_ai.scientific.ledger import InMemoryLedgerStorage, ScientificLedger
    from dvs_ai.strategy_intelligence import FusedSignal, StrategyDecisionBridge

    ledger = ScientificLedger(InMemoryLedgerStorage())
    run_id = "run-m9-bridge"
    states = [
        ScientificLifecycleState.RAW, ScientificLifecycleState.FEATURED,
        ScientificLifecycleState.EVIDENCE_READY, ScientificLifecycleState.VALIDATED,
        ScientificLifecycleState.CERTIFIED, ScientificLifecycleState.REGISTERED,
        ScientificLifecycleState.AVAILABLE,
    ]
    for before, after in zip(states, states[1:]):
        ledger.append_transition(pipeline_run_id=run_id, stage=f"{before.value}_TO_{after.value}", state_before=before, state_after=after, succeeded=True)
    fused = FusedSignal(SignalDirection.NEUTRAL, .9, MarketRegime.RANGE, (), (), .45, .45)
    decision = StrategyDecisionBridge(DecisionAdapter(ledger)).authorize(
        pipeline_run_id=run_id, snapshot=snap(), fused_signal=fused
    )
    assert not decision.authorized
    assert decision.final_action is DecisionAction.NO_ACTION
    assert "M9_NEUTRAL_SIGNAL" in decision.reason_codes
