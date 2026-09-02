from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import uuid
from typing import Any, Callable, Mapping, Protocol

from .contracts import (
    EvaluationMode,
    EvaluationReport,
    HoldoutConsumptionRecord,
    ModelLifecycleTransitionRecord,
    ModelSlotManifest,
    ModelSlotState,
    TestStatus,
)
from .errors import Beta4AGateError


class ConsumptionRecordLoader(Protocol):
    def __call__(self, record_sha256: str) -> HoldoutConsumptionRecord | None: ...


Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _sha256_json(payload: Any) -> str:
    raw = json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _evaluation_report_payload(report: EvaluationReport) -> dict[str, Any]:
    payload = {
        "report_id": report.report_id,
        "model_slot_id": report.model_slot_id,
        "split_sha256": report.split_sha256,
        "evaluation_mode": report.evaluation_mode.value,
        "qualifying": report.qualifying,
        "historical_benchmark_only": report.historical_benchmark_only,
        "test_status_at_evaluation_start": report.test_status_at_evaluation_start.value,
        "holdout_consumption_record_sha256": report.holdout_consumption_record_sha256,
        "metrics": dict(report.metrics),
    }
    if any((report.model_artifact_sha256, report.feature_matrix_sha256, report.training_run_id)):
        payload.update({
            "model_artifact_sha256": report.model_artifact_sha256,
            "feature_matrix_sha256": report.feature_matrix_sha256,
            "training_run_id": report.training_run_id,
        })
    return payload


def _evaluation_report_core_payload(report: EvaluationReport) -> dict[str, Any]:
    payload = _evaluation_report_payload(report)
    payload.pop("holdout_consumption_record_sha256")
    return payload


class ModelLifecycleGate:
    """Sole application entry point for Model Slot state transitions.

    RC1 implements the frozen ``TRAINED_UNVALIDATED -> VALIDATED`` transition.
    It independently verifies the qualifying EvaluationReport, its immutable
    HoldoutConsumptionRecord, model/split bindings, and artifact hashes before
    persisting a sealed transition record in one SQLite transaction.

    This is an application-architecture and audit control, not a filesystem
    security boundary.
    """

    def __init__(
        self,
        *,
        state_db_path: str | Path,
        consumption_record_loader: ConsumptionRecordLoader,
        clock: Clock = _utc_now,
    ) -> None:
        self._db_path = str(state_db_path)
        self._consumption_record_loader = consumption_record_loader
        self._clock = clock
        self._schema_lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path, timeout=30.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _ensure_schema(self) -> None:
        with self._schema_lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS model_slot_manifests (
                    manifest_sha256 TEXT PRIMARY KEY,
                    model_slot_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_model_slot_manifests_slot
                    ON model_slot_manifests(model_slot_id, created_at);

                CREATE TABLE IF NOT EXISTS model_lifecycle_transitions (
                    transition_id TEXT PRIMARY KEY,
                    model_slot_id TEXT NOT NULL,
                    source_state TEXT NOT NULL,
                    target_state TEXT NOT NULL,
                    source_manifest_sha256 TEXT NOT NULL,
                    target_manifest_sha256 TEXT NOT NULL,
                    evaluation_report_id TEXT NOT NULL,
                    evaluation_report_sha256 TEXT NOT NULL,
                    holdout_consumption_record_sha256 TEXT NOT NULL,
                    transitioned_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(model_slot_id, target_state)
                );
                """
            )

    @staticmethod
    def _hard_block(code: str, message: str) -> None:
        raise Beta4AGateError(code, message)

    def _verify_report_shape(self, report: EvaluationReport) -> None:
        if report.evaluation_mode is EvaluationMode.HISTORICAL_BENCHMARK_EVALUATION:
            self._hard_block(
                "VALIDATION_SOURCE_TEST_ALREADY_CONSUMED",
                "historical benchmark reports cannot validate a model slot",
            )
        if (
            report.evaluation_mode is not EvaluationMode.QUALIFYING_HOLDOUT_EVALUATION
            or not report.qualifying
            or report.historical_benchmark_only
        ):
            self._hard_block(
                "NON_QUALIFYING_EVALUATION_SOURCE",
                "evaluation report is not a qualifying holdout evaluation",
            )
        if report.test_status_at_evaluation_start is not TestStatus.LOCKED_UNCONSUMED:
            self._hard_block(
                "VALIDATION_SOURCE_TEST_ALREADY_CONSUMED",
                "qualifying source was not LOCKED_UNCONSUMED at evaluation start",
            )
        if not report.holdout_consumption_record_sha256:
            self._hard_block(
                "NON_QUALIFYING_EVALUATION_SOURCE",
                "qualifying report has no HoldoutConsumptionRecord identity",
            )

    def _verify_bindings(
        self,
        *,
        model_slot: ModelSlotManifest,
        report: EvaluationReport,
        consumption: HoldoutConsumptionRecord,
    ) -> None:
        if report.model_slot_id != model_slot.model_slot_id:
            self._hard_block(
                "MODEL_SLOT_EVALUATION_BINDING_MISMATCH",
                "EvaluationReport belongs to a different model slot",
            )
        if report.split_sha256 != model_slot.source_split_sha256:
            self._hard_block(
                "MODEL_SLOT_SPLIT_BINDING_MISMATCH",
                "EvaluationReport split does not match ModelSlot source split",
            )
        if consumption.model_slot_id != model_slot.model_slot_id:
            self._hard_block(
                "HOLDOUT_CONSUMPTION_BINDING_MISMATCH",
                "HoldoutConsumptionRecord belongs to a different model slot",
            )
        if consumption.split_sha256 != report.split_sha256:
            self._hard_block(
                "HOLDOUT_CONSUMPTION_BINDING_MISMATCH",
                "HoldoutConsumptionRecord belongs to a different split",
            )
        if consumption.evaluation_purpose != EvaluationMode.QUALIFYING_HOLDOUT_EVALUATION.value:
            self._hard_block(
                "NON_QUALIFYING_EVALUATION_SOURCE",
                "HoldoutConsumptionRecord purpose is not qualifying evaluation",
            )
        binding_values = (
            model_slot.model_artifact_sha256, model_slot.feature_matrix_sha256, model_slot.training_run_id,
            report.model_artifact_sha256, report.feature_matrix_sha256, report.training_run_id,
        )
        if any(value is not None for value in binding_values):
            if not model_slot.model_artifact_sha256 or report.model_artifact_sha256 != model_slot.model_artifact_sha256:
                self._hard_block(
                    "MODEL_ARTIFACT_BINDING_MISMATCH",
                    "EvaluationReport does not bind to the trained model artifact",
                )
            if not model_slot.feature_matrix_sha256 or report.feature_matrix_sha256 != model_slot.feature_matrix_sha256:
                self._hard_block(
                    "FEATURE_MATRIX_BINDING_MISMATCH",
                    "EvaluationReport does not bind to the training feature matrix",
                )
            if not model_slot.training_run_id or report.training_run_id != model_slot.training_run_id:
                self._hard_block(
                    "TRAINING_RUN_BINDING_MISMATCH",
                    "EvaluationReport does not bind to the training run",
                )

    def promote_to_validated(
        self,
        *,
        model_slot: ModelSlotManifest,
        evaluation_report: EvaluationReport,
    ) -> ModelSlotManifest:
        if model_slot.state is not ModelSlotState.TRAINED_UNVALIDATED:
            self._hard_block(
                "MODEL_SLOT_TRANSITION_NOT_ALLOWED",
                f"cannot transition {model_slot.state.value} to VALIDATED",
            )

        self._verify_report_shape(evaluation_report)
        record_sha = evaluation_report.holdout_consumption_record_sha256
        assert record_sha is not None  # verified above
        consumption = self._consumption_record_loader(record_sha)
        if consumption is None:
            self._hard_block(
                "HOLDOUT_CONSUMPTION_RECORD_NOT_FOUND",
                f"record {record_sha} cannot be verified",
            )
        assert consumption is not None

        if _sha256_json(consumption) != record_sha:
            self._hard_block(
                "HOLDOUT_CONSUMPTION_RECORD_HASH_MISMATCH",
                "HoldoutConsumptionRecord payload does not match its identity",
            )
        self._verify_bindings(
            model_slot=model_slot,
            report=evaluation_report,
            consumption=consumption,
        )
        report_core_sha = _sha256_json(_evaluation_report_core_payload(evaluation_report))
        if consumption.evaluation_report_sha256 != report_core_sha:
            self._hard_block(
                "EVALUATION_REPORT_HASH_MISMATCH",
                "HoldoutConsumptionRecord does not bind to this EvaluationReport",
            )

        target = replace(model_slot, state=ModelSlotState.VALIDATED)
        now = _iso(self._clock())
        source_payload = _jsonable(model_slot)
        target_payload = _jsonable(target)
        source_sha = _sha256_json(source_payload)
        target_sha = _sha256_json(target_payload)
        report_sha = _sha256_json(_evaluation_report_payload(evaluation_report))
        transition = ModelLifecycleTransitionRecord(
            transition_id=uuid.uuid4().hex,
            model_slot_id=model_slot.model_slot_id,
            source_state=model_slot.state,
            target_state=target.state,
            source_manifest_sha256=source_sha,
            target_manifest_sha256=target_sha,
            evaluation_report_id=evaluation_report.report_id,
            evaluation_report_sha256=report_sha,
            holdout_consumption_record_sha256=record_sha,
            transitioned_at=now,
        )
        transition_payload = _jsonable(transition)

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT * FROM model_lifecycle_transitions WHERE model_slot_id = ? AND target_state = ?",
                    (model_slot.model_slot_id, ModelSlotState.VALIDATED.value),
                ).fetchone()
                if existing is not None:
                    self._hard_block(
                        "MODEL_SLOT_ALREADY_VALIDATED",
                        f"model slot {model_slot.model_slot_id} already has a VALIDATED transition",
                    )
                connection.execute(
                    """INSERT OR IGNORE INTO model_slot_manifests(
                           manifest_sha256, model_slot_id, state, created_at, payload_json
                       ) VALUES (?, ?, ?, ?, ?)""",
                    (source_sha, model_slot.model_slot_id, model_slot.state.value, now,
                     json.dumps(source_payload, sort_keys=True)),
                )
                connection.execute(
                    """INSERT INTO model_slot_manifests(
                           manifest_sha256, model_slot_id, state, created_at, payload_json
                       ) VALUES (?, ?, ?, ?, ?)""",
                    (target_sha, target.model_slot_id, target.state.value, now,
                     json.dumps(target_payload, sort_keys=True)),
                )
                connection.execute(
                    """INSERT INTO model_lifecycle_transitions(
                           transition_id, model_slot_id, source_state, target_state,
                           source_manifest_sha256, target_manifest_sha256,
                           evaluation_report_id, evaluation_report_sha256,
                           holdout_consumption_record_sha256, transitioned_at, payload_json
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        transition.transition_id,
                        transition.model_slot_id,
                        transition.source_state.value,
                        transition.target_state.value,
                        transition.source_manifest_sha256,
                        transition.target_manifest_sha256,
                        transition.evaluation_report_id,
                        transition.evaluation_report_sha256,
                        transition.holdout_consumption_record_sha256,
                        transition.transitioned_at,
                        json.dumps(transition_payload, sort_keys=True),
                    ),
                )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        return target

    def audit_snapshot(self, model_slot_id: str) -> dict[str, list[dict[str, Any]]]:
        with self._connect() as connection:
            manifests = connection.execute(
                "SELECT * FROM model_slot_manifests WHERE model_slot_id = ? ORDER BY created_at, rowid",
                (model_slot_id,),
            ).fetchall()
            transitions = connection.execute(
                "SELECT * FROM model_lifecycle_transitions WHERE model_slot_id = ? ORDER BY transitioned_at, rowid",
                (model_slot_id,),
            ).fetchall()
        return {
            "manifests": [dict(row) for row in manifests],
            "transitions": [dict(row) for row in transitions],
        }
