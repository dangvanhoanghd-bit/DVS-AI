from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
import time

import pandas as pd
import pytest

from dvs_ai.domain.models import MicrostructureSnapshot
from dvs_ai.engines.microstructure.position_building_engine import PositionBuildingEngine
from dvs_ai.services.microstructure_service import MicrostructureService
from dvs_ai.services.order_flow_store import PersistentOrderFlowStore


def frame():
    return pd.DataFrame({
        "open": [100.0], "high": [101.0], "low": [99.0],
        "close": [100.0], "volume": [1000.0],
    })


def test_invalid_history_sample_breaks_persistence_instead_of_joining_runs():
    series = PositionBuildingEngine._series([0.4, 0.5, float("nan"), 0.6, 0.7])
    assert series == pytest.approx((0.4, 0.5, 0.0, 0.6, 0.7))
    score = PositionBuildingEngine.persistence_score(series, "LONG_BUILDING")
    assert score < 100.0


def test_untrusted_orderflow_inputs_are_clamped_before_scoring():
    out = PositionBuildingEngine().analyze(frame(), {
        "oi_change_15m_pct": 0.5,
        "price_change_pct": 0.4,
        "funding_pct": 0.0,
        "delta_ratio": 99.0,
        "cvd_slope": -99.0,
        "absorption_score": 999.0,
        "liquidation_impulse": 999.0,
    })
    assert out.metadata["delta_ratio"] == 1.0
    assert out.metadata["cvd_slope"] == -1.0
    assert out.metadata["absorption_score"] == 100.0
    assert out.metadata["liquidation_impulse"] == 100.0
    assert out.metadata["input_normalization"] == "FAIL_SAFE_V3"


def _micro() -> MicrostructureSnapshot:
    return MicrostructureSnapshot(
        symbol="TEST/USDT:USDT", generated_at="2026-07-16 00:00:00",
        data_quality="GOOD", bid_depth_usd=1, ask_depth_usd=1,
        book_imbalance=0.0, aggressive_buy_usd=750.0,
        aggressive_sell_usd=250.0, trade_delta_usd=500.0,
        cvd_proxy_usd=500.0, ofi_score=75.0, absorption_score=62.0,
        exhaustion_score=0.0, bid_wall_score=0.0, ask_wall_score=0.0,
        spoofing_probability=0.0, long_liquidation_usd=100.0,
        short_liquidation_usd=200.0, liquidation_impulse=30.0,
        position_building_score=60.0, effort_result_score=50.0,
        composite_operator_score=70.0, operator_bias="SMART_MONEY_LONG",
        explanation=(), liquidation_data_available=True,
    )


def test_hydrated_microstructure_produces_real_position_context(tmp_path):
    store = PersistentOrderFlowStore(tmp_path / "flow.sqlite3")
    now_ms = int(time.time() * 1000)
    store.ingest_agg_trades("TESTUSDT", [
        {"a": 1, "T": now_ms - 1000, "p": "100", "q": "5", "m": False},
        {"a": 2, "T": now_ms, "p": "100", "q": "5", "m": False},
        {"a": 3, "T": now_ms, "p": "100", "q": "1", "m": True},
    ], realtime=True)
    service = MicrostructureService(provider=object(), order_flow_store=store)
    service._oi_history["TEST/USDT:USDT"].extend((0.1, 0.2, 0.4))
    service._delta_history["TEST/USDT:USDT"].extend((0.1, 0.25, 0.5))
    analysis = SimpleNamespace(symbol="TEST/USDT:USDT", microstructure=_micro())
    context = service.position_context(analysis)
    assert context["order_flow_quality_gate"] == "FULL"
    assert context["delta_ratio"] == pytest.approx(0.5)
    assert context["cvd_slope"] > 0.0
    assert context["liquidation_impulse"] == pytest.approx(30.0)
    assert context["absorption_score"] == pytest.approx(62.0)
    assert context["oi_change_series"] == pytest.approx((0.1, 0.2, 0.4))
    assert context["liquidation_data_available"] is True


def test_finalization_refreshes_position_footprint_before_adjustment():
    source = Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")
    hydrate = source.index("ranked = self.service.hydrate_microstructure(")
    refresh = source.index("ranked = self.service.refresh_position_footprint(ranked)")
    adjust = source.index("ranked = self.service.apply_microstructure_adjustments(")
    assert hydrate < refresh < adjust


def test_iceberg_and_queue_imbalance_are_not_falsely_claimed():
    source = Path(
        "dvs_ai/engines/microstructure/position_building_engine.py"
    ).read_text(encoding="utf-8").lower()
    assert "iceberg" not in source
    assert "queue_imbalance" not in source
