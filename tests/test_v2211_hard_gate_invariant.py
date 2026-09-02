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
        long_trend_score=82.0,
        short_trend_score=8.0,
        long_entry_score=84.0,
        short_entry_score=8.0,
        direction="LONG",
        entry_status=EntryStatus.WAIT,
        priority_status="legacy",
        oi_state="Long build-up",
        phase_summary="TEST / TEST",
        confidence_score=88.0,
        reasons=(),
        trade_plan=SimpleNamespace(rr_to_tp2=2.3),
        structure=SimpleNamespace(),
        regime=SimpleNamespace(
            regime="TREND",
            direction="LONG",
        ),
        alignment=SimpleNamespace(
            label="ĐỒNG PHA LONG",
        ),
        risk=SimpleNamespace(
            liquidation_safe=True,
            risk_score=18.0,
        ),
        smart_entry=SimpleNamespace(
            long_opportunity_index=90.0,
            short_opportunity_index=5.0,
        ),
        action="ĐỨNG NGOÀI",
        timing="legacy",
        generated_at="2026-01-01 00:00:00",
        trend_maturity_score=45.0,
        trend_lifecycle="FIRST_RETEST",
        maturity_gate="CONFIRMED",
        market_bias_gate="PASS",
        direction_confirmation_score=88.0,
        direction_confirmation_gate="CONFIRMED",
    )
    values.update(overrides)
    return CoinAnalysis(**values)


def make_footprint():
    return SimpleNamespace(
        lifecycle_stage="TEST",
        score=95.0,
        raw_score=95.0,
        position_building_score=90.0,
        position_building_regime="LONG_BUILDING",
        confirmation_depth="STRONG",
        direction_alignment="ALIGNED",
        context_multiplier=1.0,
        strong_confirmation=True,
        components=(),
        component_scores={},
        direction="LONG",
    )


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


def test_direction_confirmation_block_stays_wait():
    result = engine().apply_footprint_v31(
        make_analysis(direction_confirmation_gate="BLOCK"),
        make_footprint(),
    )
    assert result.entry_status == EntryStatus.WAIT
    assert "DIRECTION_CONFIRMATION_BLOCK" in result.decision_hard_reasons


def test_mtf_conflict_stays_wait():
    result = engine().apply_footprint_v31(
        make_analysis(
            alignment=SimpleNamespace(label="MÂU THUẪN")
        ),
        make_footprint(),
    )
    assert result.entry_status == EntryStatus.WAIT
    assert "MTF_ALIGNMENT_CONFLICT" in result.decision_hard_reasons


def test_transition_regime_stays_wait():
    result = engine().apply_footprint_v31(
        make_analysis(
            regime=SimpleNamespace(
                regime="TRANSITION",
                direction="NEUTRAL",
            )
        ),
        make_footprint(),
    )
    assert result.entry_status == EntryStatus.WAIT
    assert "REGIME_TRANSITION" in result.decision_hard_reasons


def test_exhaustion_stays_wait():
    result = engine().apply_footprint_v31(
        make_analysis(maturity_gate="EXHAUSTION"),
        make_footprint(),
    )
    assert result.entry_status == EntryStatus.WAIT
    assert "MATURITY_EXHAUSTION" in result.decision_hard_reasons


def test_running_extension_stays_wait():
    result = engine().apply_footprint_v31(
        make_analysis(entry_status=EntryStatus.RUNNING),
        make_footprint(),
    )
    assert result.entry_status == EntryStatus.WAIT
    assert "TREND_ALREADY_RUNNING_EXTENDED" in result.decision_hard_reasons


def test_late_only_caps_ready_to_setup():
    result = engine().apply_footprint_v31(
        make_analysis(
            maturity_gate="LATE",
            entry_status=EntryStatus.READY,
        ),
        make_footprint(),
    )
    assert result.entry_status == EntryStatus.SETUP
    assert result.footprint_gate == "TREND_MATURITY_LATE_CAP"


def test_healthy_signal_can_still_reach_ready():
    result = engine().apply_footprint_v31(
        make_analysis(),
        make_footprint(),
    )
    assert result.entry_status == EntryStatus.READY
    assert result.decision_hard_reasons == ()
