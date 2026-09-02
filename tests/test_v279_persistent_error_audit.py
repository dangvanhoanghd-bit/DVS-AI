import sqlite3
from pathlib import Path
from types import SimpleNamespace

from dvs_ai.services.signal_recorder import SignalRecorder


def test_record_error_persists_structured_data(tmp_path):
    db = tmp_path / "signals.db"
    recorder = SignalRecorder(str(db))

    ok = recorder.record_error(
        symbol="BTC/USDT:USDT",
        direction="LONG",
        error_type="RuntimeError",
        error_message="paper failure",
        stack_trace="traceback text",
        context={"confidence": 72.5},
        source="AUTO_PAPER_TRADE",
    )
    assert ok is True

    with sqlite3.connect(db) as con:
        row = con.execute("""
            SELECT symbol,direction,error_type,error_message,
                   stack_trace,context,source
            FROM error_logs
        """).fetchone()

    assert row[0] == "BTC/USDT:USDT"
    assert row[1] == "LONG"
    assert row[2] == "RuntimeError"
    assert row[3] == "paper failure"
    assert row[4] == "traceback text"
    assert '"confidence": 72.5' in row[5]
    assert row[6] == "AUTO_PAPER_TRADE"


def test_latest_errors_and_stats(tmp_path):
    db = tmp_path / "signals.db"
    recorder = SignalRecorder(str(db))
    recorder.record_error(
        symbol="ETH/USDT:USDT",
        direction="SHORT",
        error_type="ValueError",
        error_message="bad plan",
        source="AUTO_PAPER_WRAPPER",
    )

    rows = recorder.latest_errors(
        source="AUTO_PAPER_WRAPPER"
    )
    stats = recorder.error_stats()

    assert len(rows) == 1
    assert rows[0][1] == "ETH/USDT:USDT"
    assert stats["total"] == 1
    assert stats["last_24h"] == 1
    assert stats["sources"] == 1


def test_auto_paper_call_uses_existing_signature():
    root = Path(__file__).parents[1]
    source = (
        root / "dvs_ai/ui/main_window.py"
    ).read_text(encoding="utf-8")
    assert "symbol=analysis.symbol" in source
    assert 'source="AUTO_PAPER_TRADE"' in source
    assert "stack_trace=stack_trace" in source
    assert "except Exception:\\n                pass" not in source[
        source.index("def auto_paper_consider"):
        source.index("def _apply_detail_tooltips")
    ]


def test_error_schema_exists(tmp_path):
    db = tmp_path / "signals.db"
    SignalRecorder(str(db))
    with sqlite3.connect(db) as con:
        columns = {
            row[1]
            for row in con.execute(
                "PRAGMA table_info(error_logs)"
            )
        }
    assert {
        "timestamp", "symbol", "direction", "error_type",
        "error_message", "stack_trace", "context", "source",
    }.issubset(columns)
