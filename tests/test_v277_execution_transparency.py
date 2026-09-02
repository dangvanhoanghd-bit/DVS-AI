from pathlib import Path
from types import SimpleNamespace
from dvs_ai.engines.risk_engine import RiskEngine

ROOT = Path(__file__).parents[1]

def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")

def test_mmr_resolver():
    engine = RiskEngine(SimpleNamespace(maintenance_margin_rate=0.005))
    assert engine.resolve_mmr(1000) == (0.005, 0.0, "FIXED_APPROXIMATION")
    tiers = ((5000, 0.004, 0), (25000, 0.005, 50))
    assert engine.resolve_mmr(10000, tiers) == (0.005, 50.0, "TIER_TABLE")

def test_plan_repair_tag():
    assert 'tags.append("PLAN_REPAIRED")' in read(
        "dvs_ai/services/paper_trade_service.py"
    )

def test_execution_diagnostics():
    source = read("dvs_ai/services/learning_service.py")
    assert "def execution_diagnostics" in source
    assert "p90_slippage_pct" in source
    assert "repair_rate" in source

def test_ui_slippage_visibility():
    source = read("dvs_ai/ui/main_window.py")
    assert '"Slip %"' in source
    assert "Configured Slippage:" in source
    assert "Execution diagnostics:" in source

def test_ambiguous_policy():
    assert "Không giả định TP xảy ra trước Stop" in read(
        "README_FULL_PROJECT.md"
    )
