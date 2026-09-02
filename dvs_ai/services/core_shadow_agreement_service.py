from __future__ import annotations

"""Persistent, observe-only Legacy/Unified Core agreement measurements.

The store records paired GUI shadow observations.  It does not expose any
execution, authorization, promotion, or handover capability.  Qualification
is a read-only evaluation against the frozen governance profile.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import csv
import hashlib
import json
import math
from threading import RLock
from collections import defaultdict

from dvs_ai.governance.paper_authority_handover import (
    FROZEN_PAPER_AUTHORITY_HANDOVER_PROFILE,
    PaperAuthorityHandoverProfile,
)


AGREEMENT_FULL = "FULL"
AGREEMENT_PARTIAL = "PARTIAL"
AGREEMENT_CONSERVATIVE = "PARTIAL_UNIFIED_MORE_CONSERVATIVE"
AGREEMENT_UNSAFE = "UNSAFE_DIVERGENCE"


@dataclass(frozen=True, slots=True)
class AgreementResult:
    """Canonical agreement value shared by evidence, UI and governance.

    ``code`` is the stable persisted value. ``display`` and ``color`` are
    presentation metadata derived from the same classification, preventing
    evidence/presentation drift.
    """

    code: str
    display: str
    severity: str
    color: str

    @property
    def is_full(self) -> bool:
        return self.code == AGREEMENT_FULL

    @property
    def is_unsafe(self) -> bool:
        return self.code == AGREEMENT_UNSAFE


_AGREEMENT_RESULTS = {
    AGREEMENT_FULL: AgreementResult(
        code=AGREEMENT_FULL, display="FULL", severity="SAFE", color="#22c55e"
    ),
    AGREEMENT_PARTIAL: AgreementResult(
        code=AGREEMENT_PARTIAL, display="PARTIAL", severity="REVIEW", color="#facc15"
    ),
    AGREEMENT_CONSERVATIVE: AgreementResult(
        code=AGREEMENT_CONSERVATIVE,
        display="PARTIAL · UNIFIED MORE CONSERVATIVE",
        severity="SAFE_PARTIAL",
        color="#38bdf8",
    ),
    AGREEMENT_UNSAFE: AgreementResult(
        code=AGREEMENT_UNSAFE,
        display="UNSAFE DIVERGENCE",
        severity="BLOCKED",
        color="#ef4444",
    ),
}


def classify_agreement_result(legacy_action: str, unified_action: str) -> AgreementResult:
    """Return the single canonical classification object."""
    legacy = str(legacy_action).upper().strip()
    unified = str(unified_action).upper().strip()
    actionable = {"BUY", "SELL"}
    if legacy == unified:
        code = AGREEMENT_FULL
    elif legacy == "NO_ACTION" and unified in actionable:
        code = AGREEMENT_UNSAFE
    elif legacy in actionable and unified == "NO_ACTION":
        code = AGREEMENT_CONSERVATIVE
    else:
        code = AGREEMENT_PARTIAL
    return _AGREEMENT_RESULTS[code]


def classify_agreement(legacy_action: str, unified_action: str) -> str:
    """Backward-compatible code-only facade.

    New callers should use :func:`classify_agreement_result` so display and
    evidence always originate from the same immutable value object.
    """
    return classify_agreement_result(legacy_action, unified_action).code


@dataclass(frozen=True, slots=True)
class ShadowAgreementObservation:
    request_id: str
    symbol: str
    analysis_revision: int
    legacy_action: str
    unified_action: str
    agreement: str
    ledger_verified: bool
    synthetic_lifecycle: bool = True
    confidence: float = 0.0
    regime: str = "UNKNOWN"
    phase: str = "UNKNOWN"
    timeframe: str = "UNKNOWN"
    reason_codes: tuple[str, ...] = ()
    ledger_hash: str = ""
    authorized: bool = False
    risk_allowed: bool = False
    quantity: float = 0.0
    event_names: tuple[str, ...] = ()
    observed_at: str = ""

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("request_id is required")
        if not self.symbol:
            raise ValueError("symbol is required")
        if self.analysis_revision < 0:
            raise ValueError("analysis_revision must be non-negative")
        if self.agreement not in {
            AGREEMENT_FULL,
            AGREEMENT_PARTIAL,
            AGREEMENT_CONSERVATIVE,
            AGREEMENT_UNSAFE,
        }:
            raise ValueError(f"unsupported agreement: {self.agreement}")
        if not self.observed_at:
            object.__setattr__(
                self,
                "observed_at",
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )


@dataclass(frozen=True, slots=True)
class ShadowAgreementMetrics:
    total_cycles: int
    full_agreements: int
    partial_agreements: int
    conservative_divergences: int
    unsafe_divergences: int
    full_agreement_ratio: float
    profile_id: str
    profile_hash: str
    minimum_cycles: int
    required_full_agreement_ratio: float
    actionable_cycles: int
    actionable_ratio: float
    minimum_actionable_count: int
    minimum_actionable_ratio: float
    required_actionable_cycles: int
    actionable_gap: int
    decision_agreement_confidence: float | None
    qualification_status: str


@dataclass(frozen=True, slots=True)
class QualificationBreakdown:
    key: str
    total: int
    full: int
    partial: int
    conservative: int
    unsafe: int
    full_ratio: float


@dataclass(frozen=True, slots=True)
class QualificationAnalytics:
    total_cycles: int
    by_symbol: tuple[QualificationBreakdown, ...]
    by_regime: tuple[QualificationBreakdown, ...]
    by_phase: tuple[QualificationBreakdown, ...]
    by_confidence_bucket: tuple[QualificationBreakdown, ...]
    recent_timeline: tuple[tuple[str, str, str], ...]
    unsafe_cases: tuple[tuple[str, str, str, str], ...]


@dataclass(frozen=True, slots=True)
class QualificationEvidenceRecord:
    request_id: str
    symbol: str
    analysis_revision: int
    observed_at: str
    legacy_action: str
    unified_action: str
    agreement: str
    confidence: float
    regime: str
    phase: str
    timeframe: str
    ledger_verified: bool
    synthetic_lifecycle: bool
    reason_codes: tuple[str, ...]
    ledger_hash: str
    authorized: bool
    risk_allowed: bool
    quantity: float
    event_names: tuple[str, ...]
    profile_hash: str
    evidence_hash: str
    integrity_status: str


def _canonical_evidence_payload(values: dict[str, object]) -> str:
    return json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _evidence_hash(payload_json: str) -> str:
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


def _confidence_bucket(value: float) -> str:
    if value < 40:
        return "<40"
    if value < 50:
        return "40-49"
    if value < 60:
        return "50-59"
    if value < 70:
        return "60-69"
    if value < 80:
        return "70-79"
    return "80+"


class CoreShadowAgreementStore:
    """SQLite-backed append-only observation store with request idempotency."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=15.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS core_shadow_agreement_observations (
                    request_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    analysis_revision INTEGER NOT NULL,
                    legacy_action TEXT NOT NULL,
                    unified_action TEXT NOT NULL,
                    agreement TEXT NOT NULL,
                    ledger_verified INTEGER NOT NULL,
                    synthetic_lifecycle INTEGER NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0,
                    regime TEXT NOT NULL DEFAULT 'UNKNOWN',
                    phase TEXT NOT NULL DEFAULT 'UNKNOWN',
                    timeframe TEXT NOT NULL DEFAULT 'UNKNOWN',
                    observed_at TEXT NOT NULL,
                    profile_hash TEXT NOT NULL,
                    reason_codes_json TEXT NOT NULL DEFAULT '[]',
                    ledger_hash TEXT NOT NULL DEFAULT '',
                    authorized INTEGER NOT NULL DEFAULT 0,
                    risk_allowed INTEGER NOT NULL DEFAULT 0,
                    quantity REAL NOT NULL DEFAULT 0,
                    event_names_json TEXT NOT NULL DEFAULT '[]',
                    evidence_payload_json TEXT NOT NULL DEFAULT '',
                    evidence_hash TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_core_shadow_agreement_observed_at "
                "ON core_shadow_agreement_observations(observed_at)"
            )
            existing = {row[1] for row in connection.execute("PRAGMA table_info(core_shadow_agreement_observations)")}
            for name, ddl in (
                ("confidence", "REAL NOT NULL DEFAULT 0"),
                ("regime", "TEXT NOT NULL DEFAULT 'UNKNOWN'"),
                ("phase", "TEXT NOT NULL DEFAULT 'UNKNOWN'"),
                ("timeframe", "TEXT NOT NULL DEFAULT 'UNKNOWN'"),
                ("reason_codes_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("ledger_hash", "TEXT NOT NULL DEFAULT ''"),
                ("authorized", "INTEGER NOT NULL DEFAULT 0"),
                ("risk_allowed", "INTEGER NOT NULL DEFAULT 0"),
                ("quantity", "REAL NOT NULL DEFAULT 0"),
                ("event_names_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("evidence_payload_json", "TEXT NOT NULL DEFAULT ''"),
                ("evidence_hash", "TEXT NOT NULL DEFAULT ''"),
            ):
                if name not in existing:
                    connection.execute(f"ALTER TABLE core_shadow_agreement_observations ADD COLUMN {name} {ddl}")

    def append(
        self,
        observation: ShadowAgreementObservation,
        profile: PaperAuthorityHandoverProfile = FROZEN_PAPER_AUTHORITY_HANDOVER_PROFILE,
    ) -> bool:
        """Append once.  Returns False when request_id was already recorded."""
        payload = {
            "request_id": observation.request_id,
            "symbol": observation.symbol,
            "analysis_revision": observation.analysis_revision,
            "legacy_action": observation.legacy_action,
            "unified_action": observation.unified_action,
            "agreement": observation.agreement,
            "ledger_verified": bool(observation.ledger_verified),
            "synthetic_lifecycle": bool(observation.synthetic_lifecycle),
            "confidence": float(observation.confidence),
            "regime": str(observation.regime),
            "phase": str(observation.phase),
            "timeframe": str(observation.timeframe),
            "reason_codes": list(observation.reason_codes),
            "ledger_hash": str(observation.ledger_hash),
            "authorized": bool(observation.authorized),
            "risk_allowed": bool(observation.risk_allowed),
            "quantity": float(observation.quantity),
            "event_names": list(observation.event_names),
            "observed_at": observation.observed_at,
            "profile_hash": profile.profile_hash,
        }
        payload_json = _canonical_evidence_payload(payload)
        digest = _evidence_hash(payload_json)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO core_shadow_agreement_observations (
                    request_id, symbol, analysis_revision, legacy_action,
                    unified_action, agreement, ledger_verified,
                    synthetic_lifecycle, confidence, regime, phase, timeframe,
                    observed_at, profile_hash, reason_codes_json, ledger_hash,
                    authorized, risk_allowed, quantity, event_names_json,
                    evidence_payload_json, evidence_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation.request_id, observation.symbol, observation.analysis_revision,
                    observation.legacy_action, observation.unified_action, observation.agreement,
                    int(observation.ledger_verified), int(observation.synthetic_lifecycle),
                    float(observation.confidence), str(observation.regime), str(observation.phase),
                    str(observation.timeframe), observation.observed_at, profile.profile_hash,
                    json.dumps(list(observation.reason_codes), ensure_ascii=False),
                    str(observation.ledger_hash), int(observation.authorized),
                    int(observation.risk_allowed), float(observation.quantity),
                    json.dumps(list(observation.event_names), ensure_ascii=False),
                    payload_json, digest,
                ),
            )
            return cursor.rowcount == 1

    def analytics(
        self,
        profile: PaperAuthorityHandoverProfile = FROZEN_PAPER_AUTHORITY_HANDOVER_PROFILE,
        *,
        recent_limit: int = 30,
    ) -> QualificationAnalytics:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """SELECT symbol, agreement, confidence, regime, phase, timeframe, observed_at, legacy_action, unified_action
                   FROM core_shadow_agreement_observations
                   WHERE profile_hash = ? ORDER BY observed_at DESC""",
                (profile.profile_hash,),
            ).fetchall()

        def build(key_fn):
            groups = defaultdict(lambda: {
                AGREEMENT_FULL: 0, AGREEMENT_PARTIAL: 0,
                AGREEMENT_CONSERVATIVE: 0, AGREEMENT_UNSAFE: 0,
            })
            for row in rows:
                groups[str(key_fn(row) or "UNKNOWN")][str(row["agreement"])] += 1
            result = []
            for key, counts in groups.items():
                total = sum(counts.values())
                result.append(QualificationBreakdown(
                    key=key, total=total, full=counts[AGREEMENT_FULL],
                    partial=counts[AGREEMENT_PARTIAL],
                    conservative=counts[AGREEMENT_CONSERVATIVE],
                    unsafe=counts[AGREEMENT_UNSAFE],
                    full_ratio=(counts[AGREEMENT_FULL] / total) if total else 0.0,
                ))
            return tuple(sorted(result, key=lambda x: (-x.total, x.key)))

        timeline = tuple(
            (str(row["observed_at"]), str(row["symbol"]), str(row["agreement"]))
            for row in rows[:max(1, recent_limit)]
        )
        unsafe = tuple(
            (str(row["observed_at"]), str(row["symbol"]), str(row["legacy_action"]), str(row["unified_action"]))
            for row in rows if str(row["agreement"]) == AGREEMENT_UNSAFE
        )
        return QualificationAnalytics(
            total_cycles=len(rows),
            by_symbol=build(lambda r: r["symbol"]),
            by_regime=build(lambda r: r["regime"]),
            by_phase=build(lambda r: r["phase"]),
            by_confidence_bucket=build(lambda r: _confidence_bucket(float(r["confidence"] or 0.0))),
            recent_timeline=timeline,
            unsafe_cases=unsafe,
        )

    def list_evidence(
        self,
        *,
        profile: PaperAuthorityHandoverProfile = FROZEN_PAPER_AUTHORITY_HANDOVER_PROFILE,
        symbol: str = "",
        agreement: str = "",
        limit: int = 200,
    ) -> tuple[QualificationEvidenceRecord, ...]:
        clauses = ["profile_hash = ?"]
        params: list[object] = [profile.profile_hash]
        if symbol.strip():
            clauses.append("symbol LIKE ?")
            params.append(f"%{symbol.strip().upper()}%")
        if agreement.strip():
            clauses.append("agreement = ?")
            params.append(agreement.strip().upper())
        params.append(max(1, min(int(limit), 5000)))
        query = (
            "SELECT * FROM core_shadow_agreement_observations WHERE "
            + " AND ".join(clauses)
            + " ORDER BY observed_at DESC, rowid DESC LIMIT ?"
        )
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return tuple(self._row_to_evidence(row) for row in rows)

    def get_evidence(self, request_id: str) -> QualificationEvidenceRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM core_shadow_agreement_observations WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        return self._row_to_evidence(row) if row is not None else None

    def _row_to_evidence(self, row: sqlite3.Row) -> QualificationEvidenceRecord:
        payload_json = str(row["evidence_payload_json"] or "")
        stored_hash = str(row["evidence_hash"] or "")
        try:
            reasons = tuple(str(x) for x in json.loads(row["reason_codes_json"] or "[]"))
        except Exception:
            reasons = ()
        try:
            events = tuple(str(x) for x in json.loads(row["event_names_json"] or "[]"))
        except Exception:
            events = ()
        current_payload = _canonical_evidence_payload({
            "request_id": str(row["request_id"]),
            "symbol": str(row["symbol"]),
            "analysis_revision": int(row["analysis_revision"]),
            "legacy_action": str(row["legacy_action"]),
            "unified_action": str(row["unified_action"]),
            "agreement": str(row["agreement"]),
            "ledger_verified": bool(row["ledger_verified"]),
            "synthetic_lifecycle": bool(row["synthetic_lifecycle"]),
            "confidence": float(row["confidence"] or 0.0),
            "regime": str(row["regime"]),
            "phase": str(row["phase"]),
            "timeframe": str(row["timeframe"]),
            "reason_codes": list(reasons),
            "ledger_hash": str(row["ledger_hash"] or ""),
            "authorized": bool(row["authorized"]),
            "risk_allowed": bool(row["risk_allowed"]),
            "quantity": float(row["quantity"] or 0.0),
            "event_names": list(events),
            "observed_at": str(row["observed_at"]),
            "profile_hash": str(row["profile_hash"]),
        })
        if not payload_json or not stored_hash:
            integrity = "LEGACY_UNSEALED"
        elif payload_json != current_payload or _evidence_hash(current_payload) != stored_hash:
            integrity = "FAILED"
        else:
            integrity = "PASS"
        return QualificationEvidenceRecord(
            request_id=str(row["request_id"]), symbol=str(row["symbol"]),
            analysis_revision=int(row["analysis_revision"]), observed_at=str(row["observed_at"]),
            legacy_action=str(row["legacy_action"]), unified_action=str(row["unified_action"]),
            agreement=str(row["agreement"]), confidence=float(row["confidence"] or 0.0),
            regime=str(row["regime"]), phase=str(row["phase"]), timeframe=str(row["timeframe"]),
            ledger_verified=bool(row["ledger_verified"]), synthetic_lifecycle=bool(row["synthetic_lifecycle"]),
            reason_codes=reasons, ledger_hash=str(row["ledger_hash"] or ""),
            authorized=bool(row["authorized"]), risk_allowed=bool(row["risk_allowed"]),
            quantity=float(row["quantity"] or 0.0), event_names=events,
            profile_hash=str(row["profile_hash"]), evidence_hash=stored_hash,
            integrity_status=integrity,
        )

    def export_evidence_json(self, destination: str | Path, **filters: object) -> int:
        records = self.list_evidence(**filters)
        Path(destination).write_text(
            json.dumps([r.__dict__ if hasattr(r, "__dict__") else {f: getattr(r, f) for f in r.__dataclass_fields__} for r in records], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return len(records)

    def export_evidence_csv(self, destination: str | Path, **filters: object) -> int:
        records = self.list_evidence(**filters)
        fields = tuple(QualificationEvidenceRecord.__dataclass_fields__)
        with Path(destination).open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for record in records:
                row = {field: getattr(record, field) for field in fields}
                row["reason_codes"] = "|".join(record.reason_codes)
                row["event_names"] = "|".join(record.event_names)
                writer.writerow(row)
        return len(records)

    def metrics(
        self,
        profile: PaperAuthorityHandoverProfile = FROZEN_PAPER_AUTHORITY_HANDOVER_PROFILE,
    ) -> ShadowAgreementMetrics:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT agreement, COUNT(*) AS count
                FROM core_shadow_agreement_observations
                WHERE profile_hash = ?
                GROUP BY agreement
                """,
                (profile.profile_hash,),
            ).fetchall()
            actionable_row = connection.execute(
                """
                SELECT
                    COUNT(*) AS actionable_count,
                    SUM(CASE WHEN agreement = ? THEN 1 ELSE 0 END) AS actionable_full
                FROM core_shadow_agreement_observations
                WHERE profile_hash = ?
                  AND (UPPER(TRIM(legacy_action)) != 'NO_ACTION'
                       OR UPPER(TRIM(unified_action)) != 'NO_ACTION')
                """,
                (AGREEMENT_FULL, profile.profile_hash),
            ).fetchone()
            actionable = int(actionable_row["actionable_count"] or 0)
            actionable_full = int(actionable_row["actionable_full"] or 0)
        counts = {str(row["agreement"]): int(row["count"]) for row in rows}
        full = counts.get(AGREEMENT_FULL, 0)
        partial = counts.get(AGREEMENT_PARTIAL, 0)
        conservative = counts.get(AGREEMENT_CONSERVATIVE, 0)
        unsafe = counts.get(AGREEMENT_UNSAFE, 0)
        total = full + partial + conservative + unsafe
        ratio = (full / total) if total else 0.0
        actionable_ratio = (actionable / total) if total else 0.0
        required_actionable = max(
            profile.minimum_actionable_count,
            int(math.ceil(total * profile.minimum_actionable_ratio)),
        )
        actionable_gap = max(0, required_actionable - actionable)
        decision_agreement_confidence = (
            actionable_full / actionable if actionable else None
        )
        if unsafe > profile.maximum_unsafe_divergences:
            status = "BLOCKED_UNSAFE_DIVERGENCE"
        elif total < profile.minimum_parallel_cycles:
            status = "COLLECTING"
        elif actionable < required_actionable:
            status = "ACTIONABLE_EVIDENCE_INSUFFICIENT"
        elif ratio < profile.minimum_full_agreement_ratio:
            status = "BELOW_AGREEMENT_THRESHOLD"
        else:
            status = "READY_FOR_GOVERNANCE_REVIEW"
        return ShadowAgreementMetrics(
            total_cycles=total,
            full_agreements=full,
            partial_agreements=partial,
            conservative_divergences=conservative,
            unsafe_divergences=unsafe,
            full_agreement_ratio=ratio,
            profile_id=profile.profile_id,
            profile_hash=profile.profile_hash,
            minimum_cycles=profile.minimum_parallel_cycles,
            required_full_agreement_ratio=profile.minimum_full_agreement_ratio,
            actionable_cycles=actionable,
            actionable_ratio=actionable_ratio,
            minimum_actionable_count=profile.minimum_actionable_count,
            minimum_actionable_ratio=profile.minimum_actionable_ratio,
            required_actionable_cycles=required_actionable,
            actionable_gap=actionable_gap,
            decision_agreement_confidence=decision_agreement_confidence,
            qualification_status=status,
        )
