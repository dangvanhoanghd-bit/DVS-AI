from __future__ import annotations

import numpy as np
import pandas as pd

from dvs_ai.engines.microstructure import (
    BosChochEngine,
    FVGEngine,
    FootprintOrchestrator,
    LiquiditySweepEngine,
)


def frame(n=90):
    close = np.full(n, 100.0)
    open_ = close.copy()
    high = close + 0.4
    low = close - 0.4
    volume = np.full(n, 100.0)
    return pd.DataFrame({
        "open": open_, "high": high, "low": low,
        "close": close, "volume": volume
    })


def test_bullish_fvg_detected():
    df = frame()
    i = 60
    df.loc[i-2, ["high","low","open","close"]] = [100.0, 99.5, 99.7, 99.8]
    df.loc[i-1, ["high","low","open","close","volume"]] = [102.0, 100.2, 100.3, 101.8, 180]
    df.loc[i, ["high","low","open","close"]] = [102.4, 101.0, 101.2, 102.0]
    out = FVGEngine().analyze(df, {})
    assert out.metadata["implemented"] is True
    assert any(
        gap.direction.value == "BULLISH"
        for gap in out.metadata["all_gaps"]
    )


def test_bullish_bos_detected():
    df = frame()
    df.loc[69:88, "high"] = 101.0
    df.loc[69:88, "low"] = 99.0
    df.loc[89, ["open","close","high","low","volume"]] = [100.5, 102.0, 102.3, 100.4, 180]
    out = BosChochEngine().analyze(df, {})
    assert out.metadata["event"] in ("BULLISH_BOS", "BULLISH_CHOCH")


def test_liquidity_sweep_low():
    df = frame()
    df.loc[69:88, "low"] = 99.0
    df.loc[89, ["open","close","high","low","volume"]] = [99.5, 99.4, 100.0, 98.2, 160]
    out = LiquiditySweepEngine().analyze(df, {})
    assert "LIQUIDITY_SWEEP_LOW" in out.evidence


def test_composite_is_evidence_only_and_bounded():
    df = frame()
    result = FootprintOrchestrator().analyze(df, {})
    comp = result["composite"]
    assert 0 <= comp.score <= 100
    assert comp.direction in ("LONG", "SHORT", "NEUTRAL")
    assert hasattr(comp, "strong_confirmation")


def test_decision_engine_uses_evidence_without_orchestrator_dependency():
    source = open("dvs_ai/engines/decision_engine.py", encoding="utf-8").read()
    assert "FootprintOrchestrator" not in source
    assert "apply_footprint_v31" in source
    assert "strong_confirmation" in source
