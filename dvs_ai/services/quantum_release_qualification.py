from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Tuple

from dvs_ai.services.quantum_governance.checksum import canonical_sha256
from dvs_ai.services.quantum_runtime_guard import QuantumRuntimeGuard

FROZEN_DECISION_ENGINE_MD5 = "72cf7d54e1ed6369400683358da8c0ef"


@dataclass(frozen=True)
class QualificationCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class QuantumReleaseQualification:
    qualified: bool
    state: str
    generated_at_utc: str
    checks: Tuple[QualificationCheck, ...]
    report_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": "dvs-quantum-release-qualification-v1",
            "qualified": self.qualified,
            "state": self.state,
            "generated_at_utc": self.generated_at_utc,
            "checks": [asdict(item) for item in self.checks],
        }
        payload["report_sha256"] = canonical_sha256(payload)
        return payload


class QuantumReleaseQualifier:
    """Production-readiness checks for the governed Quantum runtime.

    This class does not grant Optimizer or SHADOW authority. It only reports
    whether the installed runtime, frozen engine, configuration, governance
    bundle and append-only audit ledger are internally consistent.
    """

    def __init__(
        self,
        project_root: str | Path,
        *,
        guard: QuantumRuntimeGuard | None = None,
        config_path: str | Path | None = None,
        decision_engine_path: str | Path | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.guard = guard or QuantumRuntimeGuard()
        self.config_path = Path(config_path) if config_path else self.project_root / "config.json"
        self.decision_engine_path = (
            Path(decision_engine_path)
            if decision_engine_path
            else self.project_root / "dvs_ai" / "engines" / "decision_engine.py"
        )

    @staticmethod
    def _md5(path: Path) -> str:
        digest = hashlib.md5()  # nosec B324 - required frozen artifact identity
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def verify_runtime_audit_log(path: str | Path) -> tuple[bool, str]:
        log_path = Path(path)
        if not log_path.is_file():
            return False, "RUNTIME_AUDIT_LOG_MISSING"
        previous = "GENESIS"
        try:
            rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, json.JSONDecodeError):
            return False, "RUNTIME_AUDIT_LOG_UNREADABLE"
        if not rows:
            return False, "RUNTIME_AUDIT_LOG_EMPTY"
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, Mapping):
                return False, f"RUNTIME_AUDIT_LOG_ROW_INVALID:{index}"
            if row.get("previous_hash") != previous:
                return False, f"RUNTIME_AUDIT_LOG_CHAIN_INVALID:{index}"
            claimed = row.get("entry_hash")
            body = dict(row)
            body.pop("entry_hash", None)
            if not isinstance(claimed, str) or canonical_sha256(body) != claimed:
                return False, f"RUNTIME_AUDIT_LOG_HASH_INVALID:{index}"
            previous = claimed
        return True, f"RUNTIME_AUDIT_LOG_VALID:{len(rows)}"

    def _check_engine(self) -> QualificationCheck:
        if not self.decision_engine_path.is_file():
            return QualificationCheck("decision_engine_integrity", False, "DECISION_ENGINE_MISSING")
        actual = self._md5(self.decision_engine_path)
        return QualificationCheck(
            "decision_engine_integrity",
            actual == FROZEN_DECISION_ENGINE_MD5,
            f"md5={actual}",
        )

    def _check_config(self) -> QualificationCheck:
        try:
            config = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return QualificationCheck("runtime_configuration", False, "CONFIG_UNREADABLE")
        violations: list[str] = []
        if config.get("quantum_auto_apply_shadow") is not False:
            violations.append("QUANTUM_AUTO_APPLY_SHADOW_NOT_FALSE")
        execution_mode = str(config.get("execution_mode", "PAPER")).upper()
        if execution_mode not in {"PAPER", "RESEARCH", "SHADOW"}:
            violations.append(f"UNSAFE_EXECUTION_MODE:{execution_mode}")
        return QualificationCheck(
            "runtime_configuration",
            not violations,
            ",".join(violations) if violations else f"execution_mode={execution_mode};quantum_auto_apply_shadow=false",
        )

    def _check_governance(self) -> QualificationCheck:
        decision = self.guard.startup_self_test()
        return QualificationCheck(
            "governance_startup_self_test",
            decision.allowed,
            decision.message(),
        )

    def _check_audit_log(self) -> QualificationCheck:
        valid, detail = self.verify_runtime_audit_log(self.guard.audit_log)
        return QualificationCheck("runtime_audit_ledger", valid, detail)

    def run(self) -> QuantumReleaseQualification:
        checks = (
            self._check_engine(),
            self._check_config(),
            self._check_governance(),
            self._check_audit_log(),
        )
        qualified = all(item.passed for item in checks)
        return QuantumReleaseQualification(
            qualified=qualified,
            state="QUALIFIED_RESEARCH_RUNTIME" if qualified else "BLOCKED_NOT_QUALIFIED",
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            checks=checks,
        )

    def write_report(self, destination: str | Path) -> Path:
        report = self.run().to_dict()
        output = Path(destination)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return output
