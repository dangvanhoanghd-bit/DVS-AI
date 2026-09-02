"""
Test hồi quy: Wall Score (Bid Wall/Ask Wall trong MicrostructureEngine)
từng bị bão hòa ở gần như mọi coin (quan sát trực tiếp từ ảnh chụp màn
hình dashboard thật: cột Bid Wall/Ask Wall hiển thị 100.0 lặp lại liên
tục cho nhiều coin khác nhau).

NGUYÊN NHÂN GỐC: wall_score() so sánh max/median trên TOÀN BỘ 100 mức
giá lấy từ Binance /fapi/v1/depth — nhưng order book thật luôn có xu
hướng tự nhiên: các mức GIÁ XA hiện tại (ít cạnh tranh hơn) thường có
1-2 lệnh "nghỉ" kích thước lớn bất thường do ai đó đặt "cho chắc" —
đây KHÔNG phải là "tường phòng thủ" thật sự ảnh hưởng đến hành động giá
sắp tới, nhưng đủ khiến tỷ lệ max/median vượt xa ngưỡng bão hòa (6.56x)
gần như luôn luôn, làm Wall Score mất hoàn toàn khả năng phân biệt.

TÁC ĐỘNG THẬT (không chỉ hiển thị): bid_wall/ask_wall chiếm 30% trọng
số của Composite Operator Score (COS), và COS được dùng làm ngưỡng
`min_cos` trong paper_trade_service.py (điều kiện Shadow eligibility)
— Wall Score bị bão hòa sai sẽ làm COS bị thổi phồng có hệ thống.

ĐÃ SỬA: giới hạn cửa sổ xét về NEAR_TOUCH_LEVELS=20 mức GẦN GIÁ NHẤT
(bids/asks từ Binance luôn trả về theo thứ tự gần giá nhất trước) —
đúng khái niệm "tường" muốn đo: lệnh lớn bất thường ĐANG PHÒNG THỦ giá
hiện tại, không phải lệnh nghỉ ở đâu đó xa xôi trong sổ lệnh.
"""
import sys
import random

sys.path.insert(0, ".")

from dvs_ai.engines.microstructure_engine import MicrostructureEngine


def _make_raw(bid_sizes, ask_sizes, last_price=100.0, n_trades=50):
    bids = [
        [last_price - i * 0.01, size / max(last_price - i * 0.01, 1e-9)]
        for i, size in enumerate(bid_sizes)
    ]
    asks = [
        [last_price + i * 0.01, size / max(last_price + i * 0.01, 1e-9)]
        for i, size in enumerate(ask_sizes)
    ]
    trades = [
        {"price": last_price, "qty": 1.0, "quoteQty": last_price,
         "isBuyerMaker": False, "time": i}
        for i in range(n_trades)
    ]
    return {"depth": {"bids": bids, "asks": asks}, "agg_trades": trades, "liquidations": []}


def test_far_level_skew_does_not_saturate_wall_score():
    """
    LỖI ĐÃ SỬA: order book có 1 lệnh nghỉ lớn bất thường ở mức GIÁ XA
    (level >= 20, ngoài cửa sổ near-touch) — mô phỏng đúng đặc điểm tự
    nhiên của order book thật — KHÔNG được làm Wall Score bão hòa ở 100.
    """
    random.seed(2)
    sizes = []
    for level in range(100):
        if level < 20:
            sizes.append(random.uniform(500, 2000))
        else:
            sizes.append(random.uniform(500, 2000) * random.choice([1, 1, 1, 1, 1, 2, 3, 8]))

    raw = _make_raw(sizes, sizes)
    snapshot = MicrostructureEngine.analyze("TESTUSDT", raw, last_price=100.0)

    assert snapshot.bid_wall_score < 50.0, (
        f"LỖI TÁI PHÁT: lệch ở mức giá XA (ngoài near-touch) không được "
        f"làm Wall Score cao, được bid_wall_score={snapshot.bid_wall_score}"
    )
    assert snapshot.ask_wall_score < 50.0, (
        f"LỖI TÁI PHÁT: {snapshot.ask_wall_score}"
    )
    print(f"✅ test_far_level_skew_does_not_saturate_wall_score PASS "
          f"(bid_wall={snapshot.bid_wall_score:.1f}, ask_wall={snapshot.ask_wall_score:.1f})")


def test_genuine_near_touch_wall_still_detected():
    """
    Đảm bảo việc sửa lỗi KHÔNG làm mất khả năng phát hiện tường THẬT —
    khi có 1 lệnh lớn bất thường THỰC SỰ ở gần giá hiện tại (trong cửa
    sổ near-touch), Wall Score vẫn phải cao.
    """
    random.seed(3)
    sizes = []
    for level in range(100):
        if level == 5:
            sizes.append(30000.0)  # tường thật, ngay gần giá (mức #6)
        else:
            sizes.append(random.uniform(500, 2000))  # đồng đều khắp nơi khác

    raw = _make_raw(sizes, sizes)
    snapshot = MicrostructureEngine.analyze("TESTUSDT", raw, last_price=100.0)

    assert snapshot.bid_wall_score > 50.0, (
        f"Tường THẬT gần giá phải được phát hiện (điểm cao), "
        f"được {snapshot.bid_wall_score}"
    )
    print(f"✅ test_genuine_near_touch_wall_still_detected PASS "
          f"(bid_wall={snapshot.bid_wall_score:.1f})")


def test_wall_score_uses_only_near_touch_window():
    """
    Kiểm chứng trực tiếp: Wall Score với 1 lệnh lớn CHỈ ở mức thứ 21 trở
    đi (ngoài cửa sổ 20 mức near-touch) phải giống hệt trường hợp KHÔNG
    có lệnh lớn nào cả — xác nhận cửa sổ xét đúng bị giới hạn ở 20 mức.
    """
    random.seed(5)
    baseline_sizes = [random.uniform(500, 2000) for _ in range(100)]

    sizes_with_far_outlier = list(baseline_sizes)
    sizes_with_far_outlier[25] = 100000.0  # outlier RÕ RÀNG ở mức 26 (ngoài near-touch)

    raw_baseline = _make_raw(baseline_sizes, baseline_sizes)
    raw_with_outlier = _make_raw(sizes_with_far_outlier, sizes_with_far_outlier)

    snap_baseline = MicrostructureEngine.analyze("TESTUSDT", raw_baseline, last_price=100.0)
    snap_outlier = MicrostructureEngine.analyze("TESTUSDT", raw_with_outlier, last_price=100.0)

    assert snap_baseline.bid_wall_score == snap_outlier.bid_wall_score, (
        f"Outlier ở mức 26 (ngoài cửa sổ 20 mức near-touch) không được "
        f"ảnh hưởng đến Wall Score: baseline={snap_baseline.bid_wall_score}, "
        f"có outlier xa={snap_outlier.bid_wall_score}"
    )
    print("✅ test_wall_score_uses_only_near_touch_window PASS "
          "(outlier ngoài cửa sổ near-touch không ảnh hưởng gì)")


def main():
    test_far_level_skew_does_not_saturate_wall_score()
    test_genuine_near_touch_wall_still_detected()
    test_wall_score_uses_only_near_touch_window()
    print("\n✅ TẤT CẢ TEST HỒI QUY WALL SCORE PASS")


if __name__ == "__main__":
    main()
