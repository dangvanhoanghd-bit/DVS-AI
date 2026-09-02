from __future__ import annotations
from enum import Enum
import pandas as pd
from .base import MicrostructureEvidence
from .base_engine import EvidenceEngine
class StructureBreakType(str, Enum):
    NONE='NONE'; BULLISH_BOS='BULLISH_BOS'; BEARISH_BOS='BEARISH_BOS'; BULLISH_CHOCH='BULLISH_CHOCH'; BEARISH_CHOCH='BEARISH_CHOCH'; FAKE_BREAK='FAKE_BREAK'
class BosChochEngine(EvidenceEngine):
    @staticmethod
    def _normalise(df):
        out=df.rename(columns={'o':'open','h':'high','l':'low','c':'close','v':'volume'}).copy()
        for c in ('open','high','low','close','volume'):
            if c not in out.columns: raise ValueError(f'Missing OHLCV column: {c}')
            out[c]=pd.to_numeric(out[c],errors='coerce')
        return out.dropna().reset_index(drop=True)
    @staticmethod
    def _clamp(x): return max(0.0,min(100.0,float(x)))
    def analyze(self,ohlcv,context):
        d=self._normalise(ohlcv)
        if len(d)<60: return MicrostructureEvidence(score=20,phase_quality=15,explanation=('Dữ liệu quá ít cho BOS/CHOCH V3.',),evidence=('INSUFFICIENT_STRUCTURE_HISTORY',),metadata={'implemented':True})
        close=float(d.close.iloc[-1]); prev=float(d.close.iloc[-2]); internal=d.iloc[-13:-1]; external=d.iloc[-41:-13]
        ih,il=float(internal.high.max()),float(internal.low.min()); eh,el=float(external.high.max()),float(external.low.min())
        up=ih>eh and il>el; down=ih<eh and il<el
        bi=close>ih and prev<=ih; si=close<il and prev>=il; be=close>eh and prev<=eh; se=close<el and prev>=el
        wu=float(d.high.iloc[-1])>max(ih,eh) and close<=max(ih,eh); wd=float(d.low.iloc[-1])<min(il,el) and close>=min(il,el)
        if be: event=StructureBreakType.BULLISH_CHOCH if down else StructureBreakType.BULLISH_BOS; scope='EXTERNAL'; level=eh
        elif se: event=StructureBreakType.BEARISH_CHOCH if up else StructureBreakType.BEARISH_BOS; scope='EXTERNAL'; level=el
        elif bi: event=StructureBreakType.BULLISH_CHOCH if down else StructureBreakType.BULLISH_BOS; scope='INTERNAL'; level=ih
        elif si: event=StructureBreakType.BEARISH_CHOCH if up else StructureBreakType.BEARISH_BOS; scope='INTERNAL'; level=il
        elif wu or wd: event=StructureBreakType.FAKE_BREAK; scope='FAILED'; level=max(ih,eh) if wu else min(il,el)
        else: return MicrostructureEvidence(score=35,phase_quality=30,explanation=('Chưa có BOS/CHOCH đóng nến xác nhận.',),evidence=('NO_CONFIRMED_STRUCTURE_BREAK',),metadata={'implemented':True,'internal_high':ih,'internal_low':il,'external_high':eh,'external_low':el})
        avg=max(float((internal.high-internal.low).mean()),close*.002); distance=abs(close-level)/avg if event!=StructureBreakType.FAKE_BREAK else 0
        cs=self._clamp(distance*45); vr=float(d.volume.iloc[-1])/max(float(internal.volume.mean()),1e-12); vs=self._clamp((vr-.7)*55)
        if event==StructureBreakType.FAKE_BREAK: quality='FAILED'; score=25
        else:
            score=self._clamp(55+.25*cs+.20*vs+(8 if scope=='EXTERNAL' else 0)); quality='STRONG' if score>=75 else 'WEAK' if score<60 else 'CONFIRMED'
        tag=f'{scope}_{event.value}' if event!=StructureBreakType.FAKE_BREAK else 'FAILED_BOS'
        return MicrostructureEvidence(score=score,phase_quality=score,explanation=(f'{tag} · quality {quality}.',f'Close strength {cs:.1f}; volume ratio {vr:.2f}.'),evidence=(event.value,tag,f'BOS_QUALITY_{quality}'),metadata={'implemented':True,'event':event.value,'scope':scope,'quality':quality,'trend_up_before':up,'trend_down_before':down,'break_level':level,'close_strength':cs,'volume_ratio':vr})
