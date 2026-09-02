from pathlib import Path
import numpy as np, pandas as pd
from dvs_ai.engines.microstructure.bos_choch_engine import BosChochEngine
from dvs_ai.engines.microstructure.fvg_engine import FVGEngine
from dvs_ai.engines.microstructure.liquidity_sweep_engine import LiquiditySweepEngine
def frame(n=90):
 c=np.linspace(100,101,n); return pd.DataFrame({'open':c-.1,'high':c+.3,'low':c-.3,'close':c,'volume':np.full(n,100.)})
def test_fvg_v3_metadata():
 d=frame(); d.loc[60,'high']=100; d.loc[61,['open','close','high','low','volume']]=[100.2,101.5,101.7,100.1,200]; d.loc[62,'low']=101; o=FVGEngine().analyze(d,{}); assert 'cluster_count' in o.metadata and 'untouched' in o.metadata
def test_bos_v3_scope_quality():
 d=frame(); d.loc[89,['open','close','high','low','volume']]=[101,103,103.2,100.8,220]; o=BosChochEngine().analyze(d,{}); assert o.metadata.get('scope') in ('INTERNAL','EXTERNAL','FAILED'); assert o.metadata.get('quality') in ('STRONG','CONFIRMED','WEAK','FAILED')
def test_liquidity_v3():
 d=frame(); d.loc[70:88,'low']=99; d.loc[89,['open','close','high','low','volume']]=[99.5,99.4,100.2,98.4,180]; o=LiquiditySweepEngine().analyze(d,{}); assert any(x in o.evidence for x in ('LIQUIDITY_SWEEP_LOW','SELL_SIDE_LIQUIDITY_POOL'))
def test_decision_v35():
 s=Path('dvs_ai/engines/decision_engine.py').read_text(); assert 'footprint_score < 60.0' in s and 'position_score < 48.0' in s and 'final_score >= 76.0' in s
def test_safety():
 import json; raw=json.loads(Path('config.json').read_text()); assert raw.get('auto_paper_execution_enabled',False) is False and raw.get('execution_live_enabled',False) is False
