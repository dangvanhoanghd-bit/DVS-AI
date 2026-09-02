from dataclasses import replace
from types import SimpleNamespace

from dvs_ai.engines.composite_exhaustion_engine import CompositeExhaustionEngine


def _analysis(**overrides):
    tf15 = SimpleNamespace(cmf=-0.25, rsi=25.0, adx=45.0, spring=False, wyckoff_test_long=False)
    tf1h = SimpleNamespace(cmf=-0.30)
    base = SimpleNamespace(
        symbol="HOME/USDT:USDT",
        snapshot=SimpleNamespace(change_24h_pct=-40.0, oi_change_15m_pct=0.4, oi_change_1h_pct=1.0, funding_pct=-1.5),
        timeframes={"15m": tf15, "1h": tf1h},
        short_trend_score=91.0,
        microstructure=SimpleNamespace(absorption_score=15.0, bid_wall_effective_score=5.0, ofi_score=-30.0, book_imbalance=-0.2, exhaustion_score=20.0),
        smart_entry=SimpleNamespace(absorption_score=15.0, panic_flush_score=10.0),
        structure=SimpleNamespace(wyckoff_test="NONE"),
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_strong_sell_without_confirmation_cannot_claim_bottom():
    result = CompositeExhaustionEngine().evaluate(_analysis())
    assert result.state in {"SELLING", "SELLING_EXHAUSTING"}
    assert result.bottom_formation_probability <= 29.0
    assert result.bottom_state == "BOTTOM_NOT_CONFIRMED"
    assert result.observe_only is True


def test_confirmation_and_absorption_can_raise_watch_not_entry():
    a = _analysis()
    a.timeframes["15m"] = SimpleNamespace(cmf=0.03, rsi=39.0, adx=28.0, spring=True, wyckoff_test_long=True)
    a.microstructure = SimpleNamespace(absorption_score=78.0, bid_wall_effective_score=72.0, ofi_score=55.0, book_imbalance=0.25, exhaustion_score=75.0)
    a.snapshot = SimpleNamespace(change_24h_pct=-32.0, oi_change_15m_pct=-1.0, oi_change_1h_pct=-0.4, funding_pct=-0.2)
    result = CompositeExhaustionEngine().evaluate(a)
    assert result.bottom_formation_probability >= 45.0
    assert result.bottom_state in {"BOTTOM_FORMATION_WATCH", "BOTTOM_FORMATION_CONFIRMED_FOR_REVIEW"}
    assert result.observe_only is True


def test_timeline_is_symbol_scoped_and_bounded():
    engine = CompositeExhaustionEngine(history_size=4)
    a = _analysis()
    for _ in range(8):
        result = engine.evaluate(a)
    assert len(result.timeline) == 4


def test_source_has_no_execution_dependency():
    import inspect
    import dvs_ai.engines.composite_exhaustion_engine as mod
    source = inspect.getsource(mod)
    for forbidden in ("trade_intent", "order_router", "send_order", "promotion"):
        assert forbidden not in source.lower()
