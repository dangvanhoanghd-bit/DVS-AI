from __future__ import annotations

from dvs_ai.governance.paper_authority_handover import PaperAuthorityHandoverProfile
from dvs_ai.services.core_shadow_agreement_service import (
    AGREEMENT_FULL,
    CoreShadowAgreementStore,
    ShadowAgreementObservation,
)
from dvs_ai.services.qualification_report_service import QualificationReportService


def _append(store, index: int, legacy: str, unified: str) -> None:
    store.append(ShadowAgreementObservation(
        request_id=f"r-{index}", symbol="BTC/USDT", analysis_revision=index,
        legacy_action=legacy, unified_action=unified, agreement=AGREEMENT_FULL,
        ledger_verified=True, confidence=50.0, regime="TREND", phase="MARKUP",
        timeframe="15m", observed_at=f"2026-07-20T00:{index % 60:02d}:00+00:00",
    ))


def test_trivial_no_action_agreement_cannot_reach_governance(tmp_path):
    store = CoreShadowAgreementStore(tmp_path / "q.sqlite3")
    for index in range(500):
        _append(store, index, "NO_ACTION", "NO_ACTION")
    metrics = store.metrics()
    assert metrics.total_cycles == 500
    assert metrics.full_agreement_ratio == 1.0
    assert metrics.actionable_cycles == 0
    assert metrics.decision_agreement_confidence is None
    assert metrics.qualification_status == "ACTIONABLE_EVIDENCE_INSUFFICIENT"
    report = QualificationReportService(store, build_version="4.0.5").build_snapshot()
    assert report.evidence_observability == "UNOBSERVABLE"
    assert report.governance_recommendation == "NOT_READY"


def test_actionable_count_and_ratio_are_both_hard_gates(tmp_path):
    profile = PaperAuthorityHandoverProfile(
        minimum_parallel_cycles=100,
        minimum_actionable_count=30,
        minimum_actionable_ratio=0.05,
    )
    store = CoreShadowAgreementStore(tmp_path / "q.sqlite3")
    for index in range(100):
        action = "BUY" if index < 29 else "NO_ACTION"
        _append_with_profile(store, index, action, action, profile)
    metrics = store.metrics(profile)
    assert metrics.required_actionable_cycles == 30
    assert metrics.actionable_gap == 1
    assert metrics.qualification_status == "ACTIONABLE_EVIDENCE_INSUFFICIENT"
    _append_with_profile(store, 1000, "SELL", "SELL", profile)
    metrics = store.metrics(profile)
    assert metrics.actionable_cycles == 30
    assert metrics.actionable_gap == 0
    assert metrics.decision_agreement_confidence == 1.0
    assert metrics.qualification_status == "READY_FOR_GOVERNANCE_REVIEW"


def _append_with_profile(store, index, legacy, unified, profile):
    store.append(ShadowAgreementObservation(
        request_id=f"p-{index}", symbol="ETH/USDT", analysis_revision=index,
        legacy_action=legacy, unified_action=unified, agreement=AGREEMENT_FULL,
        ledger_verified=True, confidence=60.0, regime="RANGE", phase="ACCUMULATION",
        timeframe="15m", observed_at="2026-07-20T00:00:00+00:00",
    ), profile)


def test_main_window_uses_real_regime_and_phase_fields():
    source = open("dvs_ai/ui/main_window.py", encoding="utf-8").read()
    assert 'getattr(getattr(analysis, "regime", None), "regime", "UNKNOWN")' in source
    assert 'getattr(analysis, "phase_summary", "UNKNOWN")' in source
    assert 'getattr(analysis, "market_regime"' not in source[source.index("def _submit_qualification_batch"):source.index("def _on_qualification_batch_progress")]
