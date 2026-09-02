from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from types import SimpleNamespace

from dvs_ai.services.quantum_readiness_service import QuantumReadinessService


@dataclass(frozen=True)
class JourneyStage:
    key: str
    label: str
    state: str
    detail: str


@dataclass(frozen=True)
class OperationalJourneySnapshot:
    stages: tuple[JourneyStage, ...]
    health_history: tuple[dict[str, Any], ...]
    evidence_history: tuple[dict[str, Any], ...]


class OperationalJourneyService:
    """Observe-only lifecycle and trend projection for the commercial dashboard."""

    def __init__(self, db_path: str = "data/dvs_paper_trades.db", *, quantum_required: int = 80) -> None:
        self.db_path = Path(db_path)
        self.quantum_required = max(1, int(quantum_required))

    def snapshot(self) -> OperationalJourneySnapshot:
        try:
            readiness = QuantumReadinessService(str(self.db_path), required=self.quantum_required).snapshot()
        except (sqlite3.Error, KeyError, TypeError, ValueError):
            readiness = SimpleNamespace(
                total_closed=self._closed_count(), eligible=0, calibration_state="UNKNOWN",
                reliability_state="UNKNOWN", state="COLLECTING",
            )
        closed = int(readiness.total_closed)
        eligible = int(readiness.eligible)
        calibration = str(readiness.calibration_state or "UNKNOWN").upper()
        reliability = str(readiness.reliability_state or "UNKNOWN").upper()

        stages = (
            JourneyStage("paper", "PAPER", "COMPLETE" if closed >= self.quantum_required else "COLLECTING", f"{closed}/{self.quantum_required} closed"),
            JourneyStage("calibration", "CALIBRATION", "COMPLETE" if calibration == "VALIDATED" else "WAITING", calibration),
            JourneyStage("reliability", "RELIABILITY", "COMPLETE" if reliability in {"VALIDATED", "SUPPORTED"} else "WAITING", reliability),
            JourneyStage("quantum", "QUANTUM", "READY" if readiness.state == "READY" else "LOCKED", f"{eligible}/{self.quantum_required} eligible"),
            JourneyStage("shadow", "SHADOW PROMOTION", "LOCKED", "Human review required"),
            JourneyStage("main", "MAIN", "IMMUTABLE", "Never auto-promoted"),
        )
        return OperationalJourneySnapshot(stages, self._health_history(), self._evidence_history())


    def _closed_count(self) -> int:
        if not self.db_path.exists():
            return 0
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_trades'").fetchone()
                if not exists:
                    return 0
                return int(conn.execute("SELECT COUNT(*) FROM paper_trades WHERE status='CLOSED'").fetchone()[0] or 0)
        except sqlite3.Error:
            return 0

    def _health_history(self, limit: int = 120) -> tuple[dict[str, Any], ...]:
        if not self.db_path.exists():
            return ()
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_health_history'").fetchone()
                if not exists:
                    return ()
                rows = conn.execute(
                    "SELECT generated_at, score FROM ai_health_history ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return tuple({"time": row[0], "score": float(row[1] or 0.0)} for row in reversed(rows))
        except sqlite3.Error:
            return ()

    def _evidence_history(self, limit: int = 120) -> tuple[dict[str, Any], ...]:
        if not self.db_path.exists():
            return ()
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cols = {row[1] for row in conn.execute("PRAGMA table_info(shadow_observations)")}
                if not cols or "closed_at" not in cols:
                    return ()
                time_col = "closed_at"
                rows = conn.execute(
                    f"SELECT {time_col} FROM shadow_observations WHERE {time_col} IS NOT NULL ORDER BY {time_col}"
                ).fetchall()
            if not rows:
                return ()
            # Build a bounded cumulative series. Downsampling is deterministic.
            total = len(rows)
            step = max(1, total // limit)
            result = []
            for index, row in enumerate(rows, start=1):
                if index == total or index % step == 0:
                    result.append({"time": row[0], "outcomes": index})
            return tuple(result[-limit:])
        except sqlite3.Error:
            return ()
