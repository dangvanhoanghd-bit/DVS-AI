from __future__ import annotations
import pandas as pd
from .base import MicrostructureEvidence
from .base_engine import EvidenceEngine
class LiquiditySweepEngine(EvidenceEngine):
    @staticmethod
    def _normalise(df):
        out=df.rename(columns={'o':'open','h':'high','l':'low','c':'close','v':'volume'}).copy()
        for c in ('open','high','low','close','volume'):
            if c not in out.columns: raise ValueError(f'Missing OHLCV column: {c}')
            out[c]=pd.to_numeric(out[c],errors='coerce')
        return out.dropna().reset_index(drop=True)
    def analyze(self,ohlcv,context):
        d=self._normalise(ohlcv)
        if len(d)<40: return MicrostructureEvidence(score=20,phase_quality=15,explanation=('Dữ liệu quá ít cho Liquidity V3.',),evidence=('INSUFFICIENT_SWEEP_HISTORY',),metadata={'implemented':True})
        h=d.iloc[-31:-1]; c=d.iloc[-1]; high=float(h.high.max()); low=float(h.low.min()); close=float(c.close); tol=max(close,1e-12)*.0015
        eh=sum(abs(float(x)-high)<=tol for x in h.high); el=sum(abs(float(x)-low)<=tol for x in h.low)
        rng=max(float(c.high-c.low),1e-12); uw=max(0,float(c.high)-max(float(c.open),close)); lw=max(0,min(float(c.open),close)-float(c.low)); vr=float(c.volume)/max(float(h.volume.mean()),1e-12)
        sh=float(c.high)>high and close<high; sl=float(c.low)<low and close>low; void=abs(close-float(c.open))/rng>=.75 and vr>=1.25
        if sh or sl:
            bull=sl; wr=(lw if bull else uw)/rng; pool=el if bull else eh; stop=pool>=2 and wr>=.35
            score=min(100,58+wr*24+min(12,max(0,vr-1)*10)+min(10,pool*2.5)); ev=['LIQUIDITY_SWEEP_LOW' if bull else 'LIQUIDITY_SWEEP_HIGH','SELL_SIDE_LIQUIDITY' if bull else 'BUY_SIDE_LIQUIDITY','LIQUIDITY_GRAB']
            if stop: ev.append('STOP_HUNT')
            if bull and el>=2: ev.append('EQUAL_LOW_SWEEP')
            if not bull and eh>=2: ev.append('EQUAL_HIGH_SWEEP')
            return MicrostructureEvidence(score=score,phase_quality=score,explanation=(f'{ev[0]} with close-back-inside confirmation.',f'Equal pool {pool}; wick {wr:.2f}; volume {vr:.2f}.'),evidence=tuple(ev),metadata={'implemented':True,'direction':'BULLISH' if bull else 'BEARISH','reference_high':high,'reference_low':low,'equal_high_count':eh,'equal_low_count':el,'stop_hunt':stop,'liquidity_void':void,'volume_ratio':vr})
        ev=[]
        if eh>=2: ev.append('BUY_SIDE_LIQUIDITY_POOL')
        if el>=2: ev.append('SELL_SIDE_LIQUIDITY_POOL')
        if void: ev.append('LIQUIDITY_VOID')
        if not ev: ev=['NO_LIQUIDITY_SWEEP']
        q=min(55,25+min(15,eh*3)+min(15,el*3)+(10 if void else 0))
        return MicrostructureEvidence(score=q,phase_quality=q,explanation=('Liquidity pools detected; no confirmed sweep yet.',f'Equal highs {eh}; equal lows {el}; void={void}.'),evidence=tuple(ev),metadata={'implemented':True,'equal_high_count':eh,'equal_low_count':el,'liquidity_void':void})
