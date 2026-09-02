from pathlib import Path
from types import SimpleNamespace
from dvs_ai.domain.models import EntryStatus
from dvs_ai.services.paper_trade_service import PaperTradeService

def cfg():
    return SimpleNamespace(
        opportunity_main_top_n=3,
        opportunity_shadow_top_n=12,
        opportunity_min_score=52.0,
        shadow_opportunity_min_score=28.0,
        shadow_allow_wait_discovery=True,
        shadow_research_confidence=34.0,
        shadow_research_entry=35.0,
        shadow_fatal_micro_only=True,
        main_confidence=68.0, main_entry=62.0,
        main_risk_max=50.0, main_rr_min=1.8,
        shadow_confidence=45.0, shadow_entry=45.0,
        shadow_risk_max=65.0, shadow_rr_min=1.4,
        microstructure_min_cos=48.0,
        microstructure_shadow_min_absorption=18.0,
        microstructure_shadow_min_ofi_edge=6.0,
        microstructure_shadow_min_building=15.0,
    )

def candidate(conflict=False):
    micro = SimpleNamespace(
        composite_operator_score=38.0,
        ofi_score=55.0,
        absorption_score=10.0,
        position_building_score=10.0,
        bid_wall_score=20.0, ask_wall_score=20.0,
        bid_wall_persistence=0.0, ask_wall_persistence=0.0,
        bid_wall_velocity_pct_per_sec=0.0,
        ask_wall_velocity_pct_per_sec=0.0,
        spoofing_probability=0.0,
    )
    return SimpleNamespace(
        direction="LONG", entry_status=EntryStatus.WAIT,
        action="ĐỨNG NGOÀI",
        long_entry_score=42.0, short_entry_score=10.0,
        opportunity_rank=5, opportunity_score=36.0,
        opportunity_gate="LOW_QUALITY",
        microstructure=micro,
        microstructure_gate="CONFLICT" if conflict else "WEAK_CONFIRM",
        trend_lifecycle="FIRST_RETEST",
        maturity_gate="CONFIRMED",
        direction_confirmation_gate="WATCH",
        footprint_gate="BLOCK:FOOTPRINT_TOO_WEAK",
        confidence_score=40.0,
        risk=SimpleNamespace(risk_score=40.0, liquidation_safe=True),
        trade_plan=SimpleNamespace(rr_to_tp2=1.6),
    )

def service(tmp_path):
    return PaperTradeService(
        SimpleNamespace(),
        SimpleNamespace(),
        tmp_path/"paper.db",
        cfg(),
    )

def test_main_stays_strict(tmp_path):
    ok, _ = service(tmp_path).eligibility(candidate(), "LONG", "MAIN")
    assert not ok

def test_shadow_wait_discovery_is_eligible(tmp_path):
    ok, reasons = service(tmp_path).eligibility(candidate(), "LONG", "SHADOW")
    assert ok
    assert "SHADOW_DISCOVERY_CANDIDATE" in reasons

def test_shadow_conflict_is_still_blocked(tmp_path):
    ok, reasons = service(tmp_path).eligibility(
        candidate(conflict=True), "LONG", "SHADOW"
    )
    assert not ok
    assert "MICROSTRUCTURE_CONFLICT" in reasons

def test_market_bias_uses_real_states():
    source = Path("dvs_ai/engines/decision_engine.py").read_text(encoding="utf-8")
    assert '"COUNTERTREND_CONFIRMED": 65.0' in source
    assert '"DOWNGRADE_OPPOSING": 40.0' in source
    assert 'market_bias_gate == "CAUTION"' not in source

def test_safety_defaults():
    import json
    raw = json.loads(Path("config.json").read_text(encoding="utf-8"))
    assert raw["execution_mode"] == "PAPER"
    assert raw["execution_live_enabled"] is False
