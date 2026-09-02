from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from dvs_ai.services.quantum_validation.attempt_ledger import AttemptLedger
from dvs_ai.services.quantum_validation.holdout import HoldoutManager

from .checksum import canonical_sha256, verify_self_hash
from .ledger_verify import verify_holdout_ledger
from .models import GovernanceRequest, GovernanceResult, GovernanceState


def _nested(mapping: Mapping[str, Any], *path: str) -> Any:
    value: Any = mapping
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _manifest_policy_hash(manifest: Mapping[str, Any]) -> Any:
    return (
        manifest.get("policy_scope_hash")
        or _nested(manifest, "request", "policy_scope_hash")
        or _nested(manifest, "dataset", "policy_scope_hash")
    )


def _manifest_decision_checksum(manifest: Mapping[str, Any]) -> Any:
    return (
        manifest.get("decision_engine_checksum")
        or _nested(manifest, "request", "decision_engine_checksum")
        or _nested(manifest, "dataset", "decision_engine_checksum")
    )


class GovernanceGate:
    """Fail-closed governance gate for independently auditable Quantum studies."""

    def evaluate(self, request: GovernanceRequest) -> GovernanceResult:
        violations: list[str] = []
        checks: dict[str, bool] = {}

        manifests = {
            "dataset": request.dataset_manifest,
            "replay": request.replay_manifest,
            "explanation": request.explanation_manifest,
            "validation": request.validation_manifest,
        }
        for name, manifest in manifests.items():
            checks[f"{name}_manifest_integrity"] = verify_self_hash(manifest)
            if not checks[f"{name}_manifest_integrity"]:
                violations.append(f"{name.upper()}_MANIFEST_INVALID")

        checks["validation_pass"] = request.validation_manifest.get("state") == "PASS"
        if not checks["validation_pass"]:
            violations.append("VALIDATION_NOT_PASS")

        replay_state = request.replay_manifest.get("state") or request.replay_manifest.get("replay_state")
        checks["replay_verified"] = replay_state == "VERIFIED"
        if not checks["replay_verified"]:
            violations.append("REPLAY_NOT_VERIFIED")

        explanation_state = request.explanation_manifest.get("state")
        checks["explanation_acceptable"] = explanation_state in {"COMPLETE", "INCOMPLETE_EVIDENCE", "VERIFIED"}
        if not checks["explanation_acceptable"]:
            violations.append("EXPLANATION_NOT_ACCEPTABLE")

        policy_values = [_manifest_policy_hash(m) for m in manifests.values()]
        checks["policy_scope_consistent"] = all(v == request.policy_scope_hash for v in policy_values)
        if not checks["policy_scope_consistent"]:
            violations.append("POLICY_SCOPE_MISMATCH")

        decision_values = [_manifest_decision_checksum(m) for m in manifests.values()]
        checks["decision_checksum_consistent"] = (
            request.decision_engine_checksum == request.expected_decision_engine_checksum
            and all(v == request.expected_decision_engine_checksum for v in decision_values)
        )
        if not checks["decision_checksum_consistent"]:
            violations.append("DECISION_CHECKSUM_MISMATCH")

        attempt_ledger = AttemptLedger(request.attempt_ledger_path)
        checks["attempt_ledger_valid"] = attempt_ledger.verify()
        if not checks["attempt_ledger_valid"]:
            violations.append("ATTEMPT_LEDGER_INVALID")

        checks["holdout_ledger_valid"] = verify_holdout_ledger(request.holdout_ledger_path)
        if not checks["holdout_ledger_valid"]:
            violations.append("HOLDOUT_LEDGER_INVALID")

        holdout = HoldoutManager(request.holdout_ledger_path).status(request.holdout_id)
        checks["holdout_locked"] = bool(holdout.get("locked"))
        checks["holdout_consumed_once"] = bool(holdout.get("consumed"))
        if not checks["holdout_locked"]:
            violations.append("HOLDOUT_NOT_LOCKED")
        if not checks["holdout_consumed_once"]:
            violations.append("HOLDOUT_NOT_CONSUMED")

        state = GovernanceState.BLOCK if violations else GovernanceState.READY_FOR_AUDIT
        manifest: dict[str, Any] = {
            "schema_version": "dvs-quantum-governance-v1",
            "release": "4.3.0E-3",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "state": state.value,
            "study_id": request.study_id,
            "policy_scope_id": request.policy_scope_id,
            "policy_scope_hash": request.policy_scope_hash,
            "decision_engine_checksum": request.decision_engine_checksum,
            "checks": checks,
            "violations": violations,
            "source_manifest_hashes": {
                name: manifest.get("self_sha256") for name, manifest in manifests.items()
            },
            "holdout_id": request.holdout_id,
            "safety_boundary": {
                "decision_engine_mutation": False,
                "optimizer_authority": False,
                "recommendation_authority": False,
                "shadow_write_authority": False,
                "main_write_authority": False,
                "trade_execution_authority": False,
                "causal_claim_allowed": False,
            },
        }
        manifest["self_sha256"] = canonical_sha256(manifest)
        return GovernanceResult(
            state=state,
            study_id=request.study_id,
            violations=tuple(violations),
            checks=checks,
            manifest=manifest,
        )
