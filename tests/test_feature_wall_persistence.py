"""
Test hồi quy cho nâng cấp Wall Score toàn diện (5 đề xuất từ phiên làm
việc khác, đã xác nhận chéo với lỗi bão hòa đã tìm thấy độc lập):
  1. Top-3 average thay vì max() đơn lẻ.
  2. Wall Persistence Score qua nhiều lần quét.
  3. COS discount theo persistence (tường mới đóng góp ít hơn).
  4. Tag MICRO_WALL_UNSTABLE/MICRO_LOW_WALL_PERSISTENCE trong Learning Center.
"""
import sys

sys.path.insert(0, ".")

import random
from dvs_ai.engines.microstructure_engine import MicrostructureEngine
from dvs_ai.services.learning_service import LearningService


def _make_raw(wall_size_at_level3, seed=10, other_size_range=(500, 1500)):
    random.seed(seed)
    sizes = [random.uniform(*other_size_range) for _ in range(100)]
    sizes[3] = wall_size_at_level3
    bids = [[100.0 - i * 0.01, sizes[i] / (100.0 - i * 0.01)] for i in range(100)]
    asks = [[100.0 + i * 0.01, random.uniform(*other_size_range) / (100.0 + i * 0.01)]
            for i in range(100)]
    trades = [{"price": 100.0, "qty": 1.0, "quoteQty": 100.0, "isBuyerMaker": False, "time": i}
              for i in range(50)]
    return {"depth": {"bids": bids, "asks": asks}, "agg_trades": trades, "liquidations": []}


def test_first_appearance_has_zero_persistence():
    """Tường xuất hiện lần đầu (không có previous_wall_state) phải có persistence=0."""
    raw = _make_raw(30000.0)
    snap = MicrostructureEngine.analyze("TEST", raw, last_price=100.0, previous_wall_state=None)
    assert snap.bid_wall_persistence == 0.0
    assert snap.bid_wall_streak == 0
    print("✅ test_first_appearance_has_zero_persistence PASS")


def test_persistence_increases_when_wall_remains():
    """Tường CÙNG vị trí, khối lượng không giảm quá 40% qua lần quét kế -> streak+1."""
    raw1 = _make_raw(30000.0)
    snap1 = MicrostructureEngine.analyze("TEST", raw1, last_price=100.0, previous_wall_state=None)

    prev_state = {
        "bid": (snap1.bid_wall_price, snap1.bid_wall_notional, snap1.bid_wall_streak),
        "ask": (snap1.ask_wall_price, snap1.ask_wall_notional, snap1.ask_wall_streak),
    }
    raw2 = _make_raw(29000.0)  # gần như y hệt, giảm nhẹ (vẫn > 60%)
    snap2 = MicrostructureEngine.analyze("TEST", raw2, last_price=100.0, previous_wall_state=prev_state)

    assert snap2.bid_wall_streak == 1, f"Kỳ vọng streak=1, được {snap2.bid_wall_streak}"
    assert snap2.bid_wall_persistence == 25.0
    print(f"✅ test_persistence_increases_when_wall_remains PASS (streak={snap2.bid_wall_streak})")


def test_persistence_resets_when_wall_disappears():
    """Tường BIẾN MẤT (khối lượng về mức bình thường) -> streak reset về 0 (dấu hiệu spoofing)."""
    raw1 = _make_raw(30000.0)
    snap1 = MicrostructureEngine.analyze("TEST", raw1, last_price=100.0, previous_wall_state=None)

    prev_state = {
        "bid": (snap1.bid_wall_price, snap1.bid_wall_notional, snap1.bid_wall_streak),
        "ask": (snap1.ask_wall_price, snap1.ask_wall_notional, snap1.ask_wall_streak),
    }
    raw2 = _make_raw(800.0)  # tường biến mất
    snap2 = MicrostructureEngine.analyze("TEST", raw2, last_price=100.0, previous_wall_state=prev_state)

    assert snap2.bid_wall_streak == 0
    assert snap2.bid_wall_persistence == 0.0
    print("✅ test_persistence_resets_when_wall_disappears PASS")


def test_cos_discounted_for_unconfirmed_wall():
    """
    LỖI ĐÃ SỬA: cùng 1 order book, COS phải THẤP HƠN khi tường chưa từng
    được xác nhận (persistence=0) so với khi đã xác nhận qua nhiều lần
    quét (persistence=100) — tránh 1 lệnh mới/spoofing làm lệch COS ngay
    lập tức.
    """
    raw = _make_raw(30000.0)
    snap_new = MicrostructureEngine.analyze("TEST", raw, last_price=100.0, previous_wall_state=None)
    snap_confirmed = MicrostructureEngine.analyze(
        "TEST", raw, last_price=100.0,
        previous_wall_state={"bid": (100.0, 30000.0, 4), "ask": (0, 0, 0)},
    )
    assert snap_confirmed.composite_operator_score > snap_new.composite_operator_score, (
        f"COS đã xác nhận ({snap_confirmed.composite_operator_score}) phải cao hơn "
        f"COS chưa xác nhận ({snap_new.composite_operator_score})"
    )
    print(f"✅ test_cos_discounted_for_unconfirmed_wall PASS "
          f"(mới={snap_new.composite_operator_score:.1f}, "
          f"đã xác nhận={snap_confirmed.composite_operator_score:.1f})")


def test_genuine_wall_still_reaches_full_score_eventually():
    """Tường thật, sau khi đủ persistence, vẫn đạt được điểm cao đầy đủ (không bị chặn vĩnh viễn)."""
    raw = _make_raw(30000.0)
    snap_confirmed = MicrostructureEngine.analyze(
        "TEST", raw, last_price=100.0,
        previous_wall_state={"bid": (100.0, 30000.0, 4), "ask": (0, 0, 0)},
    )
    assert snap_confirmed.bid_wall_persistence == 100.0
    print("✅ test_genuine_wall_still_reaches_full_score_eventually PASS")


def test_learning_service_recognizes_new_wall_tags():
    """known_micro và microstructure_rejections trong learning_service.py phải nhận diện 2 tag mới."""
    import sqlite3
    import tempfile
    from pathlib import Path

    db = Path(tempfile.mkdtemp()) / "learn.db"
    with sqlite3.connect(db) as con:
        con.execute("""CREATE TABLE signal_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT,
            symbol TEXT, direction TEXT, eligible INTEGER, entry_ready INTEGER,
            confidence REAL, entry_score REAL, risk_score REAL, rr_planned REAL,
            rejection_reasons TEXT, source TEXT, lab TEXT
        )""")
        for i in range(150):
            con.execute(
                "INSERT INTO signal_evaluations "
                "(created_at,symbol,direction,eligible,entry_ready,confidence,"
                "entry_score,risk_score,rr_planned,rejection_reasons,source,lab) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"2026-01-{1+i%28:02d} 00:00:00", f"COIN{i}", "LONG", 0, 0,
                 60.0, 60.0, 40.0, 1.8, "MICRO_WALL_UNSTABLE", "AUTO", "SHADOW"),
            )
    monitor = LearningService(db_path=str(db)).rejection_monitor()
    assert monitor["microstructure_rejections"]["MICRO_WALL_UNSTABLE"] == 150
    print("✅ test_learning_service_recognizes_new_wall_tags PASS")


def main():
    test_first_appearance_has_zero_persistence()
    test_persistence_increases_when_wall_remains()
    test_persistence_resets_when_wall_disappears()
    test_cos_discounted_for_unconfirmed_wall()
    test_genuine_wall_still_reaches_full_score_eventually()
    test_learning_service_recognizes_new_wall_tags()
    print("\n✅ TẤT CẢ TEST WALL PERSISTENCE + COS DISCOUNT PASS")


if __name__ == "__main__":
    main()
