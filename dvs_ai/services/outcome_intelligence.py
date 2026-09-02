from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

from dvs_ai.services.outcome_infrastructure import canonical_json, utc_now_text

SNAPSHOT_SCHEMA_VERSION = "candidate-feature-snapshot-v1"
DATASET_SCHEMA_VERSION = "outcome-learning-dataset-v1"
RESOLVED_STATUSES = frozenset({"WIN", "LOSS", "INVALID", "AMBIGUOUS", "EXPIRED", "EXPIRED_UNFILLED"})


class NoLearningSamplesError(RuntimeError):
    """Raised when no resolved outcome with an immutable snapshot is exportable."""



@dataclass(frozen=True)
class OutcomeMaturitySummary:
    total_candidates: int
    pending: int
    resolving: int
    resolved: int
    wins: int
    losses: int
    invalid: int
    ambiguous: int
    expired: int
    feature_snapshots: int
    learning_ready: int
    readiness_state: str
    minimum_samples: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OutcomeIntelligenceService:
    """Read-only learning foundation plus immutable feature snapshots.

    This service has no execution, promotion, threshold, or Decision Engine APIs.
    It only captures immutable evidence and builds auditable datasets from resolved outcomes.
    """

    def __init__(self, db_path: str | Path = "data/dvs_paper_trades.db", *, minimum_samples: int = 30) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.minimum_samples = max(1, int(minimum_samples))
        self.ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def ensure_schema(self) -> None:
        with self._connect() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS candidate_feature_snapshots (
                candidate_id TEXT PRIMARY KEY,
                evaluation_id TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                feature_hash TEXT NOT NULL,
                features_json TEXT NOT NULL,
                source TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                FOREIGN KEY(candidate_id) REFERENCES decision_candidates(candidate_id)
            );
            CREATE INDEX IF NOT EXISTS idx_feature_snapshot_hash
            ON candidate_feature_snapshots(feature_hash);
            """)

    @staticmethod
    def _feature_hash(payload: dict[str, Any]) -> str:
        wrapped = {"schema_version": SNAPSHOT_SCHEMA_VERSION, "features": payload}
        return hashlib.sha256(canonical_json(wrapped).encode("utf-8")).hexdigest()

    def capture_feature_snapshot(
        self,
        *,
        candidate_id: str,
        evaluation_id: str,
        features: dict[str, Any],
        source: str = "LIVE_EVALUATION",
        captured_at: str | None = None,
    ) -> str:
        cid = str(candidate_id).strip()
        eid = str(evaluation_id).strip()
        if not cid or not eid:
            raise ValueError("candidate_id and evaluation_id are required")
        payload = dict(features or {})
        if not payload:
            raise ValueError("features must not be empty")
        feature_hash = self._feature_hash(payload)
        feature_json = canonical_json(payload)
        with self._connect() as con:
            exists = con.execute("SELECT 1 FROM decision_candidates WHERE candidate_id=?", (cid,)).fetchone()
            if not exists:
                raise ValueError(f"unknown candidate_id: {cid}")
            current = con.execute(
                "SELECT feature_hash FROM candidate_feature_snapshots WHERE candidate_id=?", (cid,)
            ).fetchone()
            if current:
                if str(current[0]) != feature_hash:
                    raise ValueError("feature snapshot is immutable for an existing candidate")
                return feature_hash
            con.execute(
                """INSERT INTO candidate_feature_snapshots(
                    candidate_id,evaluation_id,schema_version,feature_hash,features_json,source,captured_at
                ) VALUES(?,?,?,?,?,?,?)""",
                (cid, eid, SNAPSHOT_SCHEMA_VERSION, feature_hash, feature_json, str(source), captured_at or utc_now_text()),
            )
        return feature_hash

    def maturity_summary(self) -> OutcomeMaturitySummary:
        counts: dict[str, int] = {}
        with self._connect() as con:
            total = int(con.execute("SELECT COUNT(*) FROM decision_candidates").fetchone()[0])
            for status, n in con.execute("SELECT UPPER(status),COUNT(*) FROM candidate_outcomes GROUP BY UPPER(status)"):
                counts[str(status)] = int(n)
            snapshots = int(con.execute("SELECT COUNT(*) FROM candidate_feature_snapshots").fetchone()[0])
            ready = int(con.execute("""
                SELECT COUNT(*)
                FROM candidate_outcomes o
                JOIN candidate_feature_snapshots f USING(candidate_id)
                WHERE UPPER(o.status) IN ('WIN','LOSS','INVALID','AMBIGUOUS','EXPIRED','EXPIRED_UNFILLED')
                  AND o.outcome_time IS NOT NULL
            """).fetchone()[0])
        resolved = sum(counts.get(x, 0) for x in RESOLVED_STATUSES)
        state = "LEARNING_READY" if ready >= self.minimum_samples else "LEARNING_NOT_READY"
        return OutcomeMaturitySummary(
            total_candidates=total,
            pending=counts.get("PENDING", 0),
            resolving=counts.get("RESOLVING", 0),
            resolved=resolved,
            wins=counts.get("WIN", 0),
            losses=counts.get("LOSS", 0),
            invalid=counts.get("INVALID", 0),
            ambiguous=counts.get("AMBIGUOUS", 0),
            expired=counts.get("EXPIRED", 0) + counts.get("EXPIRED_UNFILLED", 0),
            feature_snapshots=snapshots,
            learning_ready=ready,
            readiness_state=state,
            minimum_samples=self.minimum_samples,
        )

    def build_dataset(self) -> list[dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute("""
                SELECT c.candidate_id,c.setup_episode_id,c.symbol,c.direction,c.cohort,
                       c.activated_at,c.decision_engine_profile_hash,c.trade_plan_profile_hash,
                       c.entry_low,c.entry_high,c.planned_entry,c.invalidation,c.tp1,c.tp2,c.rr_planned,
                       o.status,o.outcome_detail,o.outcome_time,o.outcome_price,o.realized_r,o.mfe_r,o.mae_r,
                       f.evaluation_id,f.schema_version,f.feature_hash,f.features_json,f.source,f.captured_at
                FROM decision_candidates c
                JOIN candidate_outcomes o USING(candidate_id)
                JOIN candidate_feature_snapshots f USING(candidate_id)
                WHERE UPPER(o.status) IN ('WIN','LOSS','INVALID','AMBIGUOUS','EXPIRED','EXPIRED_UNFILLED')
                  AND o.outcome_time IS NOT NULL
                ORDER BY o.outcome_time,c.candidate_id
            """).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["features"] = json.loads(item.pop("features_json"))
            sample_key = {
                "schema_version": DATASET_SCHEMA_VERSION,
                "candidate_id": item["candidate_id"],
                "feature_hash": item["feature_hash"],
                "outcome": item["status"],
                "outcome_time": item["outcome_time"],
            }
            item["dataset_schema_version"] = DATASET_SCHEMA_VERSION
            item["sample_id"] = hashlib.sha256(canonical_json(sample_key).encode("utf-8")).hexdigest()
            result.append(item)
        return result

    def export_jsonl(self, output_path: str | Path) -> Path:
        path = Path(output_path)
        rows = self.build_dataset()
        if not rows:
            raise NoLearningSamplesError(
                "No learning-ready samples: a sample requires both a resolved outcome and an immutable feature snapshot."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            for row in rows:
                fh.write(canonical_json(row) + "\n")
        return path

    def export_csv(self, output_path: str | Path) -> Path:
        path = Path(output_path)
        rows = self.build_dataset()
        if not rows:
            raise NoLearningSamplesError(
                "No learning-ready samples: a sample requires both a resolved outcome and an immutable feature snapshot."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        columns = [
            "sample_id", "candidate_id", "setup_episode_id", "symbol", "direction", "cohort",
            "status", "outcome_detail", "outcome_time", "realized_r", "mfe_r", "mae_r",
            "feature_hash", "features_json", "decision_engine_profile_hash", "trade_plan_profile_hash",
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                flat = dict(row)
                flat["features_json"] = canonical_json(flat.pop("features"))
                writer.writerow({key: flat.get(key) for key in columns})
        return path
