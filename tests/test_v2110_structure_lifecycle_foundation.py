import numpy as np, pandas as pd, pytest
from dvs_ai.engines.microstructure import LifecycleStage,StructureLifecycleEngine,FootprintOrchestrator
def frame(closes,volumes=None,down=False,up=False):
 c=np.asarray(closes,float); n=len(c); v=np.asarray(volumes,float) if volumes is not None else np.full(n,100.); o=np.r_[c[0],c[:-1]]; h=np.maximum(o,c)+.25; l=np.minimum(o,c)-.25
 if down:l[-1]=l[:-1].min()-1
 if up:h[-1]=h[:-1].max()+1
 return pd.DataFrame({'open':o,'high':h,'low':l,'close':c,'volume':v})
def test_short_history_unknown(): assert StructureLifecycleEngine().analyze(frame(np.linspace(100,101,30)),{}).stage==LifecycleStage.UNKNOWN
def test_spring():
 d=frame(np.r_[np.linspace(105,100,59),100.4],down=True); out=StructureLifecycleEngine().analyze(d,{'support':d.low.iloc[:-1].min()}); assert out.stage==LifecycleStage.SPRING and 'LIQUIDITY_SWEEP_LOW' in out.evidence and out.next_stage==LifecycleStage.TEST
def test_silent_spring():
 d=frame(np.r_[np.linspace(103,100,59),100.3],np.r_[np.full(59,100.),50.],down=True); out=StructureLifecycleEngine().analyze(d,{'support':d.low.iloc[:-1].min()}); assert 'SILENT_SPRING' in out.evidence
def test_upthrust():
 d=frame(np.r_[np.linspace(95,100,59),99.7],up=True); out=StructureLifecycleEngine().analyze(d,{'resistance':d.high.iloc[:-1].max()}); assert out.stage==LifecycleStage.UPTHRUST
def test_test_priority(): assert StructureLifecycleEngine().analyze(frame(np.linspace(98,101,60)),{'wyckoff_test':'TEST AFTER SPRING'}).stage==LifecycleStage.TEST
def test_immutable():
 out=StructureLifecycleEngine().analyze(frame(np.linspace(100,101,60)),{}); 
 with pytest.raises(TypeError): out.metadata['x']=1
def test_aliases(): assert StructureLifecycleEngine().analyze(frame(np.linspace(100,101,60)).rename(columns={'open':'o','high':'h','low':'l','close':'c','volume':'v'}),{}).stage is not None
def test_footprint_pipeline_remains_evidence_only():
 r=FootprintOrchestrator().analyze(frame(np.linspace(100,101,60)),{})
 assert 0 <= r['composite'].score <= 100
 assert r['order_block'].metadata['implemented'] is True
 assert r['fvg'].metadata['implemented'] is True
 assert r['bos_choch'].metadata['implemented'] is True
 assert r['liquidity_sweep'].metadata['implemented'] is True
 assert r['absorption'].metadata['implemented'] is False
 assert r['position_building'].metadata['implemented'] is True
