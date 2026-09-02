from __future__ import annotations
from dataclasses import dataclass
from .report_models import RecommendationResult, StageState

@dataclass(frozen=True)
class RecommendationStateInput:
    integrity_state: StageState
    observability_state: str
    power_state: str
    confidence_stage: StageState
    conclusion_state: str

class RecommendationMapper:
    """A pure state mapper: no numeric inference, context object, storage, or configuration."""
    @staticmethod
    def build(payload: RecommendationStateInput) -> RecommendationResult:
        if payload.integrity_state is not StageState.PASS:
            return RecommendationResult(StageState.SKIPPED, "ANALYSIS_ABORTED", "integrity gate failed", False)
        if payload.observability_state != "OBSERVABLE" or payload.power_state != "POWERED":
            return RecommendationResult(StageState.SKIPPED, "COLLECT_MORE_DATA", "observable/power hard gate not satisfied", False)
        if payload.confidence_stage is not StageState.PASS:
            return RecommendationResult(StageState.SKIPPED, "CONTINUE_PAPER", "confidence analysis not available", False)
        mapping = {
            "SUPPORTED": "READY_FOR_MANUAL_REVIEW",
            "UNSUPPORTED": "REVIEW_REQUIRED",
            "NO_ACTIONABLE_ISSUE_DETECTED": "CONTINUE_PAPER",
        }
        recommendation = mapping.get(payload.conclusion_state, "CONTINUE_PAPER")
        # Sua loi: `actionable` tung bi hardcode False ngay ca o nhanh PASS
        # thanh cong (ke ca khi recommendation="READY_FOR_MANUAL_REVIEW"),
        # khien field nay luon False bat ke ket luan that la gi. Khong gay
        # rui ro an toan (khong noi nao khac dua vao actionable=True de cho
        # phep hanh dong them), nhung lam mat y nghia field. Gio actionable
        # dung phan anh: True khi co ket luan CO Y NGHIA can con nguoi xem
        # xet (SUPPORTED hoac UNSUPPORTED), khac NO_ACTIONABLE_ISSUE_DETECTED.
        actionable = payload.conclusion_state in {"SUPPORTED", "UNSUPPORTED"}
        return RecommendationResult(StageState.PASS, recommendation, "mapped from verified confidence state", actionable)
