from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import uuid
from typing import Any, Callable, Mapping, Protocol

from .contracts import (
    ClaimTerminalOutcome,
    EvaluationMode,
    EvaluationReport,
    HoldoutConsumptionRecord,
    TestStatus,
)
from .errors import Beta4AGateError


class Evaluator(Protocol):
    def __call__(self, model_slot_id: str, rows: object) -> dict[str, float]: ...


class TestRowLoader(Protocol):
    def __call__(self, split_sha256: str) -> object: ...


Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _sha256_json(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ClaimRecoveryEvent:
    claim_id: str
    split_sha256: str
    model_slot_id: str
    expired_at: str
    recovered_at: str
    code: str = "EXPIRED_CLAIM_RECOVERED"


class ModelEvaluationGate:
    """Sole application entry point for Test evaluation.

    The gate uses SQLite ``BEGIN IMMEDIATE`` claims so only one model can obtain
    a qualifying evaluation for a split. ``HOLDOUT_ACCESS_STARTED`` is persisted
    before the Test payload is returned to evaluator code. Any failure after that
    point consumes the holdout fail-closed.

    This is an application-architecture and audit control, not an operating-system
    filesystem security boundary.
    """

    def __init__(
        self,
        *,
        state_db_path: str | Path,
        test_row_loader: TestRowLoader,
        claim_ttl: timedelta = timedelta(minutes=15),
        clock: Clock = _utc_now,
    ) -> None:
        if claim_ttl.total_seconds() <= 0:
            raise ValueError("claim_ttl must be positive")
        self._db_path = str(state_db_path)
        self._test_row_loader = test_row_loader
        self._claim_ttl = claim_ttl
        self._clock = clock
        self._schema_lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path, timeout=30.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _ensure_schema(self) -> None:
        with self._schema_lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS holdout_split_state (
                    split_sha256 TEXT PRIMARY KEY,
                    test_status TEXT NOT NULL CHECK(test_status IN ('LOCKED_UNCONSUMED','CONSUMED')),
                    consumed_at TEXT,
                    consumed_reason TEXT
                );

                CREATE TABLE IF NOT EXISTS holdout_claims (
                    claim_id TEXT PRIMARY KEY,
                    split_sha256 TEXT NOT NULL,
                    model_slot_id TEXT NOT NULL,
                    claimed_at TEXT NOT NULL,
                    claim_expires_at TEXT NOT NULL,
                    access_started_at TEXT,
                    terminal_outcome TEXT,
                    terminal_at TEXT,
                    FOREIGN KEY(split_sha256) REFERENCES holdout_split_state(split_sha256)
                );
                CREATE INDEX IF NOT EXISTS idx_holdout_claims_split
                    ON holdout_claims(split_sha256, terminal_outcome);

                CREATE TABLE IF NOT EXISTS holdout_recovery_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    claim_id TEXT NOT NULL UNIQUE,
                    split_sha256 TEXT NOT NULL,
                    model_slot_id TEXT NOT NULL,
                    expired_at TEXT NOT NULL,
                    recovered_at TEXT NOT NULL,
                    code TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS holdout_consumption_records (
                    record_sha256 TEXT PRIMARY KEY,
                    split_sha256 TEXT NOT NULL UNIQUE,
                    model_slot_id TEXT NOT NULL,
                    consumed_at TEXT NOT NULL,
                    evaluation_purpose TEXT NOT NULL,
                    evaluation_report_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evaluation_reports (
                    report_sha256 TEXT PRIMARY KEY,
                    report_id TEXT NOT NULL UNIQUE,
                    split_sha256 TEXT NOT NULL,
                    model_slot_id TEXT NOT NULL,
                    evaluation_mode TEXT NOT NULL,
                    qualifying INTEGER NOT NULL,
                    historical_benchmark_only INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )

    def _ensure_split(self, connection: sqlite3.Connection, split_sha256: str) -> None:
        connection.execute(
            "INSERT OR IGNORE INTO holdout_split_state(split_sha256, test_status) VALUES (?, ?)",
            (split_sha256, TestStatus.LOCKED_UNCONSUMED.value),
        )

    def _recover_or_block_active_claim(
        self, connection: sqlite3.Connection, *, split_sha256: str, now: datetime
    ) -> None:
        active = connection.execute(
            """SELECT * FROM holdout_claims
               WHERE split_sha256 = ? AND terminal_outcome IS NULL
               ORDER BY claimed_at DESC LIMIT 1""",
            (split_sha256,),
        ).fetchone()
        if active is None:
            return
        if _parse_iso(active["claim_expires_at"]) > now:
            raise Beta4AGateError(
                "HOLDOUT_QUALIFYING_CLAIM_ALREADY_HELD",
                f"split {split_sha256} is claimed by {active['model_slot_id']}",
            )

        terminal_at = _iso(now)
        if active["access_started_at"]:
            connection.execute(
                """UPDATE holdout_claims
                   SET terminal_outcome = ?, terminal_at = ? WHERE claim_id = ?""",
                (ClaimTerminalOutcome.CLAIM_ABORTED_AFTER_ACCESS.value, terminal_at, active["claim_id"]),
            )
            connection.execute(
                """UPDATE holdout_split_state
                   SET test_status = ?, consumed_at = ?, consumed_reason = ?
                   WHERE split_sha256 = ?""",
                (
                    TestStatus.CONSUMED.value,
                    terminal_at,
                    "HOLDOUT_CONSUMED_WITHOUT_COMPLETED_EVALUATION",
                    split_sha256,
                ),
            )
            return

        connection.execute(
            """UPDATE holdout_claims
               SET terminal_outcome = ?, terminal_at = ? WHERE claim_id = ?""",
            (ClaimTerminalOutcome.CLAIM_RECOVERED.value, terminal_at, active["claim_id"]),
        )
        connection.execute(
            """INSERT INTO holdout_recovery_events(
                   claim_id, split_sha256, model_slot_id, expired_at, recovered_at, code
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                active["claim_id"],
                split_sha256,
                active["model_slot_id"],
                active["claim_expires_at"],
                terminal_at,
                "EXPIRED_CLAIM_RECOVERED",
            ),
        )

    def _claim_qualifying(self, *, split_sha256: str, model_slot_id: str) -> str | None:
        now = self._clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._ensure_split(connection, split_sha256)
                state = connection.execute(
                    "SELECT test_status FROM holdout_split_state WHERE split_sha256 = ?",
                    (split_sha256,),
                ).fetchone()
                if state["test_status"] == TestStatus.CONSUMED.value:
                    connection.execute("COMMIT")
                    return None

                self._recover_or_block_active_claim(connection, split_sha256=split_sha256, now=now)
                state = connection.execute(
                    "SELECT test_status FROM holdout_split_state WHERE split_sha256 = ?",
                    (split_sha256,),
                ).fetchone()
                if state["test_status"] == TestStatus.CONSUMED.value:
                    connection.execute("COMMIT")
                    return None

                claim_id = uuid.uuid4().hex
                connection.execute(
                    """INSERT INTO holdout_claims(
                           claim_id, split_sha256, model_slot_id, claimed_at, claim_expires_at
                       ) VALUES (?, ?, ?, ?, ?)""",
                    (
                        claim_id,
                        split_sha256,
                        model_slot_id,
                        _iso(now),
                        _iso(now + self._claim_ttl),
                    ),
                )
                connection.execute("COMMIT")
                return claim_id
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def _mark_access_started(self, *, claim_id: str) -> None:
        now = _iso(self._clock())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                claim = connection.execute(
                    "SELECT * FROM holdout_claims WHERE claim_id = ?", (claim_id,)
                ).fetchone()
                if claim is None or claim["terminal_outcome"] is not None:
                    raise Beta4AGateError(
                        "HOLDOUT_CLAIM_OWNERSHIP_MISMATCH",
                        f"claim {claim_id} is missing or no longer active",
                    )
                connection.execute(
                    "UPDATE holdout_claims SET access_started_at = ? WHERE claim_id = ?",
                    (now, claim_id),
                )
                connection.execute(
                    """UPDATE holdout_split_state
                       SET test_status = ?, consumed_at = ?, consumed_reason = ?
                       WHERE split_sha256 = ?""",
                    (
                        TestStatus.CONSUMED.value,
                        now,
                        "HOLDOUT_ACCESS_STARTED",
                        claim["split_sha256"],
                    ),
                )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def _abort_after_access(self, *, claim_id: str) -> None:
        now = _iso(self._clock())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                claim = connection.execute(
                    "SELECT * FROM holdout_claims WHERE claim_id = ?", (claim_id,)
                ).fetchone()
                if claim and claim["terminal_outcome"] is None:
                    connection.execute(
                        """UPDATE holdout_claims SET terminal_outcome = ?, terminal_at = ?
                           WHERE claim_id = ?""",
                        (ClaimTerminalOutcome.CLAIM_ABORTED_AFTER_ACCESS.value, now, claim_id),
                    )
                    connection.execute(
                        """UPDATE holdout_split_state SET test_status = ?, consumed_at = ?, consumed_reason = ?
                           WHERE split_sha256 = ?""",
                        (
                            TestStatus.CONSUMED.value,
                            now,
                            "HOLDOUT_CONSUMED_WITHOUT_COMPLETED_EVALUATION",
                            claim["split_sha256"],
                        ),
                    )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def _publish_qualifying(
        self,
        *,
        claim_id: str,
        model_slot_id: str,
        split_sha256: str,
        metrics: Mapping[str, float],
        model_artifact_sha256: str | None,
        feature_matrix_sha256: str | None,
        training_run_id: str | None,
    ) -> EvaluationReport:
        now = _iso(self._clock())
        report_id = uuid.uuid4().hex
        report_core = {
            "report_id": report_id,
            "model_slot_id": model_slot_id,
            "split_sha256": split_sha256,
            "evaluation_mode": EvaluationMode.QUALIFYING_HOLDOUT_EVALUATION.value,
            "qualifying": True,
            "historical_benchmark_only": False,
            "test_status_at_evaluation_start": TestStatus.LOCKED_UNCONSUMED.value,
            "metrics": dict(metrics),
            "model_artifact_sha256": model_artifact_sha256,
            "feature_matrix_sha256": feature_matrix_sha256,
            "training_run_id": training_run_id,
        }
        report_core_sha = _sha256_json(report_core)
        consumption = HoldoutConsumptionRecord(
            split_sha256=split_sha256,
            model_slot_id=model_slot_id,
            consumed_at=now,
            evaluation_purpose="QUALIFYING_HOLDOUT_EVALUATION",
            evaluation_report_sha256=report_core_sha,
        )
        consumption_payload = asdict(consumption)
        consumption_sha = _sha256_json(consumption_payload)
        report = EvaluationReport(
            report_id=report_id,
            model_slot_id=model_slot_id,
            split_sha256=split_sha256,
            evaluation_mode=EvaluationMode.QUALIFYING_HOLDOUT_EVALUATION,
            qualifying=True,
            historical_benchmark_only=False,
            test_status_at_evaluation_start=TestStatus.LOCKED_UNCONSUMED,
            holdout_consumption_record_sha256=consumption_sha,
            metrics=dict(metrics),
            model_artifact_sha256=model_artifact_sha256,
            feature_matrix_sha256=feature_matrix_sha256,
            training_run_id=training_run_id,
        )
        report_payload = {
            **report_core,
            "holdout_consumption_record_sha256": consumption_sha,
        }
        report_sha = _sha256_json(report_payload)

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                claim = connection.execute(
                    "SELECT * FROM holdout_claims WHERE claim_id = ?", (claim_id,)
                ).fetchone()
                if (
                    claim is None
                    or claim["model_slot_id"] != model_slot_id
                    or claim["split_sha256"] != split_sha256
                    or claim["terminal_outcome"] is not None
                    or not claim["access_started_at"]
                ):
                    raise Beta4AGateError(
                        "HOLDOUT_CLAIM_OWNERSHIP_MISMATCH",
                        f"claim {claim_id} does not authorize publication",
                    )
                connection.execute(
                    """INSERT INTO holdout_consumption_records(
                           record_sha256, split_sha256, model_slot_id, consumed_at,
                           evaluation_purpose, evaluation_report_sha256, payload_json
                       ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        consumption_sha,
                        split_sha256,
                        model_slot_id,
                        now,
                        consumption.evaluation_purpose,
                        report_core_sha,
                        json.dumps(consumption_payload, sort_keys=True),
                    ),
                )
                connection.execute(
                    """INSERT INTO evaluation_reports(
                           report_sha256, report_id, split_sha256, model_slot_id,
                           evaluation_mode, qualifying, historical_benchmark_only,
                           created_at, payload_json
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        report_sha,
                        report_id,
                        split_sha256,
                        model_slot_id,
                        report.evaluation_mode.value,
                        1,
                        0,
                        now,
                        json.dumps(report_payload, sort_keys=True),
                    ),
                )
                connection.execute(
                    """UPDATE holdout_claims SET terminal_outcome = ?, terminal_at = ?
                       WHERE claim_id = ?""",
                    (ClaimTerminalOutcome.CLAIM_COMPLETED.value, now, claim_id),
                )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        return report

    def _publish_historical(
        self, *, model_slot_id: str, split_sha256: str, metrics: Mapping[str, float],
        model_artifact_sha256: str | None, feature_matrix_sha256: str | None,
        training_run_id: str | None,
    ) -> EvaluationReport:
        now = _iso(self._clock())
        report = EvaluationReport(
            report_id=uuid.uuid4().hex,
            model_slot_id=model_slot_id,
            split_sha256=split_sha256,
            evaluation_mode=EvaluationMode.HISTORICAL_BENCHMARK_EVALUATION,
            qualifying=False,
            historical_benchmark_only=True,
            test_status_at_evaluation_start=TestStatus.CONSUMED,
            holdout_consumption_record_sha256=None,
            metrics=dict(metrics),
            model_artifact_sha256=model_artifact_sha256,
            feature_matrix_sha256=feature_matrix_sha256,
            training_run_id=training_run_id,
        )
        payload = {
            "report_id": report.report_id,
            "model_slot_id": model_slot_id,
            "split_sha256": split_sha256,
            "evaluation_mode": report.evaluation_mode.value,
            "qualifying": False,
            "historical_benchmark_only": True,
            "test_status_at_evaluation_start": TestStatus.CONSUMED.value,
            "holdout_consumption_record_sha256": None,
            "metrics": dict(metrics),
            "model_artifact_sha256": model_artifact_sha256,
            "feature_matrix_sha256": feature_matrix_sha256,
            "training_run_id": training_run_id,
        }
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO evaluation_reports(
                       report_sha256, report_id, split_sha256, model_slot_id,
                       evaluation_mode, qualifying, historical_benchmark_only,
                       created_at, payload_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    _sha256_json(payload),
                    report.report_id,
                    split_sha256,
                    model_slot_id,
                    report.evaluation_mode.value,
                    0,
                    1,
                    now,
                    json.dumps(payload, sort_keys=True),
                ),
            )
        return report

    def evaluate(
        self, *, model_slot_id: str, split_sha256: str, evaluator: Evaluator,
        model_artifact_sha256: str | None = None,
        feature_matrix_sha256: str | None = None,
        training_run_id: str | None = None,
    ) -> EvaluationReport:
        if not model_slot_id or not split_sha256:
            raise ValueError("model_slot_id and split_sha256 must be non-empty")

        claim_id = self._claim_qualifying(
            split_sha256=split_sha256, model_slot_id=model_slot_id
        )
        if claim_id is None:
            rows = self._test_row_loader(split_sha256)
            metrics = evaluator(model_slot_id, rows)
            return self._publish_historical(
                model_slot_id=model_slot_id, split_sha256=split_sha256, metrics=metrics,
                model_artifact_sha256=model_artifact_sha256,
                feature_matrix_sha256=feature_matrix_sha256,
                training_run_id=training_run_id,
            )

        self._mark_access_started(claim_id=claim_id)
        try:
            rows = self._test_row_loader(split_sha256)
            metrics = evaluator(model_slot_id, rows)
            return self._publish_qualifying(
                claim_id=claim_id,
                model_slot_id=model_slot_id,
                split_sha256=split_sha256,
                metrics=metrics,
                model_artifact_sha256=model_artifact_sha256,
                feature_matrix_sha256=feature_matrix_sha256,
                training_run_id=training_run_id,
            )
        except Exception:
            self._abort_after_access(claim_id=claim_id)
            raise

    def recover_expired_claims(self) -> tuple[ClaimRecoveryEvent, ...]:
        """Recover expired claims that provably never started Test access.

        Claims with access_started_at are consumed fail-closed and are therefore
        intentionally absent from the returned recovery-event list.
        """
        now = self._clock()
        recovered: list[ClaimRecoveryEvent] = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                rows = connection.execute(
                    """SELECT * FROM holdout_claims
                       WHERE terminal_outcome IS NULL AND claim_expires_at <= ?""",
                    (_iso(now),),
                ).fetchall()
                for row in rows:
                    if row["access_started_at"]:
                        connection.execute(
                            """UPDATE holdout_claims SET terminal_outcome = ?, terminal_at = ?
                               WHERE claim_id = ?""",
                            (
                                ClaimTerminalOutcome.CLAIM_ABORTED_AFTER_ACCESS.value,
                                _iso(now),
                                row["claim_id"],
                            ),
                        )
                        connection.execute(
                            """UPDATE holdout_split_state SET test_status = ?, consumed_at = ?, consumed_reason = ?
                               WHERE split_sha256 = ?""",
                            (
                                TestStatus.CONSUMED.value,
                                _iso(now),
                                "HOLDOUT_CONSUMED_WITHOUT_COMPLETED_EVALUATION",
                                row["split_sha256"],
                            ),
                        )
                        continue
                    event = ClaimRecoveryEvent(
                        claim_id=row["claim_id"],
                        split_sha256=row["split_sha256"],
                        model_slot_id=row["model_slot_id"],
                        expired_at=row["claim_expires_at"],
                        recovered_at=_iso(now),
                    )
                    connection.execute(
                        """UPDATE holdout_claims SET terminal_outcome = ?, terminal_at = ?
                           WHERE claim_id = ?""",
                        (
                            ClaimTerminalOutcome.CLAIM_RECOVERED.value,
                            event.recovered_at,
                            event.claim_id,
                        ),
                    )
                    connection.execute(
                        """INSERT INTO holdout_recovery_events(
                               claim_id, split_sha256, model_slot_id, expired_at, recovered_at, code
                           ) VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            event.claim_id,
                            event.split_sha256,
                            event.model_slot_id,
                            event.expired_at,
                            event.recovered_at,
                            event.code,
                        ),
                    )
                    recovered.append(event)
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        return tuple(recovered)

    def audit_snapshot(self, split_sha256: str) -> dict[str, Any]:
        """Return a compact, read-only audit view used by tests and audit tooling."""
        with self._connect() as connection:
            state = connection.execute(
                "SELECT * FROM holdout_split_state WHERE split_sha256 = ?",
                (split_sha256,),
            ).fetchone()
            claims = connection.execute(
                "SELECT * FROM holdout_claims WHERE split_sha256 = ? ORDER BY claimed_at",
                (split_sha256,),
            ).fetchall()
            consumption = connection.execute(
                "SELECT * FROM holdout_consumption_records WHERE split_sha256 = ?",
                (split_sha256,),
            ).fetchone()
            reports = connection.execute(
                "SELECT * FROM evaluation_reports WHERE split_sha256 = ? ORDER BY created_at",
                (split_sha256,),
            ).fetchall()
        return {
            "state": dict(state) if state else None,
            "claims": [dict(row) for row in claims],
            "consumption": dict(consumption) if consumption else None,
            "reports": [dict(row) for row in reports],
        }
