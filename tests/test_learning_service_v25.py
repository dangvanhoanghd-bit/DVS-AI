from types import SimpleNamespace

from dvs_ai.services.learning_service import LearningService
from dvs_ai.services.paper_trade_service import PaperTradeService


class DummyProvider:
    exchange = SimpleNamespace(fetch_ohlcv=lambda *args, **kwargs: [])


class DummyDecision:
    pass


def test_learning_service_empty_db(tmp_path):
    db = tmp_path / "paper.db"
    PaperTradeService(DummyProvider(), DummyDecision(), str(db))
    learning = LearningService(str(db))
    overview = learning.overview()
    assert overview["total"] == 0
    assert overview["closed"] == 0


def test_rejection_monitor_detects_strict_threshold(tmp_path):
    db = tmp_path / "paper.db"
    service = PaperTradeService(DummyProvider(), DummyDecision(), str(db))
    with service._connect() as con:
        for _ in range(120):
            con.execute("""
                INSERT INTO signal_evaluations (
                    created_at,symbol,direction,eligible,entry_ready,
                    confidence,entry_score,risk_score,rr_planned,
                    rejection_reasons,source
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                "2026-07-14 00:00:00",
                "X/USDT",
                "LONG",
                0,
                0,
                55,
                50,
                40,
                2.0,
                "Tín hiệu chưa đạt READY.|Confidence 55 < 70.",
                "AUTO",
            ))
    monitor = LearningService(str(db)).rejection_monitor()
    assert monitor["evaluations"] == 120
    assert monitor["strictness"] == "QUÁ KHẮT KHE"


def test_setup_performance_reads_tags(tmp_path):
    db = tmp_path / "paper.db"
    service = PaperTradeService(DummyProvider(), DummyDecision(), str(db))
    with service._connect() as con:
        for i, r_value in enumerate([1.0, 0.5, -1.0, 1.5, 0.25]):
            con.execute("""
                INSERT INTO paper_trades (
                    pilot_id,created_at,signal_time,symbol,direction,source,status,
                    entry_low,entry_high,planned_entry,fill_price,fill_time,
                    invalidation,tp1,tp2,rr_planned,confidence,entry_score,
                    risk_score,smart_money_score,wyckoff_score,regime,phase,
                    oi_state,funding,result,r_multiple,setup_tags
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                service.PILOT_ID,
                "2026-07-14 00:00:00",
                "2026-07-14 00:00:00",
                f"X{i}/USDT",
                "LONG",
                "AUTO",
                "CLOSED",
                100,100,100,100,"2026-07-14 00:00:00",
                99,101,102,2.0,75,75,20,70,70,
                "TREND","Accumulation","Neutral",0,
                "TP2" if r_value > 0 else "STOP",
                r_value,
                "SPRING|DIRECTION_LONG",
            ))
    rows = LearningService(str(db)).setup_performance()
    spring = next(x for x in rows if x["setup"] == "SPRING")
    assert spring["closed"] == 5
    assert spring["win_rate"] == 80.0
