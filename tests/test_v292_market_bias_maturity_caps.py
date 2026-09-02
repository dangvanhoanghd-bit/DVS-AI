from types import ModuleType, SimpleNamespace
from pathlib import Path
import sys

ccxt_stub = ModuleType("ccxt")
ccxt_stub.binance = lambda *args, **kwargs: None
sys.modules.setdefault("ccxt", ccxt_stub)
sys.modules.setdefault("pandas_ta", ModuleType("pandas_ta"))

from dvs_ai.domain.models import EntryStatus, MarketBrief
from dvs_ai.services.scanner import ScannerService


def analysis(direction="SHORT", status=EntryStatus.READY, confidence=80):
    r15 = SimpleNamespace(
        cmf=0.15,
        close=101.0,
        ema20=100.0,
    )
    structure = SimpleNamespace(
        liquidity_event="NONE",
        wyckoff_signal="NONE",
        wyckoff_test="NONE",
    )
    return SimpleNamespace(
        direction=direction,
        entry_status=status,
        confidence_score=confidence,
        action=f"READY {direction}",
        timing="",
        reasons=(),
        timeframes={"15m": r15},
        structure=structure,
        market_bias_code="NEUTRAL",
        market_bias_gate="NOT_APPLIED",
    )


def test_strong_long_blocks_unconfirmed_short(monkeypatch):
    from dataclasses import replace as real_replace

    # SimpleNamespace is not a dataclass; emulate replace for this unit.
    def fake_replace(obj, **changes):
        data = dict(obj.__dict__)
        data.update(changes)
        return SimpleNamespace(**data)

    import dvs_ai.services.scanner as module
    monkeypatch.setattr(module, "replace", fake_replace)

    brief = MarketBrief(
        "LONG", 75, "ƯU TIÊN LONG MẠNH", "THẤP",
        "", "STRONG_LONG", 75,
    )
    gated = ScannerService.apply_market_bias_gate(
        analysis(),
        brief,
    )
    assert gated.entry_status == EntryStatus.WAIT
    assert gated.confidence_score == 49.0
    assert gated.market_bias_gate == "BLOCK_OPPOSING_STRONG"


def test_quantum_report_has_lab_breakdown_source():
    source = (
        Path(__file__).parents[1]
        / "dvs_ai/services/quantum_optimizer.py"
    ).read_text(encoding="utf-8")
    assert "raw_lab_breakdown" in source
    assert "validation_lab_breakdown" in source


def test_maturity_has_absolute_caps():
    source = (
        Path(__file__).parents[1]
        / "dvs_ai/engines/decision_engine.py"
    ).read_text(encoding="utf-8")
    assert "confidence * 0.78" in source
    assert "65.0" in source
    assert "confidence * 0.45" in source
    assert "45.0" in source


def test_auto_paper_is_deferred_until_scan_finished():
    source = (
        Path(__file__).parents[1]
        / "dvs_ai/ui/main_window.py"
    ).read_text(encoding="utf-8")
    on_result = source[
        source.index("def on_result"):
        source.index("def on_finished")
    ]
    worker = source[
        source.index("class FinalizationWorker"):
        source.index("class QuantumWorker")
    ]
    batch = source[
        source.index("def _process_auto_paper_batch"):
        source.index("def _refresh_paper_outcomes_deferred")
    ]
    assert "self.auto_paper_consider(a)" not in on_result
    assert "apply_market_bias_gate" in worker
    assert "self.auto_paper_consider(analysis" in batch
