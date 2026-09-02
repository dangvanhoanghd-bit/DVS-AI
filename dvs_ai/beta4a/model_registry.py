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
from typing import Any, Callable, Mapping

from .contracts import ModelSlotManifest, ModelSlotState
from .errors import Beta4AGateError

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, '__dataclass_fields__'):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(v) for v in value]
    return value


def _sha256_json(payload: Any) -> str:
    raw = json.dumps(_jsonable(payload), sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


_ALLOWED: dict[ModelSlotState, frozenset[ModelSlotState]] = {
    ModelSlotState.EMPTY: frozenset({ModelSlotState.RESERVED}),
    ModelSlotState.RESERVED: frozenset({ModelSlotState.TRAINING, ModelSlotState.REJECTED}),
    ModelSlotState.TRAINING: frozenset({ModelSlotState.TRAINED_UNVALIDATED, ModelSlotState.REJECTED}),
    ModelSlotState.TRAINED_UNVALIDATED: frozenset({ModelSlotState.REJECTED}),
    ModelSlotState.VALIDATED: frozenset(),
    ModelSlotState.REJECTED: frozenset(),
}


class ModelRegistry:
    """Immutable Model Slot artifact store with a derived current-state index.

    VALIDATED is intentionally excluded from generic transitions and can only be
    reached through ModelLifecycleGate. The registry stores every sealed
    manifest and transition; ``model_slot_current`` is rebuildable derived data.
    """

    def __init__(self, *, state_db_path: str | Path, clock: Clock = _utc_now) -> None:
        self._db_path = str(state_db_path)
        self._clock = clock
        self._schema_lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode = WAL')
        conn.execute('PRAGMA foreign_keys = ON')
        return conn

    def _ensure_schema(self) -> None:
        with self._schema_lock, self._connect() as conn:
            conn.executescript('''
            CREATE TABLE IF NOT EXISTS model_registry_manifests (
                manifest_sha256 TEXT PRIMARY KEY,
                model_slot_id TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS model_registry_transitions (
                transition_id TEXT PRIMARY KEY,
                model_slot_id TEXT NOT NULL,
                source_state TEXT,
                target_state TEXT NOT NULL,
                source_manifest_sha256 TEXT,
                target_manifest_sha256 TEXT NOT NULL,
                reason TEXT NOT NULL,
                transitioned_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS model_slot_current (
                model_slot_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                manifest_sha256 TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            ''')

    @staticmethod
    def _block(code: str, message: str) -> None:
        raise Beta4AGateError(code, message)

    def create_empty_slot(self, manifest: ModelSlotManifest, *, reason: str = 'slot_created') -> str:
        if manifest.state is not ModelSlotState.EMPTY:
            self._block('MODEL_SLOT_INITIAL_STATE_INVALID', 'new model slots must start EMPTY')
        return self._insert_initial(manifest, reason=reason)

    def _insert_initial(self, manifest: ModelSlotManifest, *, reason: str) -> str:
        payload = _jsonable(manifest)
        sha = _sha256_json(payload)
        now = _iso(self._clock())
        transition_id = uuid.uuid4().hex
        transition_payload = {
            'transition_id': transition_id,
            'model_slot_id': manifest.model_slot_id,
            'source_state': None,
            'target_state': manifest.state.value,
            'source_manifest_sha256': None,
            'target_manifest_sha256': sha,
            'reason': reason,
            'transitioned_at': now,
        }
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                if conn.execute('SELECT 1 FROM model_slot_current WHERE model_slot_id=?', (manifest.model_slot_id,)).fetchone():
                    self._block('MODEL_SLOT_ALREADY_EXISTS', manifest.model_slot_id)
                conn.execute('INSERT INTO model_registry_manifests VALUES (?,?,?,?,?)',
                             (sha, manifest.model_slot_id, manifest.state.value, now, json.dumps(payload, sort_keys=True)))
                conn.execute('INSERT INTO model_registry_transitions VALUES (?,?,?,?,?,?,?,?,?)',
                             (transition_id, manifest.model_slot_id, None, manifest.state.value, None, sha, reason, now,
                              json.dumps(transition_payload, sort_keys=True)))
                conn.execute('INSERT INTO model_slot_current VALUES (?,?,?,?)',
                             (manifest.model_slot_id, manifest.state.value, sha, now))
                conn.execute('COMMIT')
            except Exception:
                if conn.in_transaction:
                    conn.execute('ROLLBACK')
                raise
        return sha

    def transition(self, *, model_slot_id: str, target_state: ModelSlotState, reason: str) -> ModelSlotManifest:
        if target_state is ModelSlotState.VALIDATED:
            self._block('MODEL_SLOT_VALIDATION_GATE_REQUIRED', 'VALIDATED requires ModelLifecycleGate')
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                current = conn.execute('SELECT * FROM model_slot_current WHERE model_slot_id=?', (model_slot_id,)).fetchone()
                if current is None:
                    self._block('MODEL_SLOT_NOT_FOUND', model_slot_id)
                source_state = ModelSlotState(current['state'])
                if target_state not in _ALLOWED[source_state]:
                    self._block('MODEL_SLOT_TRANSITION_NOT_ALLOWED', f'{source_state.value}->{target_state.value}')
                source_row = conn.execute('SELECT payload_json FROM model_registry_manifests WHERE manifest_sha256=?',
                                          (current['manifest_sha256'],)).fetchone()
                data = json.loads(source_row['payload_json'])
                from .contracts import FeatureSchemaIdentity
                source = ModelSlotManifest(
                    model_slot_id=data['model_slot_id'], state=ModelSlotState(data['state']),
                    policy_identity=tuple(data['policy_identity']), extraction_identity=tuple(data['extraction_identity']),
                    feature_schema_identity=FeatureSchemaIdentity(**data['feature_schema_identity']),
                    source_bundle_sha256=data['source_bundle_sha256'], source_split_sha256=data['source_split_sha256'],
                    model_artifact_sha256=data.get('model_artifact_sha256'),
                    feature_matrix_sha256=data.get('feature_matrix_sha256'),
                    training_config_sha256=data.get('training_config_sha256'),
                    training_run_id=data.get('training_run_id'))
                target = replace(source, state=target_state)
                target_payload = _jsonable(target)
                target_sha = _sha256_json(target_payload)
                now = _iso(self._clock())
                transition_id = uuid.uuid4().hex
                trans = {'transition_id': transition_id, 'model_slot_id': model_slot_id,
                         'source_state': source_state.value, 'target_state': target_state.value,
                         'source_manifest_sha256': current['manifest_sha256'],
                         'target_manifest_sha256': target_sha, 'reason': reason, 'transitioned_at': now}
                conn.execute('INSERT OR IGNORE INTO model_registry_manifests VALUES (?,?,?,?,?)',
                             (target_sha, model_slot_id, target_state.value, now, json.dumps(target_payload, sort_keys=True)))
                conn.execute('INSERT INTO model_registry_transitions VALUES (?,?,?,?,?,?,?,?,?)',
                             (transition_id, model_slot_id, source_state.value, target_state.value,
                              current['manifest_sha256'], target_sha, reason, now, json.dumps(trans, sort_keys=True)))
                conn.execute('UPDATE model_slot_current SET state=?, manifest_sha256=?, updated_at=? WHERE model_slot_id=?',
                             (target_state.value, target_sha, now, model_slot_id))
                conn.execute('COMMIT')
                return target
            except Exception:
                if conn.in_transaction:
                    conn.execute('ROLLBACK')
                raise

    def get_current(self, model_slot_id: str) -> ModelSlotManifest | None:
        with self._connect() as conn:
            row = conn.execute('''SELECT m.payload_json FROM model_slot_current c
                                  JOIN model_registry_manifests m ON m.manifest_sha256=c.manifest_sha256
                                  WHERE c.model_slot_id=?''', (model_slot_id,)).fetchone()
        if row is None:
            return None
        data = json.loads(row['payload_json'])
        from .contracts import FeatureSchemaIdentity
        return ModelSlotManifest(
            model_slot_id=data['model_slot_id'], state=ModelSlotState(data['state']),
            policy_identity=tuple(data['policy_identity']), extraction_identity=tuple(data['extraction_identity']),
            feature_schema_identity=FeatureSchemaIdentity(**data['feature_schema_identity']),
            source_bundle_sha256=data['source_bundle_sha256'], source_split_sha256=data['source_split_sha256'],
            model_artifact_sha256=data.get('model_artifact_sha256'),
            feature_matrix_sha256=data.get('feature_matrix_sha256'),
            training_config_sha256=data.get('training_config_sha256'),
            training_run_id=data.get('training_run_id'))

    def bind_trained_artifact(
        self,
        *,
        model_slot_id: str,
        model_artifact_sha256: str,
        feature_matrix_sha256: str,
        training_config_sha256: str,
        training_run_id: str,
        reason: str = "training_artifact_bound",
    ) -> ModelSlotManifest:
        """Seal artifact identity into a TRAINED_UNVALIDATED manifest."""
        current = self.get_current(model_slot_id)
        if current is None:
            self._block('MODEL_SLOT_NOT_FOUND', model_slot_id)
        if current.state is not ModelSlotState.TRAINED_UNVALIDATED:
            self._block('MODEL_SLOT_ARTIFACT_BINDING_STATE_INVALID', current.state.value)
        target = replace(
            current,
            model_artifact_sha256=model_artifact_sha256,
            feature_matrix_sha256=feature_matrix_sha256,
            training_config_sha256=training_config_sha256,
            training_run_id=training_run_id,
        )
        payload = _jsonable(target)
        target_sha = _sha256_json(payload)
        now = _iso(self._clock())
        transition_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                row = conn.execute('SELECT * FROM model_slot_current WHERE model_slot_id=?', (model_slot_id,)).fetchone()
                if row is None or row['state'] != ModelSlotState.TRAINED_UNVALIDATED.value:
                    self._block('MODEL_SLOT_ARTIFACT_BINDING_STATE_INVALID', model_slot_id)
                conn.execute('INSERT OR IGNORE INTO model_registry_manifests VALUES (?,?,?,?,?)',
                             (target_sha, model_slot_id, target.state.value, now, json.dumps(payload, sort_keys=True)))
                trans = {'transition_id': transition_id, 'model_slot_id': model_slot_id,
                         'source_state': target.state.value, 'target_state': target.state.value,
                         'source_manifest_sha256': row['manifest_sha256'],
                         'target_manifest_sha256': target_sha, 'reason': reason, 'transitioned_at': now}
                conn.execute('INSERT INTO model_registry_transitions VALUES (?,?,?,?,?,?,?,?,?)',
                             (transition_id, model_slot_id, target.state.value, target.state.value,
                              row['manifest_sha256'], target_sha, reason, now, json.dumps(trans, sort_keys=True)))
                conn.execute('UPDATE model_slot_current SET manifest_sha256=?, updated_at=? WHERE model_slot_id=?',
                             (target_sha, now, model_slot_id))
                conn.execute('COMMIT')
            except Exception:
                if conn.in_transaction:
                    conn.execute('ROLLBACK')
                raise
        return target

    def rebuild_current_index(self) -> None:
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                conn.execute('DELETE FROM model_slot_current')
                rows = conn.execute('''SELECT t.* FROM model_registry_transitions t
                    JOIN (SELECT model_slot_id, MAX(rowid) AS max_rowid FROM model_registry_transitions GROUP BY model_slot_id) x
                    ON t.rowid=x.max_rowid''').fetchall()
                for row in rows:
                    conn.execute('INSERT INTO model_slot_current VALUES (?,?,?,?)',
                                 (row['model_slot_id'], row['target_state'], row['target_manifest_sha256'], row['transitioned_at']))
                conn.execute('COMMIT')
            except Exception:
                if conn.in_transaction:
                    conn.execute('ROLLBACK')
                raise

    def audit_snapshot(self, model_slot_id: str) -> dict[str, list[dict[str, Any]]]:
        with self._connect() as conn:
            manifests = [dict(r) for r in conn.execute('SELECT * FROM model_registry_manifests WHERE model_slot_id=? ORDER BY created_at,rowid', (model_slot_id,))]
            transitions = [dict(r) for r in conn.execute('SELECT * FROM model_registry_transitions WHERE model_slot_id=? ORDER BY transitioned_at,rowid', (model_slot_id,))]
        return {'manifests': manifests, 'transitions': transitions}
