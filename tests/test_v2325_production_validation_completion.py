from dataclasses import replace
from pathlib import Path
import tempfile
import pytest

from dvs_ai.services.evidence_analysis.executive_report import ExecutiveReportGenerator, EvidenceReportStore
from dvs_ai.services.evidence_analysis.protocol_enforcement import EvidenceProtocolEnforcer
from dvs_ai.services.evidence_analysis.report_models import *


def result(*, integrity=StageState.PASS, conclusion="SUPPORTED", confidence_state=StageState.PASS, rec="READY_FOR_MANUAL_REVIEW", actionable=False):
    return EvidenceAnalysisResult(
        "1.0", "BULL_LONG_SHADOW_FULL",
        IntegrityReport(integrity, (("schema","PASS"),), ()),
        EvidenceReport(StageState.PASS if integrity==StageState.PASS else StageState.SKIPPED, 60, 60, 60, .2, .6, (.1,.3)),
        ConfidenceReport(confidence_state, conclusion, "HIGH", .1, .3, "ok", .99, .2, 60),
        ActionableGapReport(StageState.PASS, (), "none"),
        RecommendationResult(StageState.PASS if integrity==StageState.PASS else StageState.ANALYSIS_ABORTED, rec, "mapped", actionable),
    )


def test_report_is_deterministic_and_tamper_evident():
    report=ExecutiveReportGenerator.build(result(), generated_at="2026-01-01T00:00:00+00:00")
    assert report.verify()
    assert ExecutiveReportGenerator.build(result(), generated_at=report.generated_at).artifact_hash==report.artifact_hash
    assert not replace(report, context_id="FAKE").verify()


def test_report_store_is_append_only_and_multiformat():
    report=ExecutiveReportGenerator.build(result(), generated_at="2026-01-01T00:00:00+00:00")
    with tempfile.TemporaryDirectory() as d:
        store=EvidenceReportStore(d); paths=store.persist(report)
        assert set(paths)=={"json","md","html"}
        assert store.persist(report)==paths
        Path(paths["json"]).write_text("tampered", encoding="utf-8")
        with pytest.raises(FileExistsError): store.persist(report)


def test_integrity_failure_cannot_leak_downstream():
    bad=result(integrity=StageState.FAIL, conclusion="SUPPORTED", confidence_state=StageState.PASS, rec="READY_FOR_MANUAL_REVIEW", actionable=True)
    audit=EvidenceProtocolEnforcer.verify_result(bad)
    assert audit.state=="FAIL"
    assert any("Integrity failure" in x for x in audit.issues)


def test_underpowered_cannot_be_actionable():
    bad=result(conclusion="OBSERVABLE_BUT_UNDERPOWERED", rec="READY_FOR_MANUAL_REVIEW", actionable=True)
    audit=EvidenceProtocolEnforcer.verify_result(bad)
    assert audit.state=="FAIL"
    good=result(conclusion="OBSERVABLE_BUT_UNDERPOWERED", rec="COLLECT_MORE_DATA", actionable=False)
    assert EvidenceProtocolEnforcer.verify_result(good).state=="PASS"


def test_manual_review_requires_supported_confidence():
    assert EvidenceProtocolEnforcer.verify_result(result(conclusion="NO_ACTIONABLE_ISSUE_DETECTED")).state=="FAIL"


def test_source_isolation_audit_passes():
    base=Path("dvs_ai/services/evidence_analysis")
    audit=EvidenceProtocolEnforcer.audit_source(base)
    assert audit.state=="PASS", audit.issues
