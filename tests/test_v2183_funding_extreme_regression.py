from __future__ import annotations

import pandas as pd
import pytest

from dvs_ai.engines.microstructure.position_building_engine import (
    PositionBuildingEngine,
)


def _analyze(
    funding_pct: float,
    *,
    oi: float = 0.0,
    price_change: float = 0.0,
    lifecycle: str = "ACCUMULATION",
):
    df = pd.DataFrame({
        "open": [100.0],
        "high": [100.0],
        "low": [100.0],
        "close": [100.0],
        "volume": [1000.0],
    })
    return PositionBuildingEngine().analyze(
        df,
        {
            "oi_change_15m_pct": oi,
            "funding_pct": funding_pct,
            "price_change_pct": price_change,
            "delta_ratio": 0.0,
            "cvd_slope": 0.0,
            "liquidation_impulse": 0.0,
            "absorption_score": 0.0,
            "lifecycle_stage": lifecycle,
        },
    )


def test_moderate_funding_does_not_trigger_crowding():
    evidence = _analyze(0.10)
    score = evidence.metadata["funding_extreme_score"]

    assert score == pytest.approx(10.8)
    assert score < 60.0
    assert evidence.metadata["funding_crowding_risk"] is False
    assert "FUNDING_CROWDING_RISK" not in evidence.evidence


def test_extreme_funding_triggers_crowding():
    evidence = _analyze(0.60)
    score = evidence.metadata["funding_extreme_score"]

    assert score == pytest.approx(70.8)
    assert evidence.metadata["funding_crowding_risk"] is True
    assert "FUNDING_CROWDING_RISK" in evidence.evidence
    assert evidence.metadata["funding_crowding_penalty"] == -10.0


def test_funding_extreme_retains_resolution():
    high = _analyze(0.30).metadata["funding_extreme_score"]
    euphoric = _analyze(1.00).metadata["funding_extreme_score"]

    assert high == pytest.approx(34.8)
    assert euphoric == pytest.approx(100.0)
    assert 0.0 < high < euphoric


def test_funding_extreme_is_symmetric():
    positive = _analyze(0.30).metadata["funding_extreme_score"]
    negative = _analyze(-0.30).metadata["funding_extreme_score"]
    assert positive == pytest.approx(negative)


def test_funding_extreme_is_monotonic():
    levels = [0.01, 0.08, 0.10, 0.30, 0.60, 1.00]
    scores = [
        _analyze(level).metadata["funding_extreme_score"]
        for level in levels
    ]
    assert scores == sorted(scores)


def test_contrarian_bonus_and_crowding_penalty_can_coexist():
    evidence = _analyze(
        0.60,
        oi=1.0,
        price_change=-0.5,
        lifecycle="UPTHRUST",
    )

    assert evidence.metadata["regime"] == "SHORT_BUILDING"
    assert evidence.metadata["funding_contrarian_bonus"] == 16.0
    assert evidence.metadata["funding_crowding_penalty"] == -10.0
    assert "POSITIVE_FUNDING_BEARISH_CONTEXT" in evidence.evidence
    assert "FUNDING_CROWDING_RISK" in evidence.evidence


def test_public_helper_matches_metadata():
    expected = PositionBuildingEngine.funding_extreme_score(0.30)
    observed = _analyze(0.30).metadata["funding_extreme_score"]
    assert observed == pytest.approx(expected)
