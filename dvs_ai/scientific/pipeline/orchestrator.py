from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from ..contracts import (
    CertificationStatus,
    RegistryStatus,
    ScientificLifecycleState,
    ScientificReasonCode,
    StabilityStatus,
    ValidationStatus,
    require_transition,
)
from .models import PipelineEvent, ScientificPipelineResult
from .stages.base import CertificationStage, EvidenceDeltaStage, RegistryStage, StabilityStage, ValidationStage
from ..ledger import ScientificLedger


class ScientificLifecyclePipeline:
    """Pure, fail-closed orchestration for the scientific lifecycle.

    Stages are dependency-injected and may not be skipped. This component does
    not import GUI, exchange, execution, runtime, or database packages.
    """

    def __init__(
        self,
        *,
        delta_stage: EvidenceDeltaStage,
        validation_stage: ValidationStage,
        stability_stage: StabilityStage,
        certification_stage: CertificationStage,
        registry_stage: RegistryStage,
        ledger: ScientificLedger | None = None,
    ) -> None:
        self._delta_stage = delta_stage
        self._validation_stage = validation_stage
        self._stability_stage = stability_stage
        self._certification_stage = certification_stage
        self._registry_stage = registry_stage
        self._ledger = ledger

    def run(self, evidence, *, run_id: str | None = None) -> ScientificPipelineResult:
        run_id = run_id or f"sci-{uuid4().hex}"
        state = ScientificLifecycleState.RAW
        events: list[PipelineEvent] = []

        def advance(target: ScientificLifecycleState, stage: str) -> None:
            nonlocal state
            before = state
            require_transition(state, target)
            state = target
            events.append(PipelineEvent(stage=stage, state=state, succeeded=True))
            if self._ledger is not None:
                self._ledger.append_transition(pipeline_run_id=run_id, stage=stage, state_before=before, state_after=state, succeeded=True)

        def fail(stage: str, *codes: str) -> ScientificPipelineResult:
            nonlocal state
            before = state
            if state is not ScientificLifecycleState.FAILED:
                require_transition(state, ScientificLifecycleState.FAILED)
                state = ScientificLifecycleState.FAILED
            normalized = tuple(codes) or (ScientificReasonCode.VALIDATION_FAILED.value,)
            events.append(PipelineEvent(stage=stage, state=state, succeeded=False, reason_codes=normalized))
            if self._ledger is not None:
                self._ledger.append_transition(pipeline_run_id=run_id, stage=stage, state_before=before, state_after=state, succeeded=False, reason_codes=normalized)
            return ScientificPipelineResult(
                run_id=run_id,
                state=state,
                evidence=evidence,
                events=tuple(events),
                reason_codes=normalized,
            )

        try:
            advance(ScientificLifecycleState.FEATURED, "feature_contract")
            advance(ScientificLifecycleState.EVIDENCE_READY, "evidence")
            delta = self._delta_stage(evidence)
            if not delta.meaningful or not delta.hard_gates_passed:
                codes = delta.reason_codes or (ScientificReasonCode.EVIDENCE_DELTA_TOO_SMALL.value,)
                result = fail("evidence_delta", *codes)
                return replace(result, evidence_delta=delta)

            validation = self._validation_stage(evidence, delta)
            if validation.status is not ValidationStatus.PASSED:
                codes = validation.reason_codes or (ScientificReasonCode.VALIDATION_FAILED.value,)
                result = fail("validation", *codes)
                return replace(result, evidence_delta=delta, validation=validation)
            advance(ScientificLifecycleState.VALIDATED, "validation")

            stable_validation = self._stability_stage(validation)
            if stable_validation.stability_status is not StabilityStatus.STABLE:
                codes = stable_validation.reason_codes or (ScientificReasonCode.STABILITY_FAILED.value,)
                result = fail("stability", *codes)
                return replace(result, evidence_delta=delta, validation=stable_validation)

            certification = self._certification_stage(stable_validation)
            if certification.status is not CertificationStatus.GRANTED:
                codes = certification.reason_codes or (ScientificReasonCode.CERTIFICATION_NOT_GRANTED.value,)
                result = fail("certification", *codes)
                return replace(result, evidence_delta=delta, validation=stable_validation, certification=certification)
            advance(ScientificLifecycleState.CERTIFIED, "certification")

            snapshot = self._registry_stage(certification)
            if snapshot.status is not RegistryStatus.REGISTERED:
                codes = snapshot.reason_codes or (ScientificReasonCode.REGISTRY_NOT_AVAILABLE.value,)
                result = fail("registry", *codes)
                return replace(
                    result,
                    evidence_delta=delta,
                    validation=stable_validation,
                    certification=certification,
                    registry_snapshot=snapshot,
                )
            advance(ScientificLifecycleState.REGISTERED, "registry")
            advance(ScientificLifecycleState.AVAILABLE, "availability")
            return ScientificPipelineResult(
                run_id=run_id,
                state=state,
                evidence=evidence,
                evidence_delta=delta,
                validation=stable_validation,
                certification=certification,
                registry_snapshot=snapshot,
                events=tuple(events),
            )
        except Exception as exc:
            code = f"{ScientificReasonCode.PIPELINE_STAGE_EXCEPTION.value}:{type(exc).__name__.upper()}"
            return fail("exception", code)
