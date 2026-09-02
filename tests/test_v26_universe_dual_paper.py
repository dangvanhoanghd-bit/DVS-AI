from pathlib import Path
from types import SimpleNamespace

from dvs_ai.config import load_config
from dvs_ai.services.paper_trade_service import PaperTradeService


class DummyProvider:
    exchange = SimpleNamespace(fetch_ohlcv=lambda *args, **kwargs: [])


class DummyDecision:
    pass


def test_config_expanded_universe_defaults():
    cfg = load_config()
    assert 20 <= cfg.universe_size <= 200
    assert 10 <= cfg.deep_scan_size <= 80
    assert cfg.main_long_limit == 25
    assert cfg.shadow_long_limit == 50


def test_scanner_contains_round_robin_deep_scan_logic():
    path = Path(__file__).parents[1] / "dvs_ai" / "services" / "scanner.py"
    source = path.read_text(encoding="utf-8")
    assert "def deep_scan_batch(" in source
    assert "self.universe_cursor" in source
    assert "rotating.append" in source


def test_dual_lab_schema_and_limits(tmp_path):
    cfg = SimpleNamespace(
        main_long_limit=25,
        main_short_limit=25,
        shadow_long_limit=50,
        shadow_short_limit=50,
        main_confidence=70,
        main_entry=65,
        main_risk_max=50,
        main_rr_min=1.8,
        shadow_confidence=55,
        shadow_entry=50,
        shadow_risk_max=60,
        shadow_rr_min=1.5,
    )
    service = PaperTradeService(
        DummyProvider(),
        DummyDecision(),
        str(tmp_path / "paper.db"),
        config=cfg,
    )
    with service._connect() as con:
        columns = {
            row[1]
            for row in con.execute(
                "PRAGMA table_info(paper_trades)"
            ).fetchall()
        }
        eval_columns = {
            row[1]
            for row in con.execute(
                "PRAGMA table_info(signal_evaluations)"
            ).fetchall()
        }

    assert "lab" in columns
    assert "lab" in eval_columns
    assert service._limit("MAIN", "LONG") == 25
    assert service._limit("SHADOW", "SHORT") == 50
