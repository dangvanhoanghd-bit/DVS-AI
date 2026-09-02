from __future__ import annotations

import json
from pathlib import Path

from dvs_ai.services.quantum_governance.checksum import canonical_sha256, file_sha256
from dvs_ai.services.quantum_runtime_guard import QuantumRuntimeAction, QuantumRuntimeGuard


def _write_bundle(root: Path, *, optimizer: bool = False, shadow: bool = False) -> None:
    root.mkdir()
    governance = {
        "schema_version": "dvs-quantum-governance-v1",
        "state": "READY_FOR_AUDIT",
        "study_id": "study-qi1",
        "runtime_authority": {
            "optimizer_allowed": optimizer,
            "shadow_apply_allowed": shadow,
        },
        "safety_boundary": {
            "optimizer_authority": optimizer,
            "shadow_write_authority": shadow,
        },
    }
    governance["self_sha256"] = canonical_sha256(governance)
    gp = root / "governance.manifest.json"
    gp.write_text(json.dumps(governance, sort_keys=True), encoding="utf-8")
    files = {gp.name: file_sha256(gp)}
    index = {
        "schema_version": "dvs-quantum-audit-bundle-v1",
        "study_id": "study-qi1",
        "governance_state": "READY_FOR_AUDIT",
        "files": files,
        "immutable_intent": True,
    }
    index["self_sha256"] = canonical_sha256(index)
    (root / "audit_bundle.index.json").write_text(json.dumps(index, sort_keys=True), encoding="utf-8")


def test_missing_bundle_blocks_both_runtime_actions() -> None:
    guard = QuantumRuntimeGuard()
    assert not guard.evaluate(QuantumRuntimeAction.OPTIMIZE).allowed
    assert not guard.evaluate(QuantumRuntimeAction.APPLY_SHADOW).allowed


def test_e3_audit_only_authority_blocks_legacy_runtime(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle(bundle)
    guard = QuantumRuntimeGuard(bundle)
    optimize = guard.evaluate(QuantumRuntimeAction.OPTIMIZE)
    shadow = guard.evaluate(QuantumRuntimeAction.APPLY_SHADOW)
    assert not optimize.allowed
    assert "RUNTIME_AUTHORITY_DENIED:optimizer_allowed" in optimize.violations
    assert not shadow.allowed
    assert "RUNTIME_AUTHORITY_DENIED:shadow_apply_allowed" in shadow.violations


def test_tampered_bundle_blocks_even_when_authority_claims_true(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle(bundle, optimizer=True, shadow=True)
    governance = bundle / "governance.manifest.json"
    governance.write_text(governance.read_text(encoding="utf-8") + " ", encoding="utf-8")
    decision = QuantumRuntimeGuard(bundle).evaluate(QuantumRuntimeAction.OPTIMIZE)
    assert not decision.allowed
    assert any(v.startswith("AUDIT_BUNDLE_INVALID:") for v in decision.violations)


def test_sealed_future_runtime_authority_can_be_recognized(tmp_path: Path, monkeypatch) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle(bundle, optimizer=True, shadow=True)
    index = bundle / "audit_bundle.index.json"
    monkeypatch.setenv("DVS_QUANTUM_ALLOWED_BUNDLE_ROOTS", str(tmp_path))
    monkeypatch.setenv("DVS_QUANTUM_TRUSTED_BUNDLE_SHA256", file_sha256(index))
    monkeypatch.setenv("DVS_QUANTUM_RUNTIME_AUDIT_LOG", str(tmp_path / "runtime.jsonl"))
    guard = QuantumRuntimeGuard(bundle)
    assert guard.evaluate(QuantumRuntimeAction.OPTIMIZE).allowed
    assert guard.evaluate(QuantumRuntimeAction.APPLY_SHADOW).allowed


def test_live_ui_contains_governance_preflight_before_legacy_actions() -> None:
    source = Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")
    run = source.index("def run_quantum_optimizer")
    worker = source.index("self.quantum_thread=QThread", run)
    assert source.index("QuantumRuntimeAction.OPTIMIZE", run, worker) > run
    apply = source.index("def apply_quantum_shadow")
    candidate = source.index("create_shadow_candidate", apply)
    assert source.index("QuantumRuntimeAction.APPLY_SHADOW", apply, candidate) > apply
