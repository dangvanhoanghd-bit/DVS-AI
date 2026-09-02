import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dvs_ai.services.outcome_tracker import OutcomeTracker
from dvs_ai.services.history_service import HistoryService


class FakeExchange:
    def __init__(self, candles):
        self.candles = candles

    def fetch_ohlcv(self, symbol, timeframe, since, limit):
        return [
            candle for candle in self.candles
            if candle[0] >= since
        ][:limit]


class FakeProvider:
    def __init__(self, candles):
        self.exchange = FakeExchange(candles)


def make_db(path, direction="LONG"):
    with sqlite3.connect(path) as con:
        con.execute("""
            CREATE TABLE scan_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                generated_at TEXT NOT NULL,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_status TEXT NOT NULL,
                confidence REAL NOT NULL,
                long_trend REAL NOT NULL,
                long_entry REAL NOT NULL,
                short_trend REAL NOT NULL,
                short_entry REAL NOT NULL,
                price REAL NOT NULL,
                phase TEXT NOT NULL,
                oi_state TEXT NOT NULL,
                invalidation REAL,
                tp1 REAL,
                tp2 REAL,
                outcome TEXT DEFAULT 'PENDING',
                outcome_time TEXT,
                outcome_price REAL,
                r_multiple REAL
            )
        """)
        con.execute("""
            INSERT INTO scan_signals (
                generated_at,symbol,direction,entry_status,
                confidence,long_trend,long_entry,
                short_trend,short_entry,price,phase,oi_state,
                invalidation,tp1,tp2,outcome
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            "2026-07-14 00:00:00",
            "TEST/USDT",
            direction,
            "READY",
            70,70,70,20,20,
            100,
            "TEST",
            "Neutral",
            90 if direction == "LONG" else 110,
            112 if direction == "LONG" else 88,
            123 if direction == "LONG" else 77,
            "PENDING",
        ))


def ms(text):
    return int(
        datetime.strptime(
            text,
            "%Y-%m-%d %H:%M:%S",
        ).replace(tzinfo=timezone.utc).timestamp()*1000
    )


def test_long_tp1_then_stop_is_partial_stop(tmp_path):
    db = tmp_path / "signals.db"
    make_db(db, "LONG")
    candles = [
        [ms("2026-07-14 00:01:00"),100,113,99,112,1],
        [ms("2026-07-14 00:02:00"),112,113,89,90,1],
    ]
    tracker = OutcomeTracker(FakeProvider(candles), str(db))
    result = tracker.evaluate_pending(expiry_days=9999)
    assert result["updated"] == 1

    with sqlite3.connect(db) as con:
        outcome, r_value, detail = con.execute("""
            SELECT outcome,r_multiple,outcome_detail
            FROM scan_signals
        """).fetchone()

    # TP1 full R=1.2. Realized half=0.6; runner stop=-0.5 => +0.1R.
    assert outcome == "PARTIAL_STOP"
    assert round(r_value, 6) == 0.1
    assert detail == "TP1_THEN_STOP"


def test_short_tp1_then_tp2_uses_partial_accounting(tmp_path):
    db = tmp_path / "signals.db"
    make_db(db, "SHORT")
    candles = [
        [ms("2026-07-14 00:01:00"),100,101,87,88,1],
        [ms("2026-07-14 00:02:00"),88,89,76,77,1],
    ]
    tracker = OutcomeTracker(FakeProvider(candles), str(db))
    tracker.evaluate_pending(expiry_days=9999)

    with sqlite3.connect(db) as con:
        outcome, r_value, detail = con.execute("""
            SELECT outcome,r_multiple,outcome_detail
            FROM scan_signals
        """).fetchone()

    # TP1=1.2R and TP2=2.3R, each 50% => 1.75R.
    assert outcome == "TP2"
    assert round(r_value, 6) == 1.75
    assert detail == "TP1_THEN_TP2"


def test_tp1_alone_remains_pending(tmp_path):
    db = tmp_path / "signals.db"
    make_db(db, "LONG")
    candles = [
        [ms("2026-07-14 00:01:00"),100,113,99,112,1],
    ]
    tracker = OutcomeTracker(FakeProvider(candles), str(db))
    result = tracker.evaluate_pending(expiry_days=9999)

    with sqlite3.connect(db) as con:
        outcome = con.execute(
            "SELECT outcome FROM scan_signals"
        ).fetchone()[0]

    assert outcome == "PENDING"
    assert result["updated"] == 0
    assert result["tp1_intermediate"] == 1


def test_same_candle_stop_and_tp_is_ambiguous(tmp_path):
    db = tmp_path / "signals.db"
    make_db(db, "LONG")
    candles = [
        [ms("2026-07-14 00:01:00"),100,124,89,105,1],
    ]
    tracker = OutcomeTracker(FakeProvider(candles), str(db))
    tracker.evaluate_pending(expiry_days=9999)

    with sqlite3.connect(db) as con:
        outcome, detail = con.execute("""
            SELECT outcome,outcome_detail FROM scan_signals
        """).fetchone()

    assert outcome == "AMBIGUOUS"
    assert detail == "AMBIGUOUS_ACTIVE_CANDLE"


def test_history_stats_do_not_count_tp1_as_win(tmp_path):
    db = tmp_path / "signals.db"
    make_db(db, "LONG")
    with sqlite3.connect(db) as con:
        con.execute("""
            UPDATE scan_signals
            SET outcome='TP1', r_multiple=1.2
        """)

    stats = HistoryService(str(db)).stats()
    assert stats["resolved"] == 0
    assert stats["wins"] == 0
    assert stats["win_rate"] == 0.0
