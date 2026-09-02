from __future__ import annotations

import importlib.util
import sys
from types import SimpleNamespace

try:
    _ccxt_spec = importlib.util.find_spec("ccxt")
except ValueError:
    _ccxt_spec = None
if _ccxt_spec is None:
    sys.path.insert(0, "test_stubs")
sys.path.insert(0, ".")

from dvs_ai.domain.models import CoinAnalysis, EntryStatus
from dvs_ai.engines.decision_engine import DecisionEngine


def make_analysis(**overrides):
    values = dict(
        symbol="TEST/USDT:USDT",
        snapshot=SimpleNamespace(),
        timeframes={},
        long_trend_score=80.0,
        short_trend_score=10.0,
        long_entry_score=80.0,
        short_entry_score=10.0,
        direction="LONG",
        entry_status=EntryStatus.WAIT,
        priority_status="legacy",
        oi_state="OI trung tính",
        phase_summary="TEST / TEST",
        confidence_score=85.0,
        reasons=(),
        trade_plan=SimpleNamespace(rr_to_tp2=2.3),
        structure=SimpleNamespace(),
        regime=SimpleNamespace(),
        alignment=SimpleNamespace(),
        risk=SimpleNamespace(
            liquidation_safe=True,
            risk_score=20.0,
        ),
        smart_entry=SimpleNamespace(
            long_opportunity_index=85.0,
            short_opportunity_index=10.0,
        ),
        action="ĐỨNG NGOÀI",
        timing="legacy",
        generated_at="2026-01-01 00:00:00",
        trend_maturity_score=45.0,
        trend_lifecycle="FIRST_RETEST",
        maturity_gate="CONFIRMED",
        market_bias_gate="PASS",
        direction_confirmation_score=80.0,
        direction_confirmation_gate="CONFIRMED",
    )
    values.update(overrides)
    return CoinAnalysis(**values)


def make_footprint(**overrides):
    values = dict(
        lifecycle_stage="TEST",
        score=90.0,
        raw_score=90.0,
        position_building_score=80.0,
        position_building_regime="LONG_BUILDING",
        confirmation_depth="STRONG",
        direction_alignment="ALIGNED",
        context_multiplier=1.0,
        strong_confirmation=True,
        components=(),
        component_scores={},
        direction="LONG",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class NoopGraph:
    def build(self, staged):
        return SimpleNamespace(
            chain=(),
            chain_text="",
            completeness=0.0,
        )


class NoopReasoning:
    def build(self, staged, final_score):
        return SimpleNamespace(
            headline="",
            supporting_evidence=(),
            conflicting_evidence=(),
            hard_blocks=(),
            market_story=(),
            next_confirmation=(),
            text="",
        )


def engine():
    value = DecisionEngine()
    value.footprint_graph_engine = NoopGraph()
    value.reasoning_engine = NoopReasoning()
    return value


def test_direction_block_cannot_be_resurrected():
    result = engine().apply_footprint_v31(
        make_analysis(direction_confirmation_gate="BLOCK"),
        make_footprint(),
    )
    assert result.entry_status == EntryStatus.WAIT
    assert "DIRECTION_CONFIRMATION_BLOCK" in result.decision_hard_reasons


def test_missing_history_is_excluded():
    result = engine().apply_footprint_v31(
        make_analysis(),
        make_footprint(components=()),
    )
    assert "POSITION_DURABILITY" not in result.decision_quality_components
    assert result.decision_quality_active_weight == 1.0


def test_history_enables_durability():
    component = SimpleNamespace(
        metadata={
            "regime": "LONG_BUILDING",
            "oi_series_samples": 5,
            "persistence_score": 80.0,
            "acceleration_score": 70.0,
            "position_confidence": 90.0,
        }
    )
    result = engine().apply_footprint_v31(
        make_analysis(),
        make_footprint(components=(component,)),
    )
    assert "POSITION_DURABILITY" in result.decision_quality_components
    assert result.decision_quality_active_weight == 1.0  # correlated ORDER_FLOW family is capped


def test_harmonic_confidence_limits_compensation():
    result = engine().apply_footprint_v31(
        make_analysis(confidence_score=90.0),
        make_footprint(score=40.0, strong_confirmation=False),
    )
    assert result.confidence_fusion_method == "HARMONIC_TECHNICAL_QUALITY"
    assert result.confidence_score <= 54.0


def test_action_and_priority_are_recomputed():
    result = engine().apply_footprint_v31(
        make_analysis(),
        make_footprint(),
    )
    assert result.action != "ĐỨNG NGOÀI"
    assert result.priority_status != "legacy"


def test_no_duplicate_lab_upper():
    from pathlib import Path
    source = Path(
        "dvs_ai/services/paper_trade_service.py"
    ).read_text(encoding="utf-8")
    assert "lab = lab.upper()\n        lab = lab.upper()" not in source


def test_version_matches_app_version():
    from dvs_ai import __version__
    from dvs_ai.version import APP_VERSION
    assert __version__ == APP_VERSION


def test_execution_safety_config():
    import json
    from pathlib import Path
    raw = json.loads(Path("config.json").read_text(encoding="utf-8"))
    assert raw["execution_mode"] == "PAPER"
    assert raw["execution_live_enabled"] is False
