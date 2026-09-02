from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from dvs_ai.engines.footprint_graph_engine import FootprintGraphEngine
from dvs_ai.engines.microstructure.position_building_engine import (
    PositionBuildingEngine,
)


def _frame():
    return pd.DataFrame({
        "open": [100.0],
        "high": [100.0],
        "low": [100.0],
        "close": [100.0],
        "volume": [1000.0],
    })


def test_persistence_rewards_consistent_building():
    consistent = PositionBuildingEngine.persistence_score(
        (0.2, 0.3, 0.4, 0.5, 0.6),
        "LONG_BUILDING",
    )
    noisy = PositionBuildingEngine.persistence_score(
        (0.2, -0.3, 0.4, -0.5, 0.6),
        "LONG_BUILDING",
    )
    assert consistent > noisy
    assert consistent >= 60.0


def test_acceleration_detects_increasing_oi_impulse():
    increasing = PositionBuildingEngine.acceleration_score(
        (0.2, 0.4, 0.8, 1.4, 2.2)
    )
    flat = PositionBuildingEngine.acceleration_score(
        (1.0, 1.0, 1.0, 1.0, 1.0)
    )
    assert increasing > flat


def test_analyze_publishes_persistence_metadata():
    evidence = PositionBuildingEngine().analyze(
        _frame(),
        {
            "oi_change_15m_pct": 1.0,
            "funding_pct": 0.01,
            "price_change_pct": 0.5,
            "delta_ratio": 0.2,
            "cvd_slope": 0.2,
            "liquidation_impulse": 0.0,
            "absorption_score": 60.0,
            "lifecycle_stage": "TEST",
            "oi_change_series": [0.2, 0.4, 0.7, 1.0],
            "delta_ratio_series": [0.1, 0.15, 0.2, 0.25],
        },
    )
    assert evidence.metadata["persistence_score"] > 0.0
    assert evidence.metadata["acceleration_score"] > 0.0
    assert evidence.metadata["position_confidence"] >= 60.0


def test_footprint_graph_builds_ordered_chain():
    analysis = SimpleNamespace(
        direction="LONG",
        trend_lifecycle="TEST",
        position_building_regime="LONG_BUILDING",
        position_building_score=75.0,
        footprint=SimpleNamespace(
            direction="LONG",
            lifecycle_stage="TEST",
            component_scores={
                "liquidity_sweep": 75,
                "order_block": 80,
                "fvg": 70,
                "bos_choch": 78,
                "absorption": 72,
            },
        ),
    )
    graph = FootprintGraphEngine().build(analysis)
    assert len(graph.chain) >= 6
    assert "TEST" in graph.chain_text
    assert "LONG_BUILDING" in graph.chain_text


def test_decision_v4_contains_persistence_gate():
    source = Path("dvs_ai/engines/decision_engine.py").read_text(encoding="utf-8")
    assert "POSITION_PERSISTENCE_TOO_WEAK" in source
    assert "persistence_score" in source
    assert "FootprintGraphEngine" in source


def test_version_matches_app_version():
    from dvs_ai import __version__
    from dvs_ai.version import APP_VERSION
    assert __version__ == APP_VERSION


def test_execution_safety_config():
    import json
    raw = json.loads(Path("config.json").read_text(encoding="utf-8"))
    assert raw.get("auto_paper_execution_enabled", False) is False
    assert raw.get("execution_live_enabled", False) is False
