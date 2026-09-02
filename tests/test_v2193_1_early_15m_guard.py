from __future__ import annotations

import importlib.util
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

try:
    _ccxt_spec = importlib.util.find_spec("ccxt")
except ValueError:
    _ccxt_spec = None
if _ccxt_spec is None:
    sys.path.insert(0, "test_stubs")
sys.path.insert(0, ".")

from dvs_ai.services.scanner import ScannerService


class Provider:
    def fetch_snapshot(self, symbol):
        return SimpleNamespace()

    def fetch_ohlcv(self, symbol, timeframe, limit):
        return pd.DataFrame({
            "open": [100.0] * 80,
            "high": [101.0] * 80,
            "low": [99.0] * 80,
            "close": [100.5] * 80,
            "volume": [1000.0] * 80,
        })


class Indicator:
    def analyze(self, df, tf):
        return SimpleNamespace()


class StructureMustNotRun:
    def analyze(self, frames):
        raise AssertionError(
            "StructureEngine must not run before the 15m guard."
        )


class Dummy:
    def analyze(self, *args, **kwargs):
        return SimpleNamespace()


class Decision:
    def combine(self, *args, **kwargs):
        raise AssertionError(
            "DecisionEngine must not run before the 15m guard."
        )


def test_missing_15m_is_blocked_before_structure_and_decision():
    scanner = ScannerService(
        Provider(),
        Indicator(),
        Decision(),
        structure=StructureMustNotRun(),
        regime=Dummy(),
        alignment=Dummy(),
        smart_entry=Dummy(),
    )

    with pytest.raises(
        ValueError,
        match="Footprint yêu cầu dữ liệu khung 15m",
    ):
        scanner.scan_coin("BTC/USDT:USDT", ("1h",))


def test_guard_appears_before_structure_call_in_source():
    from pathlib import Path

    source = Path(
        "dvs_ai/services/scanner.py"
    ).read_text(encoding="utf-8")

    guard_pos = source.find('if "15m" not in analyses')
    structure_pos = source.find(
        "structure = self.structure.analyze(frames)"
    )
    decision_pos = source.find(
        "analysis = self.decision.combine("
    )

    assert guard_pos >= 0
    assert guard_pos < structure_pos < decision_pos
