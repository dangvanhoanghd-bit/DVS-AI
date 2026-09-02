from __future__ import annotations
import sys, importlib.util
try:
    _ccxt_spec = importlib.util.find_spec("ccxt")
except ValueError:
    _ccxt_spec = None
if _ccxt_spec is None:
    sys.path.insert(0, "test_stubs")
sys.path.insert(0,".")
from types import SimpleNamespace
import pandas as pd
import pytest
from dvs_ai.services.scanner import ScannerService

class Provider:
    def fetch_snapshot(self,symbol):
        return SimpleNamespace(
            oi_change_15m_pct=1.2,funding_pct=-0.03,
            delta_ratio=0.21,cvd_slope=0.18,
            liquidation_impulse=42.0,
            oi_change_history=(0.2,0.4,0.8,1.2),
            delta_ratio_history=(0.05,0.08,0.14,0.21),
        )
    def fetch_ohlcv(self,symbol,timeframe,limit):
        return pd.DataFrame({
            "open":[100.0]*80,"high":[101.0]*80,
            "low":[99.0]*80,"close":[100.5]*80,
            "volume":[1000.0]*80,
        })
class Indicator:
    def analyze(self,df,tf):
        return SimpleNamespace(price_change_pct=0.5,cmf=0.1,close=100.5,ema20=100.0)
class Structure:
    def analyze(self,frames):
        return SimpleNamespace(
            liquidity_event="quét đáy",wyckoff_signal="spring",
            wyckoff_test="TEST AFTER SPRING",support=99.0,
            resistance=101.0,lifecycle_stage="TEST",
        )
class Regime:
    def analyze(self,a): return SimpleNamespace()
class Alignment:
    def analyze(self,a): return SimpleNamespace()
class SmartEntry:
    def analyze(self,*a): return SimpleNamespace(absorption_score=66.0)
class Decision:
    def combine(self,*a):
        return SimpleNamespace(direction="LONG",trend_lifecycle="TEST",microstructure=None)
    def apply_footprint_v31(self,a,c): return a
class Footprint:
    def __init__(self): self.context=None
    def analyze(self,frame,context,expected_direction):
        self.context=context
        return {"composite":SimpleNamespace()}

def make_scanner():
    s=ScannerService(
        Provider(),Indicator(),Decision(),
        structure=Structure(),regime=Regime(),
        alignment=Alignment(),smart_entry=SmartEntry(),
    )
    s.footprint_orchestrator=Footprint()
    return s

def test_context_forwarded():
    s=make_scanner()
    s.scan_coin("BTC/USDT:USDT",("15m",))
    c=s.footprint_orchestrator.context
    assert c["delta_ratio"]==pytest.approx(0.21)
    assert c["cvd_slope"]==pytest.approx(0.18)
    assert c["liquidation_impulse"]==pytest.approx(42.0)
    assert c["absorption_score"]==pytest.approx(66.0)
    assert c["lifecycle_stage"]=="TEST"
    assert c["oi_change_series"]==(0.2,0.4,0.8,1.2)

def test_missing_15m_clear_error():
    with pytest.raises(ValueError,match="Footprint yêu cầu dữ liệu khung 15m"):
        make_scanner().scan_coin("BTC/USDT:USDT",("1h",))

def test_neutral_not_short():
    brief=ScannerService.build_market_brief({
        "BTC/USDT:USDT":SimpleNamespace(direction="SHORT"),
        "A":SimpleNamespace(direction="LONG"),
        "B":SimpleNamespace(direction="NEUTRAL"),
        "C":SimpleNamespace(direction="NEUTRAL"),
    })
    assert brief.alt_breadth_long_pct==pytest.approx(100.0)
    assert "1 Long/0 Short/2 Neutral" in brief.summary
