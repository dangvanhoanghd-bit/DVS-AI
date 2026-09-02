from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from .report_models import EvidenceAnalysisResult, StageState


@dataclass(frozen=True)
class ProtocolComplianceReport:
    state: str
    checks: tuple[tuple[str, str], ...]
    issues: tuple[str, ...]


class EvidenceProtocolEnforcer:
    """Fail-closed validation of Evidence Analysis Protocol v1.0 artifacts."""

    @staticmethod
    def verify_result(result: EvidenceAnalysisResult) -> ProtocolComplianceReport:
        checks: list[tuple[str, str]] = []
        issues: list[str] = []
        integrity_pass = result.integrity.state == StageState.PASS
        checks.append(("integrity_gate", "PASS" if integrity_pass else "BLOCKED"))
        if not integrity_pass:
            if result.evidence.state != StageState.SKIPPED:
                issues.append("Integrity failure did not skip evidence")
            if result.confidence.state not in {StageState.SKIPPED, StageState.ANALYSIS_ABORTED}:
                issues.append("Integrity failure did not stop confidence")
            if result.recommendation.state != StageState.ANALYSIS_ABORTED:
                issues.append("Integrity failure did not abort recommendation")
        if result.confidence.conclusion_state in {"UNOBSERVABLE", "OBSERVABLE_BUT_UNDERPOWERED"}:
            if result.recommendation.actionable:
                issues.append("Non-powered conclusion produced actionable recommendation")
            if result.recommendation.recommendation != "COLLECT_MORE_DATA":
                issues.append("Non-powered conclusion bypassed collect-more-data gate")
        if result.recommendation.recommendation == "READY_FOR_MANUAL_REVIEW":
            if result.confidence.state != StageState.PASS:
                issues.append("Manual review readiness without confidence PASS")
            if result.confidence.conclusion_state != "SUPPORTED":
                issues.append("Manual review readiness without SUPPORTED conclusion")
            if not result.recommendation.actionable:
                issues.append("Manual review readiness not marked actionable")
        if result.recommendation.recommendation == "REVIEW_REQUIRED":
            if result.confidence.conclusion_state != "UNSUPPORTED":
                issues.append("Review-required recommendation without UNSUPPORTED conclusion")
            if not result.recommendation.actionable:
                issues.append("Review-required recommendation not marked actionable")
        if result.recommendation.recommendation == "CONTINUE_PAPER":
            if result.recommendation.actionable:
                issues.append("Continue-paper recommendation incorrectly marked actionable")
        checks.append(("stopping_rules", "PASS" if not issues else "FAIL"))
        return ProtocolComplianceReport("PASS" if not issues else "FAIL", tuple(checks), tuple(issues))

    @staticmethod
    def audit_source(base: str | Path) -> ProtocolComplianceReport:
        base = Path(base)
        downstream = [
            "confidence_engine.py", "gap_planner.py", "recommendation_mapper.py",
            "executive_report.py", "protocol_enforcement.py",
        ]
        forbidden_imports = {"sqlite3", "observable_repository"}
        issues: list[str] = []
        checks: list[tuple[str, str]] = []
        for name in downstream:
            path = base / name
            if not path.exists():
                issues.append(f"Missing downstream module: {name}")
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split(".")[-1])
            bad = sorted(imports & forbidden_imports)
            if bad:
                issues.append(f"{name} imports forbidden dependency: {','.join(bad)}")
            checks.append((f"source_isolation:{name}", "PASS" if not bad else "FAIL"))
        return ProtocolComplianceReport("PASS" if not issues else "FAIL", tuple(checks), tuple(issues))
