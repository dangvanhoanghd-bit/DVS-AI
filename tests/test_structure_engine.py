import pandas as pd
from dvs_ai.engines.structure_engine import StructureEngine

def _frame(n, freq_ms, base=100.0):
    rows=[]
    for i in range(n):
        p=base+i*0.01
        rows.append([i*freq_ms,p,p+1,p-1,p+0.2,1000])
    return pd.DataFrame(rows,columns=["timestamp","open","high","low","close","volume"])

def test_structure_engine_returns_levels():
    frames={"15m":_frame(100,900000),"1d":_frame(220,86400000)}
    result=StructureEngine().analyze(frames)
    assert result.daily_high > result.daily_low
    assert result.weekly_high > result.weekly_low
    assert 0 <= result.wyckoff_score <= 100
