import json
from pathlib import Path
from dvs_ai.services.quantum_optimizer import QuantumOptimizer, OptimizationParams
from dvs_ai.services.truth_trend_store import TruthTrendStore


def cfg(path):
    path.write_text(json.dumps({
        'main_confidence':68,'main_entry':62,'main_risk_max':50,'main_rr_min':1.8,
        'shadow_confidence':45,'shadow_entry':45,'shadow_risk_max':65,'shadow_rr_min':1.4,
        'evidence_fusion_family_weights':{'TIMING':.22,'ENTRY':.18,'ORDER_FLOW':.32,'DIRECTION':.16,'MARKET':.12},
    }))

def test_main_dimensions_are_frozen_across_search_operators(tmp_path):
    c=tmp_path/'c.json'; cfg(c); o=QuantumOptimizer(str(tmp_path/'x.db'),str(c),seed=1)
    base=o._base_params(); rnd=o._random_params(base); mut=o._mutate(base); cross=o._crossover(base,rnd)
    for p in (rnd,mut,cross):
        assert (p.main_confidence,p.main_entry,p.main_risk_max,p.main_rr_min)==(68,62,50,1.8)

def test_candidate_rejects_main_keys_and_normalizes_weight_proposal(tmp_path):
    c=tmp_path/'c.json'; cfg(c); before=c.read_text(); o=QuantumOptimizer(str(tmp_path/'x.db'),str(c))
    best={**vars(OptimizationParams()),'main_confidence':99,'weight_order_flow':.50}
    out=o.create_shadow_candidate({'safe_to_apply_shadow':True,'best_params':best},str(tmp_path/'cand.json'))
    assert 'main_confidence' in out['rejected_main_keys']
    assert out['main_config_mutated'] is False and c.read_text()==before
    weights=out['evidence_fusion_family_weights']
    assert abs(sum(weights.values())-1.0)<1e-5 and weights['ORDER_FLOW']<=.40

def test_shadow_fusion_weights_change_snapshot_selection_without_main_mutation():
    from dvs_ai.services.quantum_optimizer import ClosedTrade
    trade=ClosedTrade('x','SHADOW',60,60,20,2,1,'', (90,30,20,20,20))
    a=OptimizationParams(shadow_entry=45,weight_timing=.40,weight_entry=.15,weight_order_flow=.15,weight_direction=.15,weight_market=.15).clamp()
    b=OptimizationParams(shadow_entry=45,weight_timing=.05,weight_entry=.20,weight_order_flow=.30,weight_direction=.25,weight_market=.20).clamp()
    assert QuantumOptimizer._shadow_fusion_score(trade,a)>QuantumOptimizer._shadow_fusion_score(trade,b)

def test_truth_trend_store_is_append_only_and_ordered(tmp_path):
    store=TruthTrendStore(str(tmp_path/'truth.db'))
    store.append('DRIFT','STABLE',{'brier_delta':.01},'2026-01-01T00:00:00+00:00')
    store.append('DRIFT','WATCH',{'brier_delta':.03},'2026-01-02T00:00:00+00:00')
    rows=store.recent('DRIFT',10)
    assert [r['state'] for r in rows]==['STABLE','WATCH']
    assert rows[-1]['brier_delta']==.03

def test_dashboard_contains_real_persisted_trend_charts():
    source=Path('dvs_ai/ui/truth_dashboard.py').read_text()
    assert 'class TruthTrendChart(QWidget)' in source
    assert 'TruthTrendStore' in source
    assert 'Calibration Drift · Brier/ECE/PSI' in source
    assert 'Evidence Reliability History' in source
