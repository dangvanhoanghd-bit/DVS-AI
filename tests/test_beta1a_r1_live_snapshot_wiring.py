from dataclasses import dataclass
from types import SimpleNamespace

from dvs_ai.services.live_episode_capture import LiveEpisodeCapture


class FakeEpisodes:
    def __init__(self):
        self.item = None

    def capture(self, item):
        self.item = item
        return "episode-1", "candidate-1"


class FakeStore:
    def record_diagnostic_trace(self, **kwargs):
        self.trace = kwargs


def test_live_capture_passes_full_trace_as_feature_snapshot():
    capture = object.__new__(LiveEpisodeCapture)
    capture.store = FakeStore()
    capture.episodes = FakeEpisodes()
    capture.decision_hash = "d" * 64

    tf15 = SimpleNamespace(support=100.0, resistance=110.0, atr=2.0, spring=False, upthrust=True)
    risk = SimpleNamespace(risk_score=20.0, risk_level="LOW")
    smart = SimpleNamespace(smart_money_probability=0.7, state="WATCH")
    @dataclass
    class Plan:
        entry_low: float
        entry_high: float
        invalidation: float
        tp1: float
        tp2: float

    plan = Plan(entry_low=101.0, entry_high=102.0, invalidation=98.0, tp1=105.0, tp2=108.0)
    a = SimpleNamespace(
        symbol="BTC/USDT", direction="LONG", generated_at="2026-07-23 00:00:00",
        long_entry_score=70.0, short_entry_score=20.0, long_trend_score=80.0, short_trend_score=10.0,
        decision_hard_reasons=(), reasoning_hard_blocks=(),
        entry_status=SimpleNamespace(value="WAIT"), risk=risk,
        direction_confirmation_gate="WATCH", microstructure_gate="PASS",
        confidence_score=65.0, opportunity_score=60.0,
        smart_entry=smart, regime=SimpleNamespace(regime="TREND"), trend_lifecycle="FORMING",
        phase_summary="ACCUMULATION", opportunity_gate="WATCH", market_bias_gate="PASS",
        direction_confirmation_score=55.0, timeframes={"15m": tf15}, trade_plan=plan,
    )

    capture.capture(a)

    snapshot = capture.episodes.item.feature_snapshot
    assert snapshot is not None
    assert snapshot["symbol"] == "BTC/USDT"
    assert snapshot["scores"]["confidence"] == 65.0
    assert snapshot["structure"]["upthrust"] is True
    assert snapshot["trade_plan"]["entry_low"] == 101.0
    assert capture.store.trace["trace"] == snapshot
