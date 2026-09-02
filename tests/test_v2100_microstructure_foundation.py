from types import ModuleType
import sys

ccxt_stub = ModuleType("ccxt")
ccxt_stub.binance = lambda *args, **kwargs: None
sys.modules.setdefault("ccxt", ccxt_stub)
sys.modules.setdefault("pandas_ta", ModuleType("pandas_ta"))

from dvs_ai.engines.microstructure_engine import MicrostructureEngine


def raw_book(delta_side="buy"):
    trades = []
    for i in range(100):
        is_sell = delta_side == "sell"
        trades.append({
            "p": str(100 + i*0.001),
            "q": "10",
            "m": is_sell,
        })
    return {
        "depth": {
            "bids": [["99.9", "100"], ["99.8", "80"], ["99.7", "60"],
                     ["99.6", "50"], ["99.5", "40"]],
            "asks": [["100.1", "40"], ["100.2", "40"], ["100.3", "40"],
                     ["100.4", "40"], ["100.5", "40"]],
        },
        "agg_trades": trades,
        "liquidations": [],
    }


def test_microstructure_snapshot_is_bounded():
    snap = MicrostructureEngine.analyze(
        "TEST/USDT:USDT",
        raw_book("buy"),
        last_price=100,
        oi_change_15m_pct=1.0,
        funding_pct=0.0,
        price_change_pct=0.2,
    )
    for value in (
        snap.ofi_score,
        snap.absorption_score,
        snap.position_building_score,
        snap.composite_operator_score,
    ):
        assert 0 <= value <= 100
    assert snap.trade_delta_usd > 0
    assert snap.data_quality == "GOOD"
    assert not snap.liquidation_data_available


def test_sell_flow_flips_ofi():
    buy = MicrostructureEngine.analyze(
        "T", raw_book("buy"), 100
    )
    sell = MicrostructureEngine.analyze(
        "T", raw_book("sell"), 100
    )
    assert buy.ofi_score > 50
    assert sell.ofi_score < 50


def test_rest_snapshot_does_not_claim_spoofing():
    snap = MicrostructureEngine.analyze(
        "T", raw_book("buy"), 100
    )
    assert snap.spoofing_probability == 0
    assert not snap.websocket_ready
