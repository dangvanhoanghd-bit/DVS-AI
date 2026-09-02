from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .candidate_lifecycle_store import CandidateLifecycleStore, STATES
from .historical_candidate_store import HistoricalCandidateStore
from .historical_readiness_trend import HistoricalReadinessTrendStore


@dataclass(frozen=True)
class HistoricalIntegrityReport:
    state: str
    candidates: int
    lifecycle_events: int
    snapshots: int
    readiness_events: int
    issues: tuple[str, ...]
    repository_hash: str


class HistoricalEvidenceRepository:
    """Unified, read-only historical evidence view with integrity auditing.

    This repository has no apply, promotion, execution, or mutation APIs. It joins
    lifecycle, performance, readiness and promotion audit evidence for dashboards
    and offline review.
    """

    def __init__(self, db_path: str = "data/dvs_paper_trades.db",
                 promotion_dir: str = "data/shadow_promotions") -> None:
        self.db_path = Path(db_path)
        self.promotion_dir = Path(promotion_dir)
        self.lifecycle = CandidateLifecycleStore(str(self.db_path))
        self.performance = HistoricalCandidateStore(str(self.db_path))
        self.readiness = HistoricalReadinessTrendStore(str(self.db_path))

    @staticmethod
    def _finite(value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
            return number if math.isfinite(number) else default
        except (TypeError, ValueError):
            return default

    def candidate_ids(self, *, include_archived: bool = True) -> list[str]:
        ids = {row["candidate_id"] for row in self.lifecycle.candidates(include_archived=include_archived)}
        # Include candidates that only have snapshots (e.g. imported history).
        try:
            import sqlite3
            with sqlite3.connect(str(self.db_path)) as conn:
                rows = conn.execute("SELECT DISTINCT candidate_id FROM candidate_performance_snapshots").fetchall()
            ids.update(str(row[0]) for row in rows if row and row[0])
        except Exception:
            pass
        return sorted(ids)

    def promotion_records(self, candidate_id: str | None = None) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if not self.promotion_dir.exists():
            return records
        for path in sorted(self.promotion_dir.glob("promotion_*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            cid = str(payload.get("candidate_id") or payload.get("candidate_schema") or path.stem)
            if candidate_id is not None and cid != str(candidate_id):
                continue
            records.append({**payload, "candidate_id": cid, "audit_path": str(path)})
        return records

    def dossier(self, candidate_id: str) -> dict[str, Any]:
        cid = str(candidate_id).strip()
        lifecycle = [asdict(x) for x in self.lifecycle.events(cid)]
        snapshots = [asdict(x) for x in self.performance.snapshots(cid, limit=100000)]
        readiness = self.readiness.events(cid)
        promotions = self.promotion_records(cid)
        current = self.lifecycle.current_state(cid) or "UNKNOWN"
        latest = snapshots[-1] if snapshots else {}
        created_at = lifecycle[0]["occurred_at"] if lifecycle else ""
        updated_candidates = {x["candidate_id"]: x for x in self.lifecycle.candidates()}
        updated_at = updated_candidates.get(cid, {}).get("updated_at", created_at)
        return {
            "candidate_id": cid,
            "state": current,
            "created_at": created_at,
            "updated_at": updated_at,
            "lifecycle": lifecycle,
            "snapshots": snapshots,
            "readiness": readiness,
            "promotions": promotions,
            "latest": latest,
            "archived": current == "ARCHIVED",
            "event_count": len(lifecycle),
            "snapshot_count": len(snapshots),
            "readiness_count": len(readiness),
        }

    def comparison(self, candidate_ids: list[str] | None = None) -> list[dict[str, Any]]:
        ids = candidate_ids or self.candidate_ids()
        rows: list[dict[str, Any]] = []
        for cid in ids:
            dossier = self.dossier(cid)
            latest = dict(dossier.get("latest") or {})
            readiness = dossier.get("readiness") or []
            readiness_state = readiness[-1].get("state", "NOT_EVALUATED") if readiness else "NOT_EVALUATED"
            rows.append({
                "candidate_id": cid,
                "state": dossier["state"],
                "readiness_state": readiness_state,
                "snapshots": dossier["snapshot_count"],
                "observations": int(latest.get("observations", 0) or 0),
                "expectancy": self._finite(latest.get("expectancy")),
                "max_drawdown": self._finite(latest.get("max_drawdown")),
                "win_rate": self._finite(latest.get("win_rate")),
                "profit_factor": self._finite(latest.get("profit_factor")),
                "brier": self._finite(latest.get("brier")),
                "ece": self._finite(latest.get("ece")),
                "reliability": self._finite(latest.get("reliability")),
                "coverage": self._finite(latest.get("coverage")),
                "drift_state": str(latest.get("drift_state", "UNKNOWN")),
                "captured_at": str(latest.get("captured_at", "")),
                "archived": bool(dossier["archived"]),
            })
        return sorted(
            rows,
            key=lambda x: (
                x["readiness_state"] == "READY_FOR_REVIEW",
                x["expectancy"],
                -x["max_drawdown"],
                x["observations"],
            ),
            reverse=True,
        )

    def audit_integrity(self) -> HistoricalIntegrityReport:
        issues: list[str] = []
        lifecycle_count = snapshot_count = readiness_count = 0
        digest_rows: list[str] = []
        for cid in self.candidate_ids():
            dossier = self.dossier(cid)
            lifecycle = dossier["lifecycle"]
            snapshots = dossier["snapshots"]
            readiness = dossier["readiness"]
            lifecycle_count += len(lifecycle)
            snapshot_count += len(snapshots)
            readiness_count += len(readiness)

            previous_state = None
            previous_time = ""
            for event in lifecycle:
                if event["new_state"] not in STATES:
                    issues.append(f"{cid}: unsupported lifecycle state {event['new_state']}")
                if event["previous_state"] != previous_state:
                    issues.append(f"{cid}: lifecycle chain mismatch at event {event['event_id']}")
                if previous_time and str(event["occurred_at"]) < previous_time:
                    issues.append(f"{cid}: lifecycle timestamp regression")
                previous_state = event["new_state"]
                previous_time = str(event["occurred_at"])

            previous_obs = -1
            previous_capture = ""
            snapshot_ids = set()
            for snap in snapshots:
                snapshot_ids.add(int(snap["snapshot_id"]))
                if int(snap["observations"]) < previous_obs:
                    issues.append(f"{cid}: observation count regressed")
                if previous_capture and str(snap["captured_at"]) < previous_capture:
                    issues.append(f"{cid}: snapshot timestamp regression")
                previous_obs = int(snap["observations"])
                previous_capture = str(snap["captured_at"])

            seen_readiness_snapshots = set()
            for event in readiness:
                sid = int(event.get("snapshot_id", -1))
                if sid in seen_readiness_snapshots:
                    issues.append(f"{cid}: duplicate readiness event for snapshot {sid}")
                seen_readiness_snapshots.add(sid)
                if sid not in snapshot_ids:
                    issues.append(f"{cid}: readiness event references missing snapshot {sid}")

            if dossier["archived"] and not lifecycle:
                issues.append(f"{cid}: archived candidate has no lifecycle history")
            digest_rows.append(json.dumps(dossier, sort_keys=True, default=str))

        digest = hashlib.sha256("\n".join(digest_rows).encode("utf-8")).hexdigest()
        state = "PASS" if not issues else "FAIL"
        return HistoricalIntegrityReport(
            state=state,
            candidates=len(self.candidate_ids()),
            lifecycle_events=lifecycle_count,
            snapshots=snapshot_count,
            readiness_events=readiness_count,
            issues=tuple(issues),
            repository_hash=digest,
        )
