from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

PROFILE_SCHEMA_VERSION = "decision-engine-profile-v1"
TRADE_PLAN_SCHEMA_VERSION = "trade-plan-profile-v1"
FINGERPRINT_SCHEMA_VERSION = "setup-fingerprint-v1"
CANDIDATE_CAPTURE_SCHEMA_VERSION = "candidate-capture-v1"

EXECUTION_TIMEFRAME = "15m"
MAXIMUM_ENTRY_WAIT_BARS = 8
EPISODE_GAP_BARS = 2
ZONE_BUCKET_ATR_FRACTION = Decimal("0.50000000")


def utc_now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def canonical_symbol(symbol: str) -> str:
    text = str(symbol or "").strip().upper().replace("-", "/")
    if "/" not in text and text.endswith("USDT"):
        text = f"{text[:-4]}/USDT"
    return text


def _canonical_value(value: Any) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {str(k): _canonical_value(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple, set)):
        return [_canonical_value(v) for v in value]
    if isinstance(value, Decimal):
        return format(value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_EVEN), "f")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Profile payload contains non-finite float")
        return format(Decimal(str(value)).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_EVEN), "f")
    return value


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(_canonical_value(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def decision_engine_profile_hash(payload: dict[str, Any]) -> str:
    wrapped = {"schema_version": PROFILE_SCHEMA_VERSION, **payload}
    return canonical_hash(wrapped)


def trade_plan_profile_hash(payload: dict[str, Any] | None = None) -> str:
    wrapped = {
        "schema_version": TRADE_PLAN_SCHEMA_VERSION,
        "execution_timeframe": EXECUTION_TIMEFRAME,
        "maximum_entry_wait_bars": MAXIMUM_ENTRY_WAIT_BARS,
        "entry_touch_policy": "ZONE_TOUCH",
        "entry_expiry_policy": "BAR_COUNT_OR_INVALIDATION",
        "invalidation_before_entry_policy": "EXPIRED_UNFILLED",
        "cancellation_rule_version": "v1",
        **(payload or {}),
    }
    return canonical_hash(wrapped)


def candidate_capture_profile_hash() -> str:
    return canonical_hash({
        "schema_version": CANDIDATE_CAPTURE_SCHEMA_VERSION,
        "cohorts": ["CENSUS", "ISOLATED_REJECTION", "COMPOUND_REJECTION"],
        "statistical_unit": "SETUP_EPISODE",
        "activation_policy": "FIRST_VALID_TRADE_PLAN_AND_CENSUS_ELIGIBLE",
        "outcome_plan_policy": "FIRST_ELIGIBLE_PLAN",
    })


def lifecycle_family(value: str) -> str:
    state = str(value or "UNFORMED").upper()
    if state in {"EARLY_FORMATION"}:
        return "FORMING"
    if state in {"FIRST_RETEST", "RETEST"}:
        return "RETEST"
    if state in {"CONFIRMED", "CONFIRMED_TREND", "SETUP"}:
        return "TRENDING"
    if state in {"LATE", "LATE_TREND", "EXHAUSTION"}:
        return "LATE"
    return "UNFORMED"


def structural_event_id(*, event_type: str | None, event_timestamp: str | None, timeframe: str = EXECUTION_TIMEFRAME) -> str:
    event = str(event_type or "NONE").upper()
    if event in {"", "NONE", "FALSE"} or not event_timestamp:
        return "NONE"
    return f"{event}:{timeframe}:{event_timestamp}"


def zone_identity(level: float, atr: float, min_tick_size: float = 1e-12) -> tuple[int, float]:
    bucket = max(float(ZONE_BUCKET_ATR_FRACTION) * abs(float(atr)), float(min_tick_size))
    return int(round(float(level) / bucket)), bucket


def setup_fingerprint(*, symbol: str, direction: str, primary_zone_id: int, event_id: str,
                      lifecycle: str, decision_profile_hash: str, plan_profile_hash: str) -> str:
    return canonical_hash({
        "schema_version": FINGERPRINT_SCHEMA_VERSION,
        "symbol": canonical_symbol(symbol),
        "direction": str(direction).upper(),
        "execution_timeframe": EXECUTION_TIMEFRAME,
        "primary_zone_id": int(primary_zone_id),
        "structural_event_id": event_id,
        "lifecycle_family": lifecycle_family(lifecycle),
        "decision_engine_profile_hash": decision_profile_hash,
        "trade_plan_profile_hash": plan_profile_hash,
    })


def valid_trade_plan(*, direction: str, entry_low: float, entry_high: float, invalidation: float,
                     tp1: float | None, tp2: float | None) -> bool:
    values = [entry_low, entry_high, invalidation]
    if any(v is None for v in values):
        return False
    if not all(math.isfinite(float(v)) for v in values):
        return False
    if float(entry_low) > float(entry_high):
        return False
    target = tp2 if tp2 is not None else tp1
    if target is None or not math.isfinite(float(target)):
        return False
    planned = (float(entry_low) + float(entry_high)) / 2.0
    risk = abs(planned - float(invalidation))
    reward = abs(float(target) - planned)
    return str(direction).upper() in {"LONG", "SHORT"} and risk > 0 and reward > 0


class OutcomeInfrastructureStore:
    """Canonical episode/candidate/outcome schema inside the paper database."""

    def __init__(self, db_path: str | Path = "data/dvs_paper_trades.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    def connect(self):
        con = sqlite3.connect(self.db_path, timeout=30)
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def ensure_schema(self) -> None:
        with self.connect() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS setup_episodes (
                setup_episode_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                decision_engine_profile_hash TEXT NOT NULL,
                trade_plan_profile_hash TEXT NOT NULL,
                candidate_capture_profile_hash TEXT NOT NULL,
                setup_fingerprint TEXT NOT NULL,
                primary_zone_id INTEGER NOT NULL,
                structural_event_id TEXT NOT NULL,
                lifecycle_family TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                started_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                closed_at TEXT,
                first_evaluation_id TEXT NOT NULL,
                activation_evaluation_id TEXT,
                evaluation_count INTEGER NOT NULL DEFAULT 0,
                initial_gate_set TEXT NOT NULL DEFAULT '[]',
                activation_gate_set TEXT,
                episode_class TEXT,
                eventually_accepted INTEGER NOT NULL DEFAULT 0,
                candidate_id TEXT UNIQUE
            );
            CREATE INDEX IF NOT EXISTS idx_episode_lookup
            ON setup_episodes(symbol,direction,status,last_seen_at);

            CREATE TABLE IF NOT EXISTS episode_evaluations (
                setup_episode_id TEXT NOT NULL,
                evaluation_id TEXT NOT NULL,
                sequence_number INTEGER NOT NULL,
                evaluated_at TEXT NOT NULL,
                entry_score REAL NOT NULL,
                confidence REAL NOT NULL,
                opportunity_score REAL,
                gate_set_json TEXT NOT NULL,
                trade_plan_similarity REAL,
                PRIMARY KEY(setup_episode_id,evaluation_id),
                FOREIGN KEY(setup_episode_id) REFERENCES setup_episodes(setup_episode_id)
            );

            CREATE TABLE IF NOT EXISTS decision_candidates (
                candidate_id TEXT PRIMARY KEY,
                setup_episode_id TEXT NOT NULL UNIQUE,
                activation_evaluation_id TEXT NOT NULL,
                activated_at TEXT NOT NULL,
                cohort TEXT NOT NULL,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                decision_engine_profile_hash TEXT NOT NULL,
                trade_plan_profile_hash TEXT NOT NULL,
                entry_low REAL NOT NULL,
                entry_high REAL NOT NULL,
                planned_entry REAL NOT NULL,
                invalidation REAL NOT NULL,
                tp1 REAL,
                tp2 REAL,
                rr_planned REAL NOT NULL,
                entry_wait_started_at TEXT NOT NULL,
                entry_expiry_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'WAITING_ENTRY',
                expiration_reason TEXT,
                fill_price REAL,
                fill_time TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(setup_episode_id) REFERENCES setup_episodes(setup_episode_id)
            );
            CREATE INDEX IF NOT EXISTS idx_candidate_status
            ON decision_candidates(status,entry_expiry_at);

            CREATE TABLE IF NOT EXISTS candidate_gate_rejections (
                candidate_id TEXT NOT NULL,
                gate_code TEXT NOT NULL,
                gate_ordinal INTEGER NOT NULL,
                PRIMARY KEY(candidate_id,gate_code),
                FOREIGN KEY(candidate_id) REFERENCES decision_candidates(candidate_id)
            );

            CREATE TABLE IF NOT EXISTS candidate_outcomes (
                outcome_id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                resolver_profile_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                outcome_detail TEXT,
                outcome_time TEXT,
                outcome_price REAL,
                realized_r REAL,
                mfe_r REAL,
                mae_r REAL,
                resolution_claim_id TEXT,
                resolution_claimed_at TEXT,
                resolver_version TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(candidate_id,resolver_profile_hash),
                FOREIGN KEY(candidate_id) REFERENCES decision_candidates(candidate_id)
            );

            CREATE TABLE IF NOT EXISTS candidate_outcome_events (
                event_id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                outcome_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_time TEXT NOT NULL,
                price REAL,
                realized_r REAL,
                mfe_r REAL,
                mae_r REAL,
                detail TEXT,
                resolver_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(candidate_id) REFERENCES decision_candidates(candidate_id),
                FOREIGN KEY(outcome_id) REFERENCES candidate_outcomes(outcome_id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_candidate_outcome_event_unique
            ON candidate_outcome_events(candidate_id,event_type,event_time,COALESCE(detail,''));
            CREATE INDEX IF NOT EXISTS idx_candidate_outcome_event_timeline
            ON candidate_outcome_events(candidate_id,event_time,event_type);

            CREATE TABLE IF NOT EXISTS decision_diagnostic_traces (
                diagnostic_trace_id TEXT PRIMARY KEY,
                evaluation_id TEXT NOT NULL UNIQUE,
                setup_episode_id TEXT,
                decision_engine_profile_hash TEXT NOT NULL,
                trace_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS outcome_resolution_runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                checked INTEGER NOT NULL DEFAULT 0,
                updated INTEGER NOT NULL DEFAULT 0,
                errors INTEGER NOT NULL DEFAULT 0,
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS outcome_resolution_failures (
                failure_id TEXT PRIMARY KEY,
                run_id TEXT,
                source_type TEXT NOT NULL,
                source_record_id TEXT,
                symbol TEXT,
                error_type TEXT NOT NULL,
                error_message TEXT NOT NULL,
                traceback TEXT,
                created_at TEXT NOT NULL
            );
            """)
            self._extend_existing_tables(con)

    @staticmethod
    def _columns(con: sqlite3.Connection, table: str) -> set[str]:
        return {row[1] for row in con.execute(f"PRAGMA table_info({table})")}

    def _extend_existing_tables(self, con: sqlite3.Connection) -> None:
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_trades'").fetchone():
            cols = self._columns(con, "paper_trades")
            migrations = {
                "decision_id": "TEXT", "candidate_id": "TEXT", "outcome_id": "TEXT",
                "decision_engine_profile_hash": "TEXT", "trade_plan_profile_hash": "TEXT",
                "resolver_version": "TEXT", "resolution_claim_id": "TEXT", "resolution_claimed_at": "TEXT",
            }
            for name, ddl in migrations.items():
                if name not in cols:
                    con.execute(f"ALTER TABLE paper_trades ADD COLUMN {name} {ddl}")

    def start_run(self) -> str:
        run_id = uuid4().hex
        with self.connect() as con:
            con.execute("INSERT INTO outcome_resolution_runs(run_id,started_at,status) VALUES(?,?,?)",
                        (run_id, utc_now_text(), "RUNNING"))
        return run_id

    def finish_run(self, run_id: str, *, status: str, checked: int, updated: int, errors: int,
                   error_message: str | None = None) -> None:
        with self.connect() as con:
            con.execute("""UPDATE outcome_resolution_runs SET finished_at=?,status=?,checked=?,updated=?,errors=?,error_message=? WHERE run_id=?""",
                        (utc_now_text(), status, checked, updated, errors, error_message, run_id))

    def record_failure(self, *, run_id: str | None, source_type: str, source_record_id: str | None,
                       symbol: str | None, exc: BaseException, traceback_text: str | None = None) -> None:
        with self.connect() as con:
            con.execute("""INSERT INTO outcome_resolution_failures VALUES(?,?,?,?,?,?,?,?,?)""", (
                uuid4().hex, run_id, source_type, source_record_id, symbol,
                type(exc).__name__, str(exc)[:2000], traceback_text, utc_now_text()
            ))

    def find_open_episode(self, *, symbol: str, direction: str, decision_hash: str, plan_hash: str,
                          evaluated_at: str, gap_minutes: int = 30) -> sqlite3.Row | None:
        cutoff = (datetime.strptime(evaluated_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                  - timedelta(minutes=gap_minutes)).strftime("%Y-%m-%d %H:%M:%S")
        with self.connect() as con:
            con.row_factory = sqlite3.Row
            return con.execute("""SELECT * FROM setup_episodes WHERE symbol=? AND direction=?
                AND decision_engine_profile_hash=? AND trade_plan_profile_hash=? AND status='OPEN'
                AND last_seen_at>=? ORDER BY last_seen_at DESC LIMIT 1""",
                (canonical_symbol(symbol), direction.upper(), decision_hash, plan_hash, cutoff)).fetchone()

    def create_episode(self, **fields: Any) -> str:
        episode_id = fields.pop("setup_episode_id", uuid4().hex)
        with self.connect() as con:
            con.execute("""INSERT INTO setup_episodes(
                setup_episode_id,symbol,direction,decision_engine_profile_hash,trade_plan_profile_hash,
                candidate_capture_profile_hash,setup_fingerprint,primary_zone_id,structural_event_id,
                lifecycle_family,status,started_at,last_seen_at,first_evaluation_id,initial_gate_set,evaluation_count)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                episode_id, canonical_symbol(fields["symbol"]), fields["direction"].upper(),
                fields["decision_engine_profile_hash"], fields["trade_plan_profile_hash"],
                fields.get("candidate_capture_profile_hash", candidate_capture_profile_hash()),
                fields["setup_fingerprint"], fields["primary_zone_id"], fields["structural_event_id"],
                fields["lifecycle_family"], "OPEN", fields["evaluated_at"], fields["evaluated_at"],
                fields["evaluation_id"], json.dumps(fields.get("gate_set", []), separators=(",", ":")), 0
            ))
        return episode_id

    def append_evaluation(self, *, episode_id: str, evaluation_id: str, evaluated_at: str,
                          entry_score: float, confidence: float, opportunity_score: float | None,
                          gate_set: Iterable[str], trade_plan_similarity: float | None = None) -> None:
        gate_json = json.dumps(sorted(set(gate_set)), separators=(",", ":"))
        with self.connect() as con:
            sequence = con.execute("SELECT evaluation_count FROM setup_episodes WHERE setup_episode_id=?",
                                   (episode_id,)).fetchone()[0] + 1
            con.execute("""INSERT OR IGNORE INTO episode_evaluations VALUES(?,?,?,?,?,?,?,?,?)""",
                        (episode_id, evaluation_id, sequence, evaluated_at, entry_score, confidence,
                         opportunity_score, gate_json, trade_plan_similarity))
            con.execute("UPDATE setup_episodes SET last_seen_at=?,evaluation_count=MAX(evaluation_count,?) WHERE setup_episode_id=?",
                        (evaluated_at, sequence, episode_id))

    def record_diagnostic_trace(self, *, evaluation_id: str, episode_id: str | None,
                                decision_hash: str, trace: dict[str, Any]) -> None:
        """Persist the exact score/gate breakdown used by one live evaluation."""
        with self.connect() as con:
            con.execute(
                """INSERT OR IGNORE INTO decision_diagnostic_traces(
                    diagnostic_trace_id,evaluation_id,setup_episode_id,
                    decision_engine_profile_hash,trace_json,created_at
                ) VALUES(?,?,?,?,?,?)""",
                (uuid4().hex, evaluation_id, episode_id, decision_hash,
                 canonical_json(trace), utc_now_text()),
            )

    def activate_candidate(self, *, episode_id: str, evaluation_id: str, activated_at: str,
                           symbol: str, direction: str, decision_hash: str, plan_hash: str,
                           gate_set: Iterable[str], entry_low: float, entry_high: float,
                           invalidation: float, tp1: float | None, tp2: float | None) -> str:
        candidate_id = uuid4().hex
        gates = sorted(set(gate_set))
        cohort = "ISOLATED_REJECTION" if len(gates) == 1 else "COMPOUND_REJECTION" if len(gates) > 1 else "CENSUS"
        planned = (float(entry_low) + float(entry_high)) / 2.0
        target = float(tp2 if tp2 is not None else tp1)
        risk = max(abs(planned - float(invalidation)), 1e-12)
        rr = abs(target - planned) / risk
        start_dt = datetime.strptime(activated_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        expiry = start_dt + timedelta(minutes=15 * MAXIMUM_ENTRY_WAIT_BARS)
        with self.connect() as con:
            con.execute("""INSERT INTO decision_candidates(
                candidate_id,setup_episode_id,activation_evaluation_id,activated_at,cohort,symbol,direction,
                decision_engine_profile_hash,trade_plan_profile_hash,entry_low,entry_high,planned_entry,
                invalidation,tp1,tp2,rr_planned,entry_wait_started_at,entry_expiry_at,status,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                candidate_id, episode_id, evaluation_id, activated_at, cohort, canonical_symbol(symbol),
                direction.upper(), decision_hash, plan_hash, entry_low, entry_high, planned, invalidation,
                tp1, tp2, rr, activated_at, expiry.strftime("%Y-%m-%d %H:%M:%S"), "WAITING_ENTRY", utc_now_text()
            ))
            for ordinal, gate in enumerate(gates):
                con.execute("INSERT INTO candidate_gate_rejections VALUES(?,?,?)", (candidate_id, gate, ordinal))
            con.execute("""UPDATE setup_episodes SET activation_evaluation_id=?,activation_gate_set=?,episode_class=?,candidate_id=?
                           WHERE setup_episode_id=?""",
                        (evaluation_id, json.dumps(gates, separators=(",", ":")), cohort, candidate_id, episode_id))
            resolver_hash = canonical_hash({"schema_version": "outcome-resolver-v1", "timeframe": "1m", "ambiguous_policy": "EXPLICIT"})
            now = utc_now_text()
            con.execute("""INSERT OR IGNORE INTO candidate_outcomes(
                outcome_id,candidate_id,resolver_profile_hash,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?)""", (uuid4().hex, candidate_id, resolver_hash, "PENDING", now, now))
        return candidate_id
