from __future__ import annotations

import json
from pathlib import Path

from dvs_ai.services.quantum_governance import (
    AuditBundleBuilder,
    GovernanceGate,
    GovernanceRequest,
    GovernanceState,
    verify_audit_bundle,
)
from dvs_ai.services.quantum_governance.checksum import canonical_sha256
from dvs_ai.services.quantum_validation import AttemptLedger, HoldoutManager

DECISION_MD5 = "72cf7d54e1ed6369400683358da8c0ef"
POLICY_HASH = "policy-scope-hash-001"


def sealed(payload: dict) -> dict:
    payload = dict(payload)
    payload["self_sha256"] = canonical_sha256(payload)
    return payload


def manifests() -> dict[str, dict]:
    common = {
        "policy_scope_hash": POLICY_HASH,
        "decision_engine_checksum": DECISION_MD5,
    }
    return {
        "dataset": sealed({**common, "state": "RESEARCH_CANDIDATE_ONLY"}),
        "replay": sealed({**common, "state": "VERIFIED"}),
        "explanation": sealed({**common, "state": "INCOMPLETE_EVIDENCE"}),
        "validation": sealed({
            "state": "PASS",
            "request": {
                "policy_scope_hash": POLICY_HASH,
                "decision_engine_checksum": DECISION_MD5,
            },
        }),
    }


def ready_request(tmp_path: Path) -> tuple[GovernanceRequest, dict[str, dict]]:
    attempt_path = tmp_path / "attempt.jsonl"
    AttemptLedger(attempt_path).append(POLICY_HASH, "study-1", 1, 1)
    holdout_path = tmp_path / "holdout.jsonl"
    holdouts = HoldoutManager(holdout_path)
    holdouts.lock("h-1", "2026-01-01T00:00:00Z", "scope-1")
    holdouts.consume("h-1", "2026-01-01T00:00:00Z", "scope-1")
    source = manifests()
    request = GovernanceRequest(
        study_id="study-1",
        policy_scope_id="scope-1",
        policy_scope_hash=POLICY_HASH,
        decision_engine_checksum=DECISION_MD5,
        expected_decision_engine_checksum=DECISION_MD5,
        dataset_manifest=source["dataset"],
        replay_manifest=source["replay"],
        explanation_manifest=source["explanation"],
        validation_manifest=source["validation"],
        attempt_ledger_path=attempt_path,
        holdout_ledger_path=holdout_path,
        holdout_id="h-1",
    )
    return request, source


def test_governance_ready_for_audit(tmp_path: Path) -> None:
    request, _ = ready_request(tmp_path)
    result = GovernanceGate().evaluate(request)
    assert result.state is GovernanceState.READY_FOR_AUDIT
    assert result.violations == ()
    assert result.optimizer_allowed is False
    assert result.shadow_apply_allowed is False


def test_governance_blocks_tampered_manifest(tmp_path: Path) -> None:
    request, _ = ready_request(tmp_path)
    bad = dict(request.validation_manifest)
    bad["state"] = "BLOCK"
    request = GovernanceRequest(**{**request.__dict__, "validation_manifest": bad})
    result = GovernanceGate().evaluate(request)
    assert result.state is GovernanceState.BLOCK
    assert "VALIDATION_MANIFEST_INVALID" in result.violations
    assert "VALIDATION_NOT_PASS" in result.violations


def test_governance_blocks_decision_checksum_mismatch(tmp_path: Path) -> None:
    request, _ = ready_request(tmp_path)
    request = GovernanceRequest(**{**request.__dict__, "decision_engine_checksum": "changed"})
    result = GovernanceGate().evaluate(request)
    assert result.state is GovernanceState.BLOCK
    assert "DECISION_CHECKSUM_MISMATCH" in result.violations


def test_governance_blocks_unconsumed_holdout(tmp_path: Path) -> None:
    request, source = ready_request(tmp_path)
    holdout_path = tmp_path / "holdout-only-locked.jsonl"
    HoldoutManager(holdout_path).lock("h-2", "2026-01-01T00:00:00Z", "scope-1")
    request = GovernanceRequest(**{
        **request.__dict__,
        "holdout_ledger_path": holdout_path,
        "holdout_id": "h-2",
    })
    result = GovernanceGate().evaluate(request)
    assert result.state is GovernanceState.BLOCK
    assert "HOLDOUT_NOT_CONSUMED" in result.violations


def test_audit_bundle_verifies_and_detects_tampering(tmp_path: Path) -> None:
    request, source = ready_request(tmp_path)
    result = GovernanceGate().evaluate(request)
    bundle = AuditBundleBuilder().build(
        tmp_path / "bundle",
        study_id=request.study_id,
        manifests=source,
        governance_manifest=result.manifest,
        attempt_ledger_path=request.attempt_ledger_path,
        holdout_ledger_path=request.holdout_ledger_path,
    )
    assert verify_audit_bundle(bundle).valid is True
    target = bundle / "validation.manifest.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["state"] = "BLOCK"
    target.write_text(json.dumps(payload), encoding="utf-8")
    verification = verify_audit_bundle(bundle)
    assert verification.valid is False
    assert any("validation.manifest.json" in x for x in verification.violations)


def test_audit_bundle_target_must_be_empty(tmp_path: Path) -> None:
    request, source = ready_request(tmp_path)
    result = GovernanceGate().evaluate(request)
    target = tmp_path / "bundle"
    target.mkdir()
    (target / "existing.txt").write_text("x")
    try:
        AuditBundleBuilder().build(
            target,
            study_id=request.study_id,
            manifests=source,
            governance_manifest=result.manifest,
            attempt_ledger_path=request.attempt_ledger_path,
            holdout_ledger_path=request.holdout_ledger_path,
        )
    except FileExistsError:
        pass
    else:
        raise AssertionError("non-empty audit target must be rejected")
