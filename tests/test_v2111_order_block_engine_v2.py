from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from dvs_ai.engines.microstructure import (
    LifecycleStage,
    OrderBlockDirection,
    OrderBlockEngine,
    OrderBlockState,
)


def make_frame(
    n: int = 90,
    trend: float = 0.02,
) -> pd.DataFrame:
    close = 100 + np.arange(n)*trend
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + 0.25
    low = np.minimum(open_, close) - 0.25
    volume = np.full(n, 100.0)
    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def bullish_ob_frame() -> pd.DataFrame:
    data = make_frame(90, trend=0.0)
    index = 55
    data.loc[index, ["open", "close", "high", "low", "volume"]] = [
        100.4, 99.8, 100.6, 99.6, 180.0
    ]
    for offset, close in enumerate([101.0, 102.0, 103.0, 103.5], start=1):
        row = index+offset
        data.loc[row, "open"] = close-0.5
        data.loc[row, "close"] = close
        data.loc[row, "high"] = close+0.3
        data.loc[row, "low"] = close-0.7
        data.loc[row, "volume"] = 170.0
    for row in range(index+5, len(data)):
        base = 103.2 + (row-index-5)*0.02
        data.loc[row, ["open", "close", "high", "low"]] = [
            base, base+0.05, base+0.25, base-0.2
        ]
    return data


def bearish_ob_frame() -> pd.DataFrame:
    data = make_frame(90, trend=0.0)
    index = 55
    data.loc[index, ["open", "close", "high", "low", "volume"]] = [
        99.6, 100.3, 100.6, 99.4, 180.0
    ]
    for offset, close in enumerate([99.0, 98.0, 97.0, 96.5], start=1):
        row = index+offset
        data.loc[row, "open"] = close+0.5
        data.loc[row, "close"] = close
        data.loc[row, "high"] = close+0.7
        data.loc[row, "low"] = close-0.3
        data.loc[row, "volume"] = 170.0
    for row in range(index+5, len(data)):
        base = 96.8 - (row-index-5)*0.02
        data.loc[row, ["open", "close", "high", "low"]] = [
            base, base-0.05, base+0.2, base-0.25
        ]
    return data


def test_bullish_order_block_detected():
    out = OrderBlockEngine().analyze(
        bullish_ob_frame(),
        {"lifecycle_stage": LifecycleStage.SPRING},
    )
    assert out.metadata["implemented"] is True
    assert out.metadata["selected_direction"] == "BULLISH"
    assert "ORDER_BLOCK_BULLISH" in out.evidence
    assert out.phase_quality > 50


def test_bearish_order_block_detected():
    out = OrderBlockEngine().analyze(
        bearish_ob_frame(),
        {"lifecycle_stage": LifecycleStage.UPTHRUST},
    )
    assert out.metadata["selected_direction"] == "BEARISH"
    assert "ORDER_BLOCK_BEARISH" in out.evidence


def test_mitigation_changes_state():
    data = bullish_ob_frame()
    # Touch the bullish zone after displacement, then reject higher.
    data.loc[80, ["open", "close", "high", "low"]] = [
        101.0, 101.4, 102.0, 99.7
    ]
    data.loc[81, ["open", "close", "high", "low"]] = [
        101.4, 103.0, 103.3, 101.2
    ]
    out = OrderBlockEngine().analyze(
        data,
        {"lifecycle_stage": "SPRING"},
    )
    assert out.metadata["selected_state"] in (
        OrderBlockState.MITIGATED.value,
        OrderBlockState.FRESH.value,
    )
    assert out.metadata["mitigation_score"] >= 0


def test_invalidated_block_is_penalized():
    data = bullish_ob_frame()
    data.loc[80:, "close"] = 98.5
    data.loc[80:, "open"] = 99.0
    data.loc[80:, "high"] = 99.2
    data.loc[80:, "low"] = 98.2
    out = OrderBlockEngine().analyze(
        data,
        {"lifecycle_stage": LifecycleStage.SPRING},
    )
    assert out.metadata["invalidated"] is True
    assert "ORDER_BLOCK_INVALIDATED" in out.evidence
    assert out.phase_quality < 70


def test_lifecycle_context_is_recorded():
    out = OrderBlockEngine().analyze(
        bullish_ob_frame(),
        {"lifecycle_stage": LifecycleStage.SPRING},
    )
    assert out.metadata["lifecycle_stage"] == "Spring"
    assert any("Lifecycle context" in item for item in out.explanation)


def test_short_history_returns_safe_evidence():
    out = OrderBlockEngine().analyze(
        make_frame(40),
        {},
    )
    assert out.score == 25.0
    assert "INSUFFICIENT_ORDER_BLOCK_HISTORY" in out.evidence


def test_metadata_is_immutable():
    out = OrderBlockEngine().analyze(
        bullish_ob_frame(),
        {},
    )
    with pytest.raises(TypeError):
        out.metadata["new"] = 1
