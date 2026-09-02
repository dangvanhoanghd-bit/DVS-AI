from pathlib import Path
from types import SimpleNamespace

from dvs_ai.engines.reasoning_engine import SmartMoneyReasoningEngine


class Status:
    value = "WAIT"


def sample():
    return SimpleNamespace(
        symbol="BTC/USDT",
        direction="LONG",
        entry_status=Status(),
        footprint_score=45.0,
        position_building_score=20.0,
        footprint_direction_alignment="CONFLICT",
        footprint_confirmation_depth="WEAK",
        footprint_gate=(
            "BLOCK:FOOTPRINT_TOO_WEAK|"
            "FOOTPRINT_DIRECTION_CONFLICT|"
            "POSITION_BUILDING_TOO_WEAK"
        ),
        footprint=SimpleNamespace(
            lifecycle_stage="TEST",
            component_scores={
                "order_block": 70,
                "fvg": 40,
                "bos_choch": 35,
                "liquidity_sweep": 30,
                "absorption": 55,
            },
        ),
        oi_state="OI trung tính",
        position_building_regime="NEUTRAL",
        snapshot=SimpleNamespace(funding_pct=0.01),
        trend_lifecycle="TEST",
    )


def test_reasoning_separates_blocks_and_story():
    result = SmartMoneyReasoningEngine().build(
        sample(),
        final_score=42.0,
    )
    assert len(result.hard_blocks) == 3
    assert result.market_story
    assert "HARD GATE CHẶN LỆNH" in result.text
    assert "CÂU CHUYỆN SMART MONEY" in result.text


def test_reasoning_does_not_mutate_decision():
    analysis = sample()
    before = analysis.entry_status.value
    SmartMoneyReasoningEngine().build(analysis, final_score=42)
    assert analysis.entry_status.value == before


def test_decision_engine_integrates_reasoning():
    source = Path("dvs_ai/engines/decision_engine.py").read_text(encoding="utf-8")
    assert "SmartMoneyReasoningEngine" in source
    assert "reasoning_text=narrative.text" in source


def test_ui_displays_reasoning():
    source = Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")
    assert "AI REASONING & MARKET NARRATIVE" in source
    assert "Decision Quality" in source


def test_version_matches_app_version():
    from dvs_ai import __version__
    from dvs_ai.version import APP_VERSION
    assert __version__ == APP_VERSION


def test_execution_safety_config():
    import json
    raw = json.loads(Path("config.json").read_text(encoding="utf-8"))
    assert raw.get("auto_paper_execution_enabled", False) is False
    assert raw.get("execution_live_enabled", False) is False
