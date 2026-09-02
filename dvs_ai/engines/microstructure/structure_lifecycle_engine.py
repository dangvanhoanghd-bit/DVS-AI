from __future__ import annotations
from math import isfinite
from typing import Any, Mapping
import pandas as pd
from .base import LifecycleStage, MicrostructureEvidence
class StructureLifecycleEngine:
    REQUIRED=('open','high','low','close','volume')
    @staticmethod
    def _f(v,d=0.0):
        try:
            x=float(v); return x if isfinite(x) else d
        except (TypeError,ValueError): return d
    @classmethod
    def _frame(cls,df):
        if not isinstance(df,pd.DataFrame): raise TypeError('ohlcv must be DataFrame')
        f=df.rename(columns={'o':'open','h':'high','l':'low','c':'close','v':'volume'}).copy()
        miss=[x for x in cls.REQUIRED if x not in f.columns]
        if miss: raise ValueError('Missing OHLCV columns: '+','.join(miss))
        for x in cls.REQUIRED: f[x]=pd.to_numeric(f[x],errors='coerce')
        return f.dropna(subset=list(cls.REQUIRED)).reset_index(drop=True)
    @staticmethod
    def _next(stage):
        mp={LifecycleStage.ACCUMULATION:(LifecycleStage.SPRING,55),LifecycleStage.SPRING:(LifecycleStage.TEST,78),LifecycleStage.TEST:(LifecycleStage.MARKUP,75),LifecycleStage.MARKUP:(LifecycleStage.REACCUMULATION,58),LifecycleStage.REACCUMULATION:(LifecycleStage.MARKUP,68),LifecycleStage.DISTRIBUTION:(LifecycleStage.UPTHRUST,55),LifecycleStage.UPTHRUST:(LifecycleStage.MARKDOWN,78),LifecycleStage.MARKDOWN:(LifecycleStage.REDISTRIBUTION,58),LifecycleStage.REDISTRIBUTION:(LifecycleStage.MARKDOWN,68),LifecycleStage.EXHAUSTION:(LifecycleStage.ACCUMULATION,50),LifecycleStage.CONTINUATION:(LifecycleStage.CONTINUATION,52)}
        return mp.get(stage,(None,0))
    def analyze(self,ohlcv:pd.DataFrame,structure_data:Mapping[str,Any]|None=None)->MicrostructureEvidence:
        f=self._frame(ohlcv); s=dict(structure_data or {})
        if len(f)<50: return MicrostructureEvidence(25,LifecycleStage.UNKNOWN,20,explanation=('Dữ liệu dưới 50 nến.',),evidence=('INSUFFICIENT_HISTORY',),metadata={'bars':len(f)})
        hist=f.iloc[-31:-1]; cur=f.iloc[-1]; close=self._f(cur.close); op=self._f(cur.open); hi=self._f(cur.high); lo=self._f(cur.low); vol=self._f(cur.volume)
        support=self._f(s.get('support',hist.low.min()),hist.low.min()); resistance=self._f(s.get('resistance',hist.high.max()),hist.high.max())
        av=max(self._f(hist.volume.mean(),1),1e-12); vr=vol/av; rng=max(hi-lo,1e-12); lw=max(0,min(op,close)-lo)/rng; uw=max(0,hi-max(op,close))/rng
        atr=max(self._f((hist.high-hist.low).rolling(14).mean().iloc[-1]),close*.002,1e-12); ema20=f.close.ewm(span=20,adjust=False).mean(); ema50=f.close.ewm(span=50,adjust=False).mean(); slope=(ema20.iloc[-1]-ema20.iloc[-6])/atr; dist=(close-ema20.iloc[-1])/atr
        rh=self._f(hist.high.max()); rl=self._f(hist.low.min()); width=max(rh-rl,1e-12); rangep=width/max(close,1e-12)*100; nearlo=(close-rl)/width<=.30; nearhi=(rh-close)/width<=.30
        text=' '.join(str(s.get(k,'')) for k in ('liquidity_event','wyckoff_signal','wyckoff_test','effort_result')).lower()
        spring=(lo<support and close>support and lw>=.35) or 'spring' in text or 'quét đáy' in text
        up=(hi>resistance and close<resistance and uw>=.35) or 'upthrust' in text or 'quét đỉnh' in text
        exp=[]; ev=[]
        if 'test after spring' in text or s.get('wyckoff_test_long'):
            stage=LifecycleStage.TEST; score=86; quality=72; exp=['Test sau Spring được xác nhận.']; ev=['TEST_AFTER_SPRING','SUPPLY_CONTRACTION']
        elif 'test after upthrust' in text or s.get('wyckoff_test_short'):
            stage=LifecycleStage.TEST; score=84; quality=70; exp=['Test sau Upthrust được xác nhận.']; ev=['TEST_AFTER_UPTHRUST','DEMAND_CONTRACTION']
        elif spring:
            stage=LifecycleStage.SPRING; bonus=12 if vr<=.8 else (8 if vr>=1.25 else 0); score=76+bonus; quality=55+min(25,lw*35)+bonus; exp=['Spring: quét dưới hỗ trợ rồi đóng lại phía trên.']; ev=['LIQUIDITY_SWEEP_LOW','SILENT_SPRING' if vr<=.8 else 'HIGH_VOLUME_ABSORPTION']
        elif up:
            stage=LifecycleStage.UPTHRUST; bonus=12 if vr<=.8 else (8 if vr>=1.25 else 0); score=74+bonus; quality=53+min(25,uw*35)+bonus; exp=['Upthrust: quét trên kháng cự rồi đóng lại phía dưới.']; ev=['LIQUIDITY_SWEEP_HIGH','SILENT_UPTHRUST' if vr<=.8 else 'HIGH_VOLUME_DISTRIBUTION']
        elif (close>rh+.1*atr or 'breakout xác nhận' in text or 'sos' in text) and slope>0:
            stage=LifecycleStage.MARKUP; score=76+min(12,max(0,slope)*4); quality=60+min(20,max(0,slope)*6); exp=['Markup: BOS/SOS tăng với EMA20 dốc lên.']; ev=['BULLISH_BOS']
        elif (close<rl-.1*atr or 'breakdown xác nhận' in text or 'sow' in text) and slope<0:
            stage=LifecycleStage.MARKDOWN; score=76+min(12,abs(slope)*4); quality=60+min(20,abs(slope)*6); exp=['Markdown: BOS/SOW giảm với EMA20 dốc xuống.']; ev=['BEARISH_BOS']
        elif rangep<=8 and abs(slope)<=1.5 and nearlo:
            stage=LifecycleStage.ACCUMULATION; score=68; quality=60; exp=['Accumulation: range nén gần đáy.']; ev=['RANGE_COMPRESSION','LOW_RANGE_LOCATION']
        elif rangep<=8 and abs(slope)<=1.5 and nearhi:
            stage=LifecycleStage.DISTRIBUTION; score=66; quality=58; exp=['Distribution: range nén gần đỉnh.']; ev=['RANGE_COMPRESSION','HIGH_RANGE_LOCATION']
        elif slope>.8 and abs(dist)<=1.5 and close>ema50.iloc[-1]:
            stage=LifecycleStage.REACCUMULATION; score=67; quality=62; exp=['Reaccumulation trong xu hướng tăng.']; ev=['UPTREND_INTACT']
        elif slope<-.8 and abs(dist)<=1.5 and close<ema50.iloc[-1]:
            stage=LifecycleStage.REDISTRIBUTION; score=67; quality=62; exp=['Redistribution trong xu hướng giảm.']; ev=['DOWNTREND_INTACT']
        elif abs(dist)>=4 and (vr>=1.8 or abs(close-op)/rng<=.3):
            stage=LifecycleStage.EXHAUSTION; score=72; quality=65; exp=['Exhaustion: giá quá xa EMA20, Effort-vs-Result yếu.']; ev=['EXTENSION','EFFORT_RESULT_DIVERGENCE']
        else:
            stage=LifecycleStage.CONTINUATION; score=52+min(12,abs(slope)*3); quality=50; exp=['Chưa có bằng chứng chuyển pha đủ mạnh.']; ev=['NO_CONFIRMED_TRANSITION']
        nxt,prob=self._next(stage); prob=min(100,prob+max(0,quality-60)*.25); exp.append(f'Phase quality {quality:.1f}/100.');
        if nxt: exp.append(f'Next probable phase: {nxt.value} ({prob:.0f}%).')
        return MicrostructureEvidence(score,stage,quality,0,nxt,prob,tuple(exp),tuple(ev),{'bars':len(f),'support':support,'resistance':resistance,'current_price':close,'volume_ratio':vr,'range_pct':rangep,'ema20_slope_atr':slope,'distance_ema20_atr':dist,'lower_wick_ratio':lw,'upper_wick_ratio':uw})
