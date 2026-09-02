from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dvs_ai.domain.models import EntryStatus
from dvs_ai.engines.microstructure import FootprintOrchestrator
from dvs_ai.execution import (
    AutoPaperExecutionService,
    ExecutionAudit,
    ExecutionMode,
    ExecutionService,
    RiskBasedPositionSizer,
    TradeIntentBuilder,
)


def frame():
    close = np.linspace(100, 101, 90)
    return pd.DataFrame({
        "open": close-0.1,
        "high": close+0.3,
        "low": close-0.3,
        "close": close,
        "volume": np.full(90, 100.0),
    })


def test_position_building_long_context():
    out = FootprintOrchestrator().analyze(
        frame(),
        {
            "oi_change_15m_pct": 1.2,
            "funding_pct": -0.02,
            "price_change_pct": 0.6,
            "delta_ratio": 0.25,
            "cvd_slope": 0.20,
            "liquidation_impulse": 20,
            "wyckoff_signal": "Spring",
        },
        expected_direction="LONG",
    )
    pb = out["position_building"]
    assert pb.metadata["implemented"] is True
    assert pb.metadata["direction"] == "LONG"
    assert pb.phase_quality > 45


def test_position_sizer_does_not_raise_risk_with_leverage():
    sizer = RiskBasedPositionSizer()
    out = sizer.size(
        equity=10000,
        risk_per_trade_pct=0.5,
        entry_price=100,
        invalidation=98,
        footprint_quality=80,
        rr=2.0,
        max_notional=10000,
    )
    assert out.valid
    assert out.risk_amount <= 50.0


def test_auto_paper_rejects_non_paper(tmp_path):
    audit = ExecutionAudit(tmp_path/"audit.db")
    service = ExecutionService(
        mode=ExecutionMode.TESTNET,
        audit=audit,
    )
    with pytest.raises(ValueError):
        AutoPaperExecutionService(service)


def test_auto_paper_disabled_by_default():
    import json
    raw = json.loads(Path("config.json").read_text(encoding="utf-8"))
    assert raw["auto_paper_execution_enabled"] is False


def test_decision_contains_position_building_gate():
    source = Path("dvs_ai/engines/decision_engine.py").read_text(encoding="utf-8")
    assert "POSITION_BUILDING_TOO_WEAK" in source
    assert "apply_footprint_v31" in source
