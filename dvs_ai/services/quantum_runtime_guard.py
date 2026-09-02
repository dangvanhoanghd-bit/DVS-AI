from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Tuple

from dvs_ai.services.quantum_governance.checksum import canonical_sha256, file_sha256, verify_self_hash
from dvs_ai.services.quantum_governance.verifier import verify_audit_bundle


class QuantumRuntimeAction(str, Enum):
    OPTIMIZE = "OPTIMIZE"
    APPLY_SHADOW = "APPLY_SHADOW"
    STARTUP_SELF_TEST = "STARTUP_SELF_TEST"


@dataclass(frozen=True)
class QuantumRuntimeDecision:
    allowed: bool
    action: QuantumRuntimeAction
    violations: Tuple[str, ...]
    bundle_dir: str | None = None
    study_id: str | None = None
    bundle_fingerprint: str | None = None

    def message(self) -> str:
        if self.allowed:
            return f"Quantum governance approved {self.action.value}."
        detail = ", ".join(self.violations) if self.violations else "UNKNOWN_BLOCK"
        return f"Quantum runtime blocked by governance: {detail}"


class QuantumRuntimeGuard:
    """Fail-closed runtime bridge with operational trust policy and audit ledger."""

    ENV_BUNDLE = "DVS_QUANTUM_GOVERNANCE_BUNDLE"
    ENV_TRUSTED_FINGERPRINTS = "DVS_QUANTUM_TRUSTED_BUNDLE_SHA256"
    ENV_ALLOWED_ROOTS = "DVS_QUANTUM_ALLOWED_BUNDLE_ROOTS"
    ENV_AUDIT_LOG = "DVS_QUANTUM_RUNTIME_AUDIT_LOG"

    def __init__(self, bundle_dir: str | Path | None = None, *, audit_log: str | Path | None = None) -> None:
        configured = bundle_dir or os.environ.get(self.ENV_BUNDLE)
        self.bundle_dir = Path(configured).expanduser() if configured else None
        self.audit_log = Path(audit_log or os.environ.get(self.ENV_AUDIT_LOG, "data/quantum_governance_runtime.jsonl"))

    @staticmethod
    def _split_policy(value: str | None) -> tuple[str, ...]:
        if not value:
            return ()
        normalized = value.replace(";", os.pathsep).replace(",", os.pathsep)
        return tuple(part.strip() for part in normalized.split(os.pathsep) if part.strip())

    def _trusted_fingerprints(self) -> set[str]:
        return {item.lower() for item in self._split_policy(os.environ.get(self.ENV_TRUSTED_FINGERPRINTS))}

    def _allowed_roots(self) -> tuple[Path, ...]:
        return tuple(Path(item).expanduser().resolve() for item in self._split_policy(os.environ.get(self.ENV_ALLOWED_ROOTS)))

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _append_audit(self, decision: QuantumRuntimeDecision) -> bool:
        try:
            self.audit_log.parent.mkdir(parents=True, exist_ok=True)
            previous_hash = "GENESIS"
            if self.audit_log.exists():
                lines = [line for line in self.audit_log.read_text(encoding="utf-8").splitlines() if line.strip()]
                if lines:
                    previous_hash = str(json.loads(lines[-1]).get("entry_hash", "INVALID_PREVIOUS"))
            entry = {
                "schema_version": "dvs-quantum-runtime-audit-v1",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "action": decision.action.value,
                "allowed": decision.allowed,
                "violations": list(decision.violations),
                "bundle_dir": decision.bundle_dir,
                "study_id": decision.study_id,
                "bundle_fingerprint": decision.bundle_fingerprint,
                "previous_hash": previous_hash,
            }
            entry["entry_hash"] = canonical_sha256(entry)
            with self.audit_log.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")
            return True
        except Exception:
            return False

    def _finish(self, decision: QuantumRuntimeDecision) -> QuantumRuntimeDecision:
        if not self._append_audit(decision):
            return QuantumRuntimeDecision(False, decision.action, decision.violations + ("AUDIT_LOG_WRITE_FAILED",), decision.bundle_dir, decision.study_id, decision.bundle_fingerprint)
        return decision

    def evaluate(self, action: QuantumRuntimeAction | str) -> QuantumRuntimeDecision:
        requested = action if isinstance(action, QuantumRuntimeAction) else QuantumRuntimeAction(str(action))
        violations: list[str] = []
        if self.bundle_dir is None:
            return self._finish(QuantumRuntimeDecision(False, requested, ("GOVERNANCE_BUNDLE_NOT_CONFIGURED",)))
        root = self.bundle_dir.resolve()
        if not root.is_dir():
            return self._finish(QuantumRuntimeDecision(False, requested, ("GOVERNANCE_BUNDLE_NOT_FOUND",), str(root)))

        allowed_roots = self._allowed_roots()
        if not allowed_roots:
            violations.append("ALLOWED_BUNDLE_ROOTS_NOT_CONFIGURED")
        elif not any(self._is_within(root, allowed) for allowed in allowed_roots):
            violations.append("BUNDLE_PATH_NOT_ALLOWED")
        index_path = root / "audit_bundle.index.json"
        fingerprint = file_sha256(index_path) if index_path.is_file() else None
        trusted = self._trusted_fingerprints()
        if not trusted:
            violations.append("TRUSTED_BUNDLE_FINGERPRINTS_NOT_CONFIGURED")
        elif fingerprint is None or fingerprint.lower() not in trusted:
            violations.append("BUNDLE_FINGERPRINT_NOT_TRUSTED")

        verification = verify_audit_bundle(root)
        if not verification.valid:
            violations.extend(f"AUDIT_BUNDLE_INVALID:{item}" for item in verification.violations)

        governance_path = root / "governance.manifest.json"
        try:
            governance: Mapping[str, Any] = json.loads(governance_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            violations.append("GOVERNANCE_MANIFEST_UNREADABLE")
            return self._finish(QuantumRuntimeDecision(False, requested, tuple(violations), str(root), bundle_fingerprint=fingerprint))

        if not verify_self_hash(governance):
            violations.append("GOVERNANCE_MANIFEST_SELF_HASH_INVALID")
        if governance.get("state") != "READY_FOR_AUDIT":
            violations.append("GOVERNANCE_NOT_READY_FOR_AUDIT")

        authority = governance.get("runtime_authority") if isinstance(governance.get("runtime_authority"), Mapping) else {}
        safety = governance.get("safety_boundary") if isinstance(governance.get("safety_boundary"), Mapping) else {}
        if requested != QuantumRuntimeAction.STARTUP_SELF_TEST:
            key = {QuantumRuntimeAction.OPTIMIZE: "optimizer_allowed", QuantumRuntimeAction.APPLY_SHADOW: "shadow_apply_allowed"}[requested]
            if authority.get(key) is not True:
                violations.append(f"RUNTIME_AUTHORITY_DENIED:{key}")
            legacy_key = {QuantumRuntimeAction.OPTIMIZE: "optimizer_authority", QuantumRuntimeAction.APPLY_SHADOW: "shadow_write_authority"}[requested]
            if safety.get(legacy_key) is not True:
                violations.append(f"SAFETY_BOUNDARY_DENIES:{legacy_key}")

        decision = QuantumRuntimeDecision(not violations, requested, tuple(violations), str(root), str(governance.get("study_id")) if governance.get("study_id") else None, fingerprint)
        return self._finish(decision)

    def startup_self_test(self) -> QuantumRuntimeDecision:
        return self.evaluate(QuantumRuntimeAction.STARTUP_SELF_TEST)

    def require(self, action: QuantumRuntimeAction | str) -> QuantumRuntimeDecision:
        decision = self.evaluate(action)
        if not decision.allowed:
            raise PermissionError(decision.message())
        return decision
