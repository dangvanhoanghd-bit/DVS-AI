from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from dvs_ai.services.unified_outcome_service import UnifiedOutcomeRecord, UnifiedOutcomeService

SCHEMA_VERSION = "beta2c-unified-integrity-v1"
CRITICAL_CODES = frozenset({
    "DUPLICATE_UNIFIED_ID", "DUPLICATE_EXPLICIT_LINK", "LEARNING_READY_WITHOUT_ELIGIBILITY",
    "ELIGIBLE_WITHOUT_SNAPSHOT", "CONFLICT_MARKED_ELIGIBLE",
    "REVIEW_EVENT_NOT_APPLIED", "REVIEW_TARGET_NOT_FOUND",
    "REVIEW_EVENT_HASH_INVALID", "REVIEW_DECISION_INCONSISTENT",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IntegrityFinding:
    code: str
    severity: str
    unified_id: str | None
    detail: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UnifiedIntegrityReport:
    schema: str
    generated_at: str
    total_records: int
    integrity_score: float
    findings: tuple[IntegrityFinding, ...]
    counts: dict[str, int]
    release_ready: bool
    report_sha256: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["findings"] = [f.to_dict() for f in self.findings]
        return value


class UnifiedIntegrityAuditor:
    """Read-only integrity auditor over the governed unified read model."""

    def __init__(self, service: UnifiedOutcomeService) -> None:
        self.service = service

    @staticmethod
    def _finding(code: str, severity: str, row: UnifiedOutcomeRecord | None, **detail: Any) -> IntegrityFinding:
        return IntegrityFinding(code, severity, row.unified_id if row else None, detail)

    def audit(self, records: Iterable[UnifiedOutcomeRecord] | None = None) -> UnifiedIntegrityReport:
        rows = list(self.service.records() if records is None else records)
        findings: list[IntegrityFinding] = []

        ids = Counter(r.unified_id for r in rows)
        for uid, count in sorted(ids.items()):
            if count > 1:
                findings.append(IntegrityFinding("DUPLICATE_UNIFIED_ID", "CRITICAL", uid, {"count": count}))

        source_identity_owner: dict[str, list[str]] = {}
        for row in rows:
            for identity in row.source_identities:
                source_identity_owner.setdefault(identity, []).append(row.unified_id)
        for identity, owners in sorted(source_identity_owner.items()):
            if len(set(owners)) > 1:
                findings.append(IntegrityFinding(
                    "DUPLICATE_EXPLICIT_LINK", "CRITICAL", None,
                    {"source_identity": identity, "unified_ids": sorted(set(owners))},
                ))

        for row in rows:
            if row.eligibility_status == "UNIFIED_ELIGIBLE" and not row.feature_snapshot_hash:
                findings.append(self._finding("ELIGIBLE_WITHOUT_SNAPSHOT", "CRITICAL", row))
            if row.eligibility_status == "UNIFIED_ELIGIBLE" and row.outcome_status not in {"WIN", "LOSS", "INVALID", "AMBIGUOUS", "EXPIRED"}:
                findings.append(self._finding("ELIGIBLE_NON_TERMINAL", "ERROR", row, outcome=row.outcome_status))
            if row.eligibility_status == "CONFLICT":
                findings.append(self._finding("UNRESOLVED_CONFLICT", "WARNING", row, reason=row.conflict_reason))
            if row.eligibility_status == "AMBIGUOUS_MATCH":
                findings.append(self._finding("AMBIGUOUS_MATCH_REVIEW_REQUIRED", "WARNING", row))
            if row.eligibility_status == "NOT_ELIGIBLE" and row.eligibility_reason == "HISTORICAL_SNAPSHOT_UNAVAILABLE":
                findings.append(self._finding("HISTORICAL_SNAPSHOT_UNAVAILABLE", "INFO", row))
            if row.eligibility_status == "UNIFIED_ELIGIBLE" and row.conflict_reason:
                findings.append(self._finding("CONFLICT_MARKED_ELIGIBLE", "CRITICAL", row, reason=row.conflict_reason))

        eligible_ids = {r.unified_id for r in rows if r.eligibility_status == "UNIFIED_ELIGIBLE"}
        for row in self.service.learning_ready():
            if row.unified_id not in eligible_ids:
                findings.append(self._finding("LEARNING_READY_WITHOUT_ELIGIBILITY", "CRITICAL", row))

        diagnostics = self.service.review_diagnostics() if hasattr(self.service, "review_diagnostics") else []
        for item in diagnostics:
            code = str(item.get("code") or "REVIEW_EVENT_NOT_APPLIED")
            uid = str(item.get("unified_id") or "") or None
            findings.append(IntegrityFinding(code, "CRITICAL", uid, {k: v for k, v in item.items() if k not in {"code", "unified_id"}}))

        # A valid review event must be visible on the governed record returned to consumers.
        reviewed = {r.unified_id: r for r in rows if r.review_event_sha256}
        latest, _ = self.service.review_repository.latest_events() if hasattr(self.service, "review_repository") else ({}, [])
        for uid, event in latest.items():
            row = reviewed.get(uid)
            if row is None or row.review_event_sha256 != str(event.get("event_sha256") or ""):
                findings.append(IntegrityFinding("REVIEW_EVENT_NOT_APPLIED", "CRITICAL", uid, {"event_id": event.get("event_id")}))

        counts = dict(sorted(Counter(f.code for f in findings).items()))
        critical = sum(f.code in CRITICAL_CODES or f.severity == "CRITICAL" for f in findings)
        errors = sum(f.severity == "ERROR" for f in findings)
        denominator = max(1, len(rows))
        score = max(0.0, 100.0 - ((critical * 10.0 + errors * 3.0) / denominator * 100.0))
        release_ready = critical == 0 and errors == 0
        generated_at = _now()
        payload = {
            "schema": SCHEMA_VERSION,
            "generated_at": generated_at,
            "total_records": len(rows),
            "integrity_score": round(score, 4),
            "findings": [f.to_dict() for f in findings],
            "counts": counts,
            "release_ready": release_ready,
        }
        return UnifiedIntegrityReport(
            schema=SCHEMA_VERSION,
            generated_at=generated_at,
            total_records=len(rows),
            integrity_score=round(score, 4),
            findings=tuple(findings),
            counts=counts,
            release_ready=release_ready,
            report_sha256=_sha(payload),
        )


class UnifiedReviewLedger:
    """Append-only manual review ledger. It never mutates source outcome tables."""

    VALID_ACTIONS = frozenset({"ACCEPT_PAPER", "ACCEPT_CANDIDATE", "EXCLUDE"})

    def __init__(self, db_path: str | Path = "data/unified_review_ledger.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._schema()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _schema(self) -> None:
        with self._connect() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS unified_review_events(
              event_id INTEGER PRIMARY KEY AUTOINCREMENT,
              unified_id TEXT NOT NULL,
              reviewed_at TEXT NOT NULL,
              reviewer TEXT NOT NULL,
              action TEXT NOT NULL,
              reason TEXT NOT NULL,
              evidence_json TEXT NOT NULL,
              previous_status TEXT NOT NULL,
              resulting_status TEXT NOT NULL,
              event_sha256 TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_unified_review_events_unified_id
              ON unified_review_events(unified_id,event_id);
            """)

    def review(self, record: UnifiedOutcomeRecord, reviewer: str, action: str,
               reason: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        action = str(action).upper()
        if action not in self.VALID_ACTIONS:
            raise ValueError(f"Unsupported review action: {action}")
        if record.eligibility_status not in {"CONFLICT", "AMBIGUOUS_MATCH", "NOT_ELIGIBLE"}:
            raise ValueError("Only blocked/review-required records may be manually reviewed")
        if not reviewer.strip() or not reason.strip():
            raise ValueError("reviewer and reason are required")
        resulting = "RESOLVED_EXCLUDE" if action == "EXCLUDE" else "MANUALLY_APPROVED"
        reviewed_at = _now()
        payload = {
            "unified_id": record.unified_id, "reviewed_at": reviewed_at,
            "reviewer": reviewer.strip(), "action": action, "reason": reason.strip(),
            "evidence": evidence or {}, "previous_status": record.eligibility_status,
            "resulting_status": resulting,
        }
        event_sha = _sha(payload)
        with self._connect() as con:
            con.execute("""
            INSERT INTO unified_review_events(
              unified_id,reviewed_at,reviewer,action,reason,evidence_json,
              previous_status,resulting_status,event_sha256
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """, (
                record.unified_id, reviewed_at, reviewer.strip(), action, reason.strip(),
                json.dumps(evidence or {}, sort_keys=True, separators=(",", ":")),
                record.eligibility_status, resulting, event_sha,
            ))
        return {**payload, "event_sha256": event_sha}

    def history(self, unified_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM unified_review_events"
        params: tuple[Any, ...] = ()
        if unified_id is not None:
            query += " WHERE unified_id=?"
            params = (unified_id,)
        query += " ORDER BY event_id ASC"
        with self._connect() as con:
            rows = [dict(r) for r in con.execute(query, params)]
        for row in rows:
            row["evidence"] = json.loads(row.pop("evidence_json"))
        return rows


class UnifiedReleaseGate:
    """Operational release gate for Beta 2C. No trading/threshold authority."""

    def __init__(self, auditor: UnifiedIntegrityAuditor, telemetry_path: str | Path = "data/legacy_path_telemetry.jsonl") -> None:
        self.auditor = auditor
        self.telemetry_path = Path(telemetry_path)

    def _legacy_calls(self) -> int:
        if not self.telemetry_path.is_file():
            return 0
        total = 0
        for line in self.telemetry_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                if json.loads(line).get("event") == "LEGACY_SQL_PATH_USED":
                    total += 1
            except json.JSONDecodeError:
                continue
        return total

    def evaluate(self) -> dict[str, Any]:
        report = self.auditor.audit()
        legacy_calls = self._legacy_calls()
        blockers = []
        if not report.release_ready:
            blockers.append("INTEGRITY_CRITICAL_OR_ERROR")
        if report.counts.get("DUPLICATE_UNIFIED_ID", 0):
            blockers.append("DUPLICATE_UNIFIED_ID")
        if report.counts.get("DUPLICATE_EXPLICIT_LINK", 0):
            blockers.append("DUPLICATE_EXPLICIT_LINK")
        if legacy_calls:
            blockers.append("LEGACY_SQL_PATH_USED")
        result = {
            "gate": "PASS" if not blockers else "BLOCKED",
            "blockers": blockers,
            "legacy_sql_calls": legacy_calls,
            "integrity_score": report.integrity_score,
            "integrity_report_sha256": report.report_sha256,
            "generated_at": _now(),
            "authority_boundary": "OBSERVATION_AND_RELEASE_GOVERNANCE_ONLY",
        }
        result["gate_sha256"] = _sha(result)
        return result
