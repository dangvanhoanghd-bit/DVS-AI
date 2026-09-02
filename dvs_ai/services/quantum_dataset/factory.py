from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "dvs-quantum-dataset-v1"
MANIFEST_VERSION = "dvs-quantum-dataset-manifest-v1"
POLICY_SCOPE_SCHEMA_VERSION = "dvs-policy-scope-v1"
DECISIVE_OUTCOMES = frozenset({"WIN", "LOSS"})
EXCLUDED_OUTCOMES = frozenset({"AMBIGUOUS", "EXPIRED_UNFILLED", "PENDING", "RESOLVING"})


class QuantumReadinessState(str, Enum):
    DATA_INTEGRITY_BLOCKED = "DATA_INTEGRITY_BLOCKED"
    UNOBSERVABLE = "UNOBSERVABLE"
    DESCRIPTIVE_ONLY = "DESCRIPTIVE_ONLY"
    RESEARCH_CANDIDATE_ONLY = "RESEARCH_CANDIDATE_ONLY"
    VALIDATION_REVIEW_ELIGIBLE = "VALIDATION_REVIEW_ELIGIBLE"


@dataclass(frozen=True)
class IntegrityFinding:
    code: str
    passed: bool
    detail: str
    count: int = 0


@dataclass(frozen=True)
class ResearchEpisode:
    sample_id: str
    setup_episode_id: str
    candidate_id: str
    activation_evaluation_id: str
    first_evaluation_id: str
    first_eligible_timestamp: str
    symbol: str
    direction: str
    lifecycle_family: str
    cohort: str
    decision_engine_checksum: str
    trade_plan_profile_hash: str
    policy_scope_id: str
    policy_scope_hash: str
    outcome_status: str
    realized_r: float | None
    mfe_r: float | None
    mae_r: float | None
    outcome_time: str | None
    market_event_cluster_id: str
    symbol_cluster: str
    source_row_hash: str


@dataclass(frozen=True)
class QuantumDatasetResult:
    state: QuantumReadinessState
    optimizer_allowed: bool
    recommendation_allowed: bool
    shadow_apply_allowed: bool
    raw_episode_count: int
    decisive_count: int
    ambiguous_count: int
    expired_unfilled_count: int
    pending_count: int
    cluster_count: int
    effective_n: float
    cohort_counts: Mapping[str, int]
    findings: tuple[IntegrityFinding, ...]
    episodes: tuple[ResearchEpisode, ...]
    manifest: Mapping[str, Any]

    def export(self, output_dir: str | Path) -> tuple[Path, Path]:
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        dataset_path = root / "quantum_research_dataset.jsonl"
        lines = [canonical_json(asdict(row)) for row in self.episodes]
        dataset_bytes = (("\n".join(lines) + "\n") if lines else "").encode("utf-8")
        dataset_path.write_bytes(dataset_bytes)
        manifest = dict(self.manifest)
        manifest["dataset_file"] = dataset_path.name
        manifest["dataset_sha256"] = hashlib.sha256(dataset_bytes).hexdigest()
        manifest_path = root / "quantum_research_dataset.manifest.json"
        unsigned = canonical_json(manifest).encode("utf-8")
        manifest["self_sha256"] = hashlib.sha256(unsigned).hexdigest()
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return dataset_path, manifest_path


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _canonical_value(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(v) for v in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite value is forbidden in governed artifacts")
        return format(value, ".12g")
    return value


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(_canonical_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00").replace(" UTC", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _cluster_id(timestamp: str, minutes: int = 15) -> str:
    dt = _parse_time(timestamp)
    if dt is None:
        return "UNKNOWN_TIME"
    minute = (dt.minute // minutes) * minutes
    return dt.astimezone(timezone.utc).replace(minute=minute, second=0, microsecond=0).isoformat()


def _kish_ess(sizes: Iterable[int]) -> float:
    vals = [int(x) for x in sizes if int(x) > 0]
    total = sum(vals)
    denom = sum(x * x for x in vals)
    return (total * total / denom) if denom else 0.0


class QuantumDatasetFactory:
    """Read-only boundary from operational outcome DB to immutable research data.

    It deliberately has no optimization, execution, SHADOW-write, or MAIN-write path.
    The source SQLite database is opened in read-only URI mode.
    """

    REQUIRED_TABLES = {
        "setup_episodes", "episode_evaluations", "decision_candidates", "candidate_outcomes"
    }

    def __init__(
        self,
        db_path: str | Path,
        *,
        allowed_parameters_path: str | Path | None = None,
        expected_decision_engine_checksum: str | None = None,
        cluster_minutes: int = 15,
    ) -> None:
        self.db_path = Path(db_path)
        self.allowed_parameters_path = Path(allowed_parameters_path) if allowed_parameters_path else None
        self.expected_decision_engine_checksum = expected_decision_engine_checksum
        self.cluster_minutes = max(1, int(cluster_minutes))

    def _connect_read_only(self) -> sqlite3.Connection:
        uri = f"file:{self.db_path.resolve().as_posix()}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        return con

    def _load_scope_governance(self) -> dict[str, Any]:
        if self.allowed_parameters_path is None:
            return {
                "schema_version": POLICY_SCOPE_SCHEMA_VERSION,
                "scope_name": "decision-engine-profile-hash-only",
                "interacting_parameters": [],
                "operational_parameters_excluded": ["scan_workers", "watchlist", "ui", "logging"],
            }
        payload = json.loads(self.allowed_parameters_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != POLICY_SCOPE_SCHEMA_VERSION:
            raise ValueError("Unsupported allowed-parameter governance schema")
        if not isinstance(payload.get("interacting_parameters", []), list):
            raise ValueError("interacting_parameters must be a list")
        return payload

    def _blocked(self, findings: Sequence[IntegrityFinding], audit: Mapping[str, int] | None = None) -> QuantumDatasetResult:
        audit = dict(audit or {})
        return QuantumDatasetResult(
            state=QuantumReadinessState.DATA_INTEGRITY_BLOCKED,
            optimizer_allowed=False,
            recommendation_allowed=False,
            shadow_apply_allowed=False,
            raw_episode_count=int(audit.get("raw", 0)),
            decisive_count=0,
            ambiguous_count=int(audit.get("ambiguous", 0)),
            expired_unfilled_count=int(audit.get("expired", 0)),
            pending_count=int(audit.get("pending", 0)),
            cluster_count=0,
            effective_n=0.0,
            cohort_counts={},
            findings=tuple(findings),
            episodes=(),
            manifest=self._manifest_base(QuantumReadinessState.DATA_INTEGRITY_BLOCKED, findings, audit),
        )

    def build(self) -> QuantumDatasetResult:
        findings: list[IntegrityFinding] = []
        if not self.db_path.exists():
            return self._blocked([IntegrityFinding("QG01_SOURCE_EXISTS", False, "Operational database does not exist")])
        try:
            scope = self._load_scope_governance()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return self._blocked([IntegrityFinding("QG15_SCOPE_GOVERNANCE", False, str(exc))])

        with self._connect_read_only() as con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing = sorted(self.REQUIRED_TABLES - tables)
            findings.append(IntegrityFinding("QG01_REQUIRED_TABLES", not missing,
                                             "All required tables present" if not missing else f"Missing: {missing}", len(missing)))
            if missing:
                return self._blocked(findings)

            duplicate_candidates = con.execute(
                "SELECT COUNT(*) FROM (SELECT candidate_id, COUNT(*) n FROM candidate_outcomes GROUP BY candidate_id HAVING n>1)"
            ).fetchone()[0]
            orphan_outcomes = con.execute(
                "SELECT COUNT(*) FROM candidate_outcomes o LEFT JOIN decision_candidates c ON c.candidate_id=o.candidate_id WHERE c.candidate_id IS NULL"
            ).fetchone()[0]
            orphan_candidates = con.execute(
                "SELECT COUNT(*) FROM decision_candidates c LEFT JOIN setup_episodes e ON e.setup_episode_id=c.setup_episode_id WHERE e.setup_episode_id IS NULL"
            ).fetchone()[0]
            chronology_invalid = con.execute("""
                SELECT COUNT(*) FROM candidate_outcomes o
                JOIN decision_candidates c ON c.candidate_id=o.candidate_id
                WHERE o.outcome_time IS NOT NULL AND o.outcome_time < c.activated_at
            """).fetchone()[0]
            findings.extend([
                IntegrityFinding("QG01_DUPLICATE_OUTCOME", duplicate_candidates == 0, "One outcome row per candidate", duplicate_candidates),
                IntegrityFinding("QG01_ORPHAN_OUTCOME", orphan_outcomes == 0, "Every outcome links to a candidate", orphan_outcomes),
                IntegrityFinding("QG01_ORPHAN_CANDIDATE", orphan_candidates == 0, "Every candidate links to an episode", orphan_candidates),
                IntegrityFinding("QG01_CHRONOLOGY", chronology_invalid == 0, "Outcome cannot predate activation", chronology_invalid),
            ])
            if any(not f.passed for f in findings):
                return self._blocked(findings)

            rows = con.execute("""
                SELECT
                    e.setup_episode_id, e.first_evaluation_id, e.activation_evaluation_id,
                    e.lifecycle_family, e.decision_engine_profile_hash,
                    e.trade_plan_profile_hash, e.started_at,
                    c.candidate_id, c.activation_evaluation_id AS candidate_activation_evaluation_id,
                    c.activated_at, c.cohort, c.symbol, c.direction,
                    o.status AS outcome_status, o.outcome_time, o.realized_r, o.mfe_r, o.mae_r,
                    o.resolver_profile_hash
                FROM setup_episodes e
                JOIN decision_candidates c ON c.setup_episode_id=e.setup_episode_id
                LEFT JOIN candidate_outcomes o ON o.candidate_id=c.candidate_id
                ORDER BY c.activated_at ASC, c.candidate_id ASC
            """).fetchall()

        status_counts = Counter(str(r["outcome_status"] or "PENDING").upper() for r in rows)
        episodes: list[ResearchEpisode] = []
        cluster_sizes: Counter[str] = Counter()
        symbol_sizes: Counter[str] = Counter()
        cohort_counts: Counter[str] = Counter()
        checksum_mismatch = 0

        governed_scope = {
            "schema_version": POLICY_SCOPE_SCHEMA_VERSION,
            "scope_name": scope.get("scope_name", "default"),
            "interacting_parameters": scope.get("interacting_parameters", []),
            "scope_governance_hash": canonical_hash(scope),
        }

        for row in rows:
            status = str(row["outcome_status"] or "PENDING").upper()
            if status not in DECISIVE_OUTCOMES:
                continue
            engine_hash = str(row["decision_engine_profile_hash"] or "")
            if self.expected_decision_engine_checksum and engine_hash != self.expected_decision_engine_checksum:
                checksum_mismatch += 1
                continue
            policy_scope_hash = canonical_hash({**governed_scope, "decision_engine_checksum": engine_hash})
            policy_scope_id = f"QPS-{policy_scope_hash[:16].upper()}"
            timestamp = str(row["activated_at"] or row["started_at"] or "")
            event_cluster = _cluster_id(timestamp, self.cluster_minutes)
            symbol = str(row["symbol"] or "UNKNOWN").upper()
            source = {k: row[k] for k in row.keys()}
            source_hash = canonical_hash(source)
            sample_id = f"QDS-{hashlib.sha256((str(row['candidate_id']) + source_hash).encode()).hexdigest()[:24].upper()}"
            item = ResearchEpisode(
                sample_id=sample_id,
                setup_episode_id=str(row["setup_episode_id"]),
                candidate_id=str(row["candidate_id"]),
                activation_evaluation_id=str(row["candidate_activation_evaluation_id"]),
                first_evaluation_id=str(row["first_evaluation_id"]),
                first_eligible_timestamp=timestamp,
                symbol=symbol,
                direction=str(row["direction"] or "UNKNOWN").upper(),
                lifecycle_family=str(row["lifecycle_family"] or "UNKNOWN").upper(),
                cohort=str(row["cohort"] or "UNKNOWN").upper(),
                decision_engine_checksum=engine_hash,
                trade_plan_profile_hash=str(row["trade_plan_profile_hash"] or ""),
                policy_scope_id=policy_scope_id,
                policy_scope_hash=policy_scope_hash,
                outcome_status=status,
                realized_r=float(row["realized_r"]) if row["realized_r"] is not None else None,
                mfe_r=float(row["mfe_r"]) if row["mfe_r"] is not None else None,
                mae_r=float(row["mae_r"]) if row["mae_r"] is not None else None,
                outcome_time=str(row["outcome_time"]) if row["outcome_time"] else None,
                market_event_cluster_id=event_cluster,
                symbol_cluster=symbol,
                source_row_hash=source_hash,
            )
            episodes.append(item)
            cluster_sizes[event_cluster] += 1
            symbol_sizes[symbol] += 1
            cohort_counts[f"direction:{item.direction}"] += 1
            cohort_counts[f"lifecycle:{item.lifecycle_family}"] += 1
            cohort_counts[f"cohort:{item.cohort}"] += 1

        findings.append(IntegrityFinding("QG13_ENGINE_CHECKSUM", checksum_mismatch == 0,
                                         "All decisive samples match expected Decision Engine checksum", checksum_mismatch))
        if checksum_mismatch:
            return self._blocked(findings, {"raw": len(rows), "ambiguous": status_counts["AMBIGUOUS"],
                                            "expired": status_counts["EXPIRED_UNFILLED"], "pending": status_counts["PENDING"]})

        raw_n = len(episodes)
        temporal_ess = _kish_ess(cluster_sizes.values())
        symbol_ess = _kish_ess(symbol_sizes.values())
        effective_n = min([float(raw_n)] + [x for x in (temporal_ess, symbol_ess) if x > 0]) if raw_n else 0.0
        if effective_n < 30:
            state = QuantumReadinessState.UNOBSERVABLE
        elif effective_n < 100:
            state = QuantumReadinessState.DESCRIPTIVE_ONLY
        elif effective_n < 300:
            state = QuantumReadinessState.RESEARCH_CANDIDATE_ONLY
        else:
            state = QuantumReadinessState.VALIDATION_REVIEW_ELIGIBLE
        # Dataset Factory never grants optimizer/recommendation/apply authority by itself.
        allowed = False
        audit = {
            "raw": len(rows), "decisive": raw_n, "ambiguous": status_counts["AMBIGUOUS"],
            "expired": status_counts["EXPIRED_UNFILLED"], "pending": status_counts["PENDING"],
            "cluster_count": len(cluster_sizes), "effective_n": round(effective_n, 6),
        }
        manifest = self._manifest_base(state, findings, audit)
        manifest.update({
            "policy_scope_governance": governed_scope,
            "cohort_counts": dict(sorted(cohort_counts.items())),
            "temporal_cluster_ess": round(temporal_ess, 6),
            "symbol_concentration_ess": round(symbol_ess, 6),
            "safety_boundary": {
                "decision_engine_frozen": True,
                "automatic_tuning": False,
                "optimizer_authority": False,
                "shadow_write_authority": False,
                "main_write_authority": False,
                "exchange_order_capability": False,
            },
        })
        return QuantumDatasetResult(
            state=state, optimizer_allowed=allowed, recommendation_allowed=allowed,
            shadow_apply_allowed=allowed, raw_episode_count=len(rows), decisive_count=raw_n,
            ambiguous_count=status_counts["AMBIGUOUS"], expired_unfilled_count=status_counts["EXPIRED_UNFILLED"],
            pending_count=status_counts["PENDING"], cluster_count=len(cluster_sizes), effective_n=round(effective_n, 6),
            cohort_counts=dict(sorted(cohort_counts.items())), findings=tuple(findings),
            episodes=tuple(episodes), manifest=manifest,
        )

    def _manifest_base(self, state: QuantumReadinessState, findings: Sequence[IntegrityFinding], audit: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "manifest_version": MANIFEST_VERSION,
            "dataset_schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_database": self.db_path.name,
            "source_database_sha256": hashlib.sha256(self.db_path.read_bytes()).hexdigest() if self.db_path.exists() else None,
            "readiness_state": state.value,
            "audit": dict(audit),
            "integrity_findings": [asdict(x) for x in findings],
            "qg_contract": "QG-01..QG-16",
        }
