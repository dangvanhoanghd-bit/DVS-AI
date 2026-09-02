from dataclasses import replace

from dvs_ai.services.order_flow_data_quality_gate import OrderFlowDataQualityGate
from dvs_ai.services.order_flow_store import OrderFlowSnapshot


def snap(*, quality="REALTIME", newest=100.0, trades=8, liqs=2):
    return OrderFlowSnapshot(
        symbol="BTCUSDT", window_seconds=300,
        buy_notional=1000.0, sell_notional=800.0, delta_usd=200.0,
        cumulative_cvd_usd=200.0, cvd_slope_usd_per_sec=2.0,
        long_liquidation_usd=100.0, short_liquidation_usd=50.0,
        liquidation_events=(), trade_events=trades,
        liquidation_event_count=liqs, newest_event_ts=newest,
        data_quality=quality,
    )


def test_full_realtime_quality_allows_confirmation():
    gate = OrderFlowDataQualityGate(clock=lambda: 110.0)
    out = gate.assess(
        snap(),
        collector_diagnostics={"state": "CONNECTED", "running": True},
        liquidation_data_available=True,
    )
    assert out.state == "FULL"
    assert out.confidence_multiplier == 1.0
    assert out.allow_directional_confirmation is True
    assert out.allow_cvd is True
    assert out.allow_liquidation is True


def test_stale_data_is_blocked_not_merely_penalized():
    gate = OrderFlowDataQualityGate(stale_after_seconds=20, clock=lambda: 130.0)
    out = gate.assess(snap(newest=100.0), liquidation_data_available=True)
    assert out.state == "BLOCKED"
    assert out.confidence_multiplier == 0.0
    assert out.allow_cvd is False
    assert out.allow_liquidation is False
    assert "STALE_ORDER_FLOW" in out.reasons


def test_unresolved_gap_cannot_receive_confirmation_bonus():
    gate = OrderFlowDataQualityGate(clock=lambda: 110.0)
    out = gate.assess(
        snap(),
        collector_diagnostics={
            "state": "CONNECTED", "running": True, "gaps_unresolved": 1
        },
        liquidation_data_available=True,
    )
    assert out.state == "DEGRADED"
    assert out.confidence_multiplier < 1.0
    assert out.allow_directional_confirmation is False
    assert "UNRESOLVED_AGGTRADE_GAP" in out.reasons


def test_liquidation_gap_disables_only_liquidation_when_trade_flow_is_healthy():
    gate = OrderFlowDataQualityGate(clock=lambda: 110.0)
    out = gate.assess(
        snap(),
        collector_diagnostics={
            "state": "CONNECTED", "running": True,
            "liquidation_gap_warnings": 1,
        },
        liquidation_data_available=True,
    )
    assert out.state == "FULL"
    assert out.allow_cvd is True
    assert out.allow_liquidation is False
    assert "LIQUIDATION_GAP_INCOMPLETE" in out.reasons


def test_bootstrap_is_degraded_and_never_directional_confirmation():
    gate = OrderFlowDataQualityGate(clock=lambda: 110.0)
    out = gate.assess(
        snap(quality="BOOTSTRAP"),
        liquidation_data_available=False,
    )
    assert out.state == "DEGRADED"
    assert out.confidence_multiplier == 0.40
    assert out.allow_directional_confirmation is False
    assert out.allow_liquidation is False
