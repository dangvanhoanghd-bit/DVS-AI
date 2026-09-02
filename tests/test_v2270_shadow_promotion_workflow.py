import json
from pathlib import Path

import pytest

from dvs_ai.services.quantum_optimizer import ClosedTrade, QuantumOptimizer
from dvs_ai.services.quantum_candidate_backtest import CandidateBacktestService
from dvs_ai.services.shadow_promotion_service import ShadowPromotionService


def config(path: Path):
    raw = {
        "main_confidence": 70, "main_entry": 65, "main_risk_max": 50, "main_rr_min": 1.8,
        "shadow_confidence": 45, "shadow_entry": 45, "shadow_risk_max": 65, "shadow_rr_min": 1.4,
        "execution_mode": "PAPER", "execution_live_enabled": False,
        "evidence_fusion_family_weights": {"TIMING": .22, "ENTRY": .18, "ORDER_FLOW": .32, "DIRECTION": .16, "MARKET": .12},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return raw


def rows(n=120):
    out=[]
    for i in range(n):
        win = i % 3 != 0
        out.append(ClosedTrade(
            created_at=f"2026-01-{(i%28)+1:02d}T00:00:00Z", lab="SHADOW",
            confidence=70, entry_score=70, risk_score=30, rr_planned=2.0,
            r_multiple=1.2 if win else -1.0, setup_tags="",
            evidence_scores=(70,70,70,70,70),
        ))
    return out


def candidate():
    return {
        "schema":"DVS_QUANTUM_SHADOW_CANDIDATE_V2",
        "human_approval_required":True, "main_config_mutated":False,
        "candidate":{"shadow_confidence":46,"shadow_entry":46,"shadow_risk_max":64,"shadow_rr_min":1.5},
        "evidence_fusion_family_weights":{"TIMING":.20,"ENTRY":.20,"ORDER_FLOW":.32,"DIRECTION":.16,"MARKET":.12},
    }


def test_backtest_is_chronological_truth_qualified_and_observe_only(tmp_path, monkeypatch):
    cfg=tmp_path/'config.json'; config(cfg)
    opt=QuantumOptimizer(db_path=str(tmp_path/'none.db'), config_path=str(cfg), min_closed=80)
    monkeypatch.setattr(opt, '_load_closed', lambda: rows())
    opt._last_training_audit={"eligible":120,"total_closed":120}
    report=CandidateBacktestService(opt, min_selected=12).simulate(candidate())
    assert report['state']=='PASS'
    assert report['holdout_samples']==36
    assert json.loads(cfg.read_text())['shadow_confidence']==45


def test_promotion_requires_exact_human_confirmation_and_pass(tmp_path):
    cfg=tmp_path/'config.json'; before=config(cfg)
    service=ShadowPromotionService(str(cfg), str(tmp_path/'audit'))
    with pytest.raises(PermissionError):
        service.apply(candidate(), {"state":"PASS","approved_for_human_review":True}, human_confirmation="YES")
    with pytest.raises(ValueError):
        service.apply(candidate(), {"state":"REJECTED","approved_for_human_review":False}, human_confirmation="APPLY TO SHADOW")
    assert json.loads(cfg.read_text())==before


def test_promotion_changes_shadow_only_and_creates_backup(tmp_path):
    cfg=tmp_path/'config.json'; before=config(cfg)
    service=ShadowPromotionService(str(cfg), str(tmp_path/'audit'))
    audit=service.apply(candidate(), {"state":"PASS","approved_for_human_review":True}, human_confirmation="APPLY TO SHADOW")
    after=json.loads(cfg.read_text())
    assert after['shadow_confidence']==46
    assert after['main_confidence']==before['main_confidence']
    assert after['execution_live_enabled'] is False
    assert Path(audit['backup_path']).exists()
    assert Path(audit['audit_path']).exists()
    assert audit['main_unchanged'] is True


def test_main_key_injection_is_rejected(tmp_path):
    cfg=tmp_path/'config.json'; config(cfg)
    bad=candidate(); bad['candidate']['main_confidence']=1
    service=ShadowPromotionService(str(cfg), str(tmp_path/'audit'))
    with pytest.raises(ValueError):
        service.apply(bad, {"state":"PASS","approved_for_human_review":True}, human_confirmation="APPLY TO SHADOW")
