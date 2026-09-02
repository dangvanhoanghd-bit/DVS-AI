from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from .attempt_ledger import AttemptLedger
from .holdout import HoldoutManager
from .bootstrap import cluster_bootstrap_mean
from .multiple_comparison import holm_bonferroni
from .stability import evaluate_stability
from .models import ValidationRequest, ValidationResult, ValidationState
from .walk_forward import validate_walk_forward
from dvs_ai.services.quantum_burn_in import QuantumBurnInPolicy


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class ValidationOrchestrator:
    """Fail-closed scientific validation foundation for Quantum studies."""

    def __init__(self, holdout_manager: HoldoutManager, attempt_ledger: AttemptLedger) -> None:
        self.holdout_manager = holdout_manager
        self.attempt_ledger = attempt_ledger

    def validate(self, request: ValidationRequest) -> ValidationResult:
        violations: list[str] = []
        checks: dict[str, bool] = {}

        checks["replay_verified"] = request.replay_state == "VERIFIED"
        if not checks["replay_verified"]:
            violations.append("REPLAY_NOT_VERIFIED")

        wf_violations = validate_walk_forward(request.split_method, request.folds)
        checks["walk_forward"] = not wf_violations
        violations.extend(wf_violations)

        checks["effective_n"] = request.effective_n >= request.minimum_effective_n
        if not checks["effective_n"]:
            violations.append("EFFECTIVE_N_BELOW_MINIMUM")

        # QBP-0E capability gate.  Legacy callers remain compatible when the
        # count is -1, while QBP-enabled studies fail closed for explicitly
        # requested research capabilities.
        if request.burn_in_eligible_outcomes >= 0 or request.burn_in_required_capabilities:
            required_capabilities = tuple(request.burn_in_required_capabilities)
            missing = QuantumBurnInPolicy.missing_capabilities(
                max(0, request.burn_in_eligible_outcomes), required_capabilities
            )
            checks["burn_in_capabilities"] = not missing
            violations.extend(f"BURN_IN_CAPABILITY_LOCKED:{name}" for name in missing)
        else:
            checks["burn_in_capabilities"] = True

        holdout_state = self.holdout_manager.status(request.holdout_id)
        checks["holdout_locked"] = bool(holdout_state["locked"])
        checks["holdout_unused"] = not bool(holdout_state["consumed"])
        if not checks["holdout_locked"]:
            violations.append("HOLDOUT_NOT_LOCKED")
        if not checks["holdout_unused"]:
            violations.append("HOLDOUT_ALREADY_CONSUMED")

        checks["attempt_ledger"] = self.attempt_ledger.verify()
        if not checks["attempt_ledger"]:
            violations.append("ATTEMPT_LEDGER_INVALID")

        multiple_comparison = holm_bonferroni(request.hypothesis_tests, request.family_alpha)
        stability = evaluate_stability(request.stability_observations) if request.stability_observations else None
        bootstrap = cluster_bootstrap_mean(request.bootstrap_metrics) if request.bootstrap_metrics else None

        checks["multiple_comparison"] = multiple_comparison.valid
        checks["stability"] = stability.stable if stability is not None else not request.require_statistical_diagnostics
        checks["bootstrap"] = bootstrap.valid if bootstrap is not None else not request.require_statistical_diagnostics
        if request.require_statistical_diagnostics:
            if not multiple_comparison.valid or not request.hypothesis_tests:
                violations.append("MULTIPLE_COMPARISON_INVALID")
            if stability is None or not stability.stable:
                violations.append("STABILITY_NOT_DEMONSTRATED")
            if bootstrap is None or not bootstrap.valid:
                violations.append("BOOTSTRAP_INVALID")

        # Record every validation attempt, including blocked attempts, for QG-16.
        ledger_entry = self.attempt_ledger.append(
            request.policy_scope_hash, request.study_id, request.candidate_count, 0
        )

        state = ValidationState.BLOCK if violations else ValidationState.PASS
        if state is ValidationState.PASS:
            first_fold = request.folds[0]
            self.holdout_manager.consume(
                request.holdout_id, first_fold.holdout_start, request.policy_scope_id
            )

        manifest = {
            "schema_version": "dvs-quantum-validation-statistical-v2",
            "release": "4.3.0E-2",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "state": state.value,
            "request": asdict(request),
            "checks": checks,
            "violations": violations,
            "attempt_ledger_entry_hash": ledger_entry["entry_hash"],
            "statistical_diagnostics": {
                "multiple_comparison": asdict(multiple_comparison),
                "stability": asdict(stability) if stability is not None else None,
                "bootstrap": asdict(bootstrap) if bootstrap is not None else None,
                "causal_claim_allowed": False,
            },
            "safety_boundary": {
                "decision_engine_mutation": False,
                "optimizer_authority": False,
                "recommendation_authority": False,
                "shadow_write_authority": False,
                "main_write_authority": False,
                "trade_execution_authority": False,
            },
        }
        manifest["self_sha256"] = _canonical_hash(manifest)
        return ValidationResult(
            state=state,
            study_id=request.study_id,
            violations=tuple(violations),
            checks=checks,
            manifest=manifest,
        )
