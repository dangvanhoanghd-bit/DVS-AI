from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

try:
    _ccxt_spec = importlib.util.find_spec("ccxt")
except ValueError:
    _ccxt_spec = None
if _ccxt_spec is None:
    sys.path.insert(0, "test_stubs")
sys.path.insert(0, ".")

from dvs_ai.domain.models import EntryStatus
from dvs_ai.services.scanner import ScannerService


def analysis(
    *,
    symbol="A/USDT:USDT",
    direction="LONG",
    status=EntryStatus.WAIT,
    market_gate="BLOCK_OPPOSING_STRONG",
    direction_gate="BLOCK",
    maturity="LATE",
):
    return SimpleNamespace(
        symbol=symbol,
        direction=direction,
        entry_status=status,
        market_bias_gate=market_gate,
        direction_confirmation_gate=direction_gate,
        maturity_gate=maturity,
        confidence_score=60.0,
        long_entry_score=60.0,
        short_entry_score=10.0,
        long_trend_score=70.0,
        short_trend_score=10.0,
        direction_confirmation_score=50.0,
        smart_entry=SimpleNamespace(
            smart_money_probability=50.0
        ),
        risk=SimpleNamespace(risk_score=30.0),
        trade_plan=SimpleNamespace(rr_to_tp2=2.0),
    )


def test_correlated_penalties_use_only_the_maximum():
    result = ScannerService._opportunity_breakdown(analysis())
    assert result["penalty"] == 25.0
    assert result["final"] == result["base"]-25.0


def test_watch_penalty_is_smaller():
    result = ScannerService._opportunity_breakdown(
        analysis(
            status=EntryStatus.SETUP,
            market_gate="PASS",
            direction_gate="WATCH",
            maturity="CONFIRMED",
        )
    )
    assert result["penalty"] == 6.0
    assert result["bonus"] == 5.0


def test_rank_publishes_breakdown_and_percentile():
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class Candidate:
        symbol: str
        direction: str
        entry_status: object
        market_bias_gate: str
        direction_confirmation_gate: str
        maturity_gate: str
        confidence_score: float
        long_entry_score: float
        short_entry_score: float
        long_trend_score: float
        short_trend_score: float
        direction_confirmation_score: float
        smart_entry: object
        risk: object
        trade_plan: object
        reasons: tuple = ()
        opportunity_score: float = 0.0
        opportunity_rank: int = 999
        opportunity_gate: str = "UNRANKED"
        opportunity_base_score: float = 0.0
        opportunity_bonus: float = 0.0
        opportunity_penalty: float = 0.0
        opportunity_penalty_reason: str = "NONE"
        opportunity_percentile: float = 0.0

    base_ns = analysis(
        status=EntryStatus.SETUP,
        market_gate="PASS",
        direction_gate="CONFIRMED",
        maturity="CONFIRMED",
    )
    first_candidate = Candidate(**vars(base_ns))
    second_candidate = Candidate(
        **{
            **vars(base_ns),
            "symbol": "B/USDT:USDT",
            "confidence_score": 30.0,
        }
    )

    ranked = ScannerService.rank_opportunities(
        {
            first_candidate.symbol: first_candidate,
            second_candidate.symbol: second_candidate,
        },
        minimum_score=52.0,
    )

    first = ranked[first_candidate.symbol]
    last = ranked[second_candidate.symbol]
    assert first.opportunity_rank == 1
    assert first.opportunity_percentile == 100.0
    assert last.opportunity_percentile == 0.0
    assert first.opportunity_base_score > 0.0
    assert first.opportunity_penalty_reason == "NONE"


def test_ui_version_is_synchronized():
    from dvs_ai.version import APP_VERSION, WINDOW_TITLE
    source = Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")
    assert "from dvs_ai.version import" in source
    assert APP_VERSION in WINDOW_TITLE
    assert "Alpha 2.18.1 Startup Hotfix" not in source


def test_version_matches_app_version():
    from dvs_ai import __version__
    from dvs_ai.version import APP_VERSION
    assert __version__ == APP_VERSION


def test_execution_safety_config():
    import json
    raw = json.loads(Path("config.json").read_text(encoding="utf-8"))
    assert raw["execution_mode"] == "PAPER"
    assert raw["execution_live_enabled"] is False
