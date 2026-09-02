from __future__ import annotations

from dataclasses import replace

from dvs_ai.services.evidence_analysis.protocol_enforcement import EvidenceProtocolEnforcer
from dvs_ai.services.evidence_analysis.recommendation_mapper import (
    RecommendationMapper,
    RecommendationStateInput,
)
from dvs_ai.services.evidence_analysis.report_models import (
    ActionableGapReport,
    ConfidenceReport,
    EvidenceAnalysisResult,
    EvidenceReport,
    IntegrityReport,
    RecommendationResult,
    StageState,
)


def _payload(conclusion: str) -> RecommendationStateInput:
    return RecommendationStateInput(
        integrity_state=StageState.PASS,
        observability_state="OBSERVABLE",
        power_state="POWERED",
        confidence_stage=StageState.PASS,
        conclusion_state=conclusion,
    )


def _result(recommendation: RecommendationResult, conclusion: str) -> EvidenceAnalysisResult:
    return EvidenceAnalysisResult(
        "1.0",
        "BULL_LONG_SHADOW_FULL",
        IntegrityReport(StageState.PASS, (("schema", "PASS"),), ()),
        EvidenceReport(StageState.PASS, 60, 60, 60, 0.2, 0.6, (0.1, 0.3)),
        ConfidenceReport(StageState.PASS, conclusion, "HIGH", 0.1, 0.3, "ok", 0.99, 0.2, 60),
        ActionableGapReport(StageState.PASS, (), "none"),
        recommendation,
    )


def test_supported_and_unsupported_are_actionable_for_human_review():
    supported = RecommendationMapper.build(_payload("SUPPORTED"))
    unsupported = RecommendationMapper.build(_payload("UNSUPPORTED"))
    assert supported.recommendation == "READY_FOR_MANUAL_REVIEW"
    assert supported.actionable is True
    assert unsupported.recommendation == "REVIEW_REQUIRED"
    assert unsupported.actionable is True


def test_no_actionable_issue_remains_non_actionable():
    result = RecommendationMapper.build(_payload("NO_ACTIONABLE_ISSUE_DETECTED"))
    assert result.recommendation == "CONTINUE_PAPER"
    assert result.actionable is False


def test_nonpowered_gate_remains_non_actionable():
    payload = replace(_payload("SUPPORTED"), power_state="UNPOWERED")
    result = RecommendationMapper.build(payload)
    assert result.recommendation == "COLLECT_MORE_DATA"
    assert result.actionable is False


def test_enforcer_catches_ready_review_false_actionable_regression():
    broken = RecommendationResult(
        StageState.PASS,
        "READY_FOR_MANUAL_REVIEW",
        "mapped",
        False,
    )
    audit = EvidenceProtocolEnforcer.verify_result(_result(broken, "SUPPORTED"))
    assert audit.state == "FAIL"
    assert "Manual review readiness not marked actionable" in audit.issues


def test_enforcer_catches_review_required_false_actionable_regression():
    broken = RecommendationResult(
        StageState.PASS,
        "REVIEW_REQUIRED",
        "mapped",
        False,
    )
    audit = EvidenceProtocolEnforcer.verify_result(_result(broken, "UNSUPPORTED"))
    assert audit.state == "FAIL"
    assert "Review-required recommendation not marked actionable" in audit.issues


def test_enforcer_catches_continue_paper_true_actionable_regression():
    broken = RecommendationResult(
        StageState.PASS,
        "CONTINUE_PAPER",
        "mapped",
        True,
    )
    audit = EvidenceProtocolEnforcer.verify_result(
        _result(broken, "NO_ACTIONABLE_ISSUE_DETECTED")
    )
    assert audit.state == "FAIL"
    assert "Continue-paper recommendation incorrectly marked actionable" in audit.issues
