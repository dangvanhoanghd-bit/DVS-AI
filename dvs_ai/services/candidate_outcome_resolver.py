from __future__ import annotations
import threading
import time

import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from dvs_ai.services.outcome_infrastructure import OutcomeInfrastructureStore, canonical_hash, utc_now_text

RESOLVER_VERSION = "BETA1B-1"
CLAIM_TTL_MINUTES = 15
RESOLVER_PROFILE_HASH = canonical_hash({
    "schema_version": "candidate-outcome-resolver-v2",
    "timeframe": "1m",
    "entry_policy": "ZONE_TOUCH",
    "ambiguous_policy": "EXPLICIT",
    "claim_ttl_minutes": CLAIM_TTL_MINUTES,
    "resolver_version": RESOLVER_VERSION,
})
TERMINAL = {"WIN", "LOSS", "BREAKEVEN", "AMBIGUOUS", "TIMEOUT", "EXPIRED_UNFILLED", "INVALID_DATA", "CANCELLED"}


class CandidateOutcomeResolver:
    """Resolve counterfactual candidates with transactional claims and 1m candles."""

    def __init__(self, provider: Any, store: OutcomeInfrastructureStore) -> None:
        self.provider = provider
        self.store = store

    @staticmethod
    def _to_ms(text: str) -> int:
        return int(datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000)

    @staticmethod
    def _ts(ms: int) -> str:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def _fetch(self, symbol: str, since: int, limit: int = 1000, *,
               cancel_event: threading.Event | None = None, deadline_monotonic=None):
        def cancellation_requested() -> bool:
            deadline = deadline_monotonic() if callable(deadline_monotonic) else deadline_monotonic
            return bool((cancel_event is not None and cancel_event.is_set()) or
                        (deadline is not None and time.monotonic() >= float(deadline)))

        last = None
        for delay in (0.0, 0.5, 1.0):
            if cancellation_requested():
                raise InterruptedError("candidate resolver cancelled before provider fetch")
            if delay:
                if cancel_event is not None:
                    if cancel_event.wait(delay):
                        raise InterruptedError("candidate resolver cancelled during provider backoff")
                else:
                    time.sleep(delay)
            if cancellation_requested():
                raise InterruptedError("candidate resolver cancelled before provider retry")
            try:
                return self.provider.exchange.fetch_ohlcv(symbol, timeframe="1m", since=since, limit=limit)
            except Exception as exc:  # pragma: no cover - provider-specific
                last = exc
        if last:
            raise last
        return []

    def recover_stale_claims(self) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=CLAIM_TTL_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
        now = utc_now_text()
        with self.store.connect() as con:
            cur = con.execute("""
                UPDATE candidate_outcomes
                   SET status='PENDING', resolution_claim_id=NULL, resolution_claimed_at=NULL,
                       outcome_detail=COALESCE(outcome_detail,'') || CASE WHEN outcome_detail IS NULL OR outcome_detail='' THEN '' ELSE ';' END || 'STALE_CLAIM_RECOVERED',
                       updated_at=?
                 WHERE status='RESOLVING' AND resolution_claimed_at<?
            """, (now, cutoff))
            return cur.rowcount

    def _claim_batch(self, limit: int) -> list[dict[str, Any]]:
        claim_id = uuid4().hex
        now = utc_now_text()
        with self.store.connect() as con:
            con.row_factory = __import__('sqlite3').Row
            con.execute("BEGIN IMMEDIATE")
            ids = [r[0] for r in con.execute("""
                SELECT o.outcome_id
                  FROM candidate_outcomes o
                  JOIN decision_candidates c ON c.candidate_id=o.candidate_id
                 WHERE o.status='PENDING' AND c.status IN ('WAITING_ENTRY','ACTIVE','TP1_HIT')
                 ORDER BY c.activated_at ASC LIMIT ?
            """, (int(limit),)).fetchall()]
            if not ids:
                con.commit(); return []
            marks = ",".join("?" for _ in ids)
            con.execute(f"UPDATE candidate_outcomes SET status='RESOLVING',resolution_claim_id=?,resolution_claimed_at=?,resolver_version=?,updated_at=? WHERE outcome_id IN ({marks}) AND status='PENDING'",
                        (claim_id, now, RESOLVER_VERSION, now, *ids))
            rows = con.execute(f"""
                SELECT o.*,c.*,c.status AS candidate_status FROM candidate_outcomes o JOIN decision_candidates c USING(candidate_id)
                 WHERE o.outcome_id IN ({marks}) AND o.resolution_claim_id=?
            """, (*ids, claim_id)).fetchall()
            con.commit()
            return [dict(r) for r in rows]

    def _record_event(self, con, row: dict[str, Any], *, event_type: str, event_time: str,
                      detail: str, price: float | None = None, realized_r: float | None = None,
                      mfe_r: float | None = None, mae_r: float | None = None) -> None:
        con.execute("""INSERT OR IGNORE INTO candidate_outcome_events(
            event_id,candidate_id,outcome_id,event_type,event_time,price,realized_r,mfe_r,mae_r,
            detail,resolver_version,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (
            uuid4().hex, row["candidate_id"], row["outcome_id"], str(event_type), event_time,
            price, realized_r, mfe_r, mae_r, detail, RESOLVER_VERSION, utc_now_text(),
        ))

    def _persist(self, row: dict[str, Any], *, candidate_status: str, outcome_status: str,
                 detail: str, outcome_time: str | None = None, outcome_price: float | None = None,
                 realized_r: float | None = None, mfe_r: float | None = None, mae_r: float | None = None,
                 fill_time: str | None = None, fill_price: float | None = None,
                 expiration_reason: str | None = None, event_type: str | None = None) -> None:
        now = utc_now_text()
        event_time = outcome_time or fill_time or now
        with self.store.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            current = con.execute(
                "SELECT status,resolution_claim_id FROM candidate_outcomes WHERE outcome_id=?",
                (row["outcome_id"],),
            ).fetchone()
            if not current or current[1] != row.get("resolution_claim_id"):
                con.rollback()
                return
            if str(current[0]).upper() in TERMINAL:
                con.rollback()
                return
            cur = con.execute("""UPDATE candidate_outcomes SET status=?,outcome_detail=?,outcome_time=?,outcome_price=?,
                realized_r=?,mfe_r=?,mae_r=?,resolver_version=?,resolution_claim_id=NULL,resolution_claimed_at=NULL,updated_at=?
                WHERE outcome_id=? AND resolution_claim_id=? AND status='RESOLVING'""",
                (outcome_status, detail, outcome_time, outcome_price, realized_r, mfe_r, mae_r,
                 RESOLVER_VERSION, now, row["outcome_id"], row["resolution_claim_id"]))
            if cur.rowcount != 1:
                con.rollback()
                return
            con.execute("""UPDATE decision_candidates SET status=?,expiration_reason=COALESCE(?,expiration_reason),
                fill_time=COALESCE(?,fill_time),fill_price=COALESCE(?,fill_price) WHERE candidate_id=?""",
                (candidate_status, expiration_reason, fill_time, fill_price, row["candidate_id"]))
            inferred_event = event_type or (
                "RESOLVED_" + outcome_status if outcome_status in TERMINAL else
                "ENTRY_FILLED" if candidate_status in {"ACTIVE", "TP1_HIT"} and fill_time else
                "TRACKING_UPDATED"
            )
            self._record_event(con, row, event_type=inferred_event, event_time=event_time,
                               detail=detail, price=outcome_price if outcome_price is not None else fill_price,
                               realized_r=realized_r, mfe_r=mfe_r, mae_r=mae_r)
            con.commit()

    def _resolve_one(self, row: dict[str, Any], *, cancel_event: threading.Event | None = None,
                     deadline_monotonic=None) -> bool:
        def cancellation_requested() -> bool:
            deadline = deadline_monotonic() if callable(deadline_monotonic) else deadline_monotonic
            return bool((cancel_event is not None and cancel_event.is_set()) or
                        (deadline is not None and time.monotonic() >= float(deadline)))

        if cancellation_requested():
            raise InterruptedError("candidate resolver cancelled before row processing")
        side = row["direction"].upper(); entry_low=float(row["entry_low"]); entry_high=float(row["entry_high"])
        stop=float(row["invalidation"]); tp1=float(row["tp1"]) if row["tp1"] is not None else None
        tp2=float(row["tp2"]) if row["tp2"] is not None else tp1
        planned=float(row["planned_entry"]); risk=max(abs(planned-stop),1e-12)
        expiry=row["entry_expiry_at"]
        start=row["fill_time"] or row["entry_wait_started_at"]
        candles=self._fetch(
            row["symbol"], self._to_ms(start), cancel_event=cancel_event,
            deadline_monotonic=deadline_monotonic,
        )
        if not candles:
            self._persist(row,candidate_status=row["candidate_status"],outcome_status="PENDING",detail="NO_NEW_1M_DATA")
            return False
        active=row["candidate_status"] in {"ACTIVE","TP1_HIT"}; tp1_hit=row["candidate_status"] == "TP1_HIT"
        fill_time=row["fill_time"]; fill_price=row["fill_price"]
        mfe=float(row.get("mfe_r") or 0.0); mae=float(row.get("mae_r") or 0.0)
        for ts, _o, high, low, close, _v in candles:
            if cancellation_requested():
                raise InterruptedError("candidate resolver cancelled during candle evaluation")
            t=self._ts(ts); high=float(high); low=float(low); close=float(close)
            if not active:
                invalid_before = low <= stop if side=="LONG" else high >= stop
                touched = high >= entry_low and low <= entry_high
                if invalid_before and touched:
                    self._persist(row,candidate_status="EXPIRED_UNFILLED",outcome_status="AMBIGUOUS",detail="AMBIGUOUS_ENTRY_AND_INVALIDATION",outcome_time=t,outcome_price=close,expiration_reason="INVALIDATED_BEFORE_ENTRY")
                    return True
                if invalid_before:
                    self._persist(row,candidate_status="EXPIRED_UNFILLED",outcome_status="EXPIRED_UNFILLED",detail="INVALIDATED_BEFORE_ENTRY",outcome_time=t,outcome_price=stop,expiration_reason="INVALIDATED_BEFORE_ENTRY")
                    return True
                if not touched:
                    if t >= expiry:
                        self._persist(row,candidate_status="EXPIRED_UNFILLED",outcome_status="EXPIRED_UNFILLED",detail="ENTRY_TIMEOUT",outcome_time=expiry,expiration_reason="ENTRY_TIMEOUT")
                        return True
                    continue
                active=True; fill_time=t; fill_price=planned
            favorable=(high-planned)/risk if side=="LONG" else (planned-low)/risk
            adverse=(planned-low)/risk if side=="LONG" else (high-planned)/risk
            mfe=max(mfe,favorable); mae=max(mae,adverse)
            stop_hit=low<=stop if side=="LONG" else high>=stop
            tp1_hit_now=(high>=tp1 if side=="LONG" else low<=tp1) if tp1 is not None else False
            target_hit=high>=tp2 if side=="LONG" else low<=tp2
            if stop_hit and target_hit:
                self._persist(row,candidate_status="AMBIGUOUS",outcome_status="AMBIGUOUS",detail="AMBIGUOUS_ACTIVE_CANDLE",outcome_time=t,outcome_price=close,realized_r=0.0,mfe_r=mfe,mae_r=mae,fill_time=fill_time,fill_price=fill_price)
                return True
            if stop_hit:
                self._persist(row,candidate_status="LOSS",outcome_status="LOSS",detail="STOP_BEFORE_TARGET",outcome_time=t,outcome_price=stop,realized_r=-1.0,mfe_r=mfe,mae_r=mae,fill_time=fill_time,fill_price=fill_price)
                return True
            if target_hit:
                rr=abs(tp2-planned)/risk
                self._persist(row,candidate_status="WIN",outcome_status="WIN",detail="TARGET_HIT",outcome_time=t,outcome_price=tp2,realized_r=rr,mfe_r=mfe,mae_r=mae,fill_time=fill_time,fill_price=fill_price,event_type="TP2_HIT")
                return True
            if tp1_hit_now and not tp1_hit:
                tp1_hit=True
                # Keep the candidate pending; persist the intermediate lifecycle state atomically.
                self._persist(row,candidate_status="TP1_HIT",outcome_status="PENDING",detail="TP1_HIT",outcome_time=None,outcome_price=None,fill_time=fill_time,fill_price=fill_price,mfe_r=mfe,mae_r=mae,event_type="TP1_HIT")
                return True
        self._persist(row,candidate_status="TP1_HIT" if tp1_hit else ("ACTIVE" if active else "WAITING_ENTRY"),outcome_status="PENDING",detail="TP1_HIT" if tp1_hit else ("ACTIVE" if active else "WAITING_ENTRY"),fill_time=fill_time,fill_price=fill_price,mfe_r=mfe,mae_r=mae,event_type="TRACKING_UPDATED")
        return active

    def resolve_pending(self, limit: int = 100, run_id: str | None = None,
                        cancel_event: threading.Event | None = None,
                        deadline_monotonic=None) -> dict[str, int]:
        def cancellation_requested() -> bool:
            deadline = deadline_monotonic() if callable(deadline_monotonic) else deadline_monotonic
            return bool((cancel_event is not None and cancel_event.is_set()) or
                        (deadline is not None and time.monotonic() >= float(deadline)))

        if cancellation_requested():
            raise InterruptedError("candidate resolver cancelled before claim")
        recovered = self.recover_stale_claims()
        if cancellation_requested():
            raise InterruptedError("candidate resolver cancelled after stale recovery")
        rows = self._claim_batch(limit)
        stats = {
            "checked": 0, "updated": 0, "tracking_only": 0,
            "entry_filled": 0, "tp1_hit": 0, "terminal_resolved": 0,
            "expired_unfilled": 0, "errors": 0, "stale_recovered": recovered,
        }
        for row in rows:
            if cancellation_requested():
                raise InterruptedError("candidate resolver cancelled during batch")
            stats["checked"] += 1
            try:
                changed = bool(self._resolve_one(
                    row, cancel_event=cancel_event, deadline_monotonic=deadline_monotonic
                ))
                stats["updated"] += int(changed)
                with self.store.connect() as con:
                    state = con.execute(
                        """SELECT c.status,o.status FROM decision_candidates c
                           JOIN candidate_outcomes o ON o.candidate_id=c.candidate_id
                           WHERE c.candidate_id=? AND o.outcome_id=?""",
                        (row["candidate_id"], row["outcome_id"]),
                    ).fetchone()
                if state:
                    candidate_status, outcome_status = map(str, state)
                    if outcome_status in TERMINAL:
                        stats["terminal_resolved"] += 1
                        if outcome_status == "EXPIRED_UNFILLED":
                            stats["expired_unfilled"] += 1
                    elif candidate_status == "TP1_HIT":
                        stats["tp1_hit"] += 1
                    elif candidate_status == "ACTIVE":
                        stats["entry_filled"] += 1
                    else:
                        stats["tracking_only"] += 1
            except InterruptedError:
                raise
            except Exception as exc:
                stats["errors"] += 1
                self.store.record_failure(
                    run_id=run_id, source_type="CANDIDATE_OUTCOME",
                    source_record_id=row.get("candidate_id"), symbol=row.get("symbol"),
                    exc=exc, traceback_text=traceback.format_exc(),
                )
                self._persist(
                    row, candidate_status=row["candidate_status"],
                    outcome_status="PENDING", detail=f"RESOLUTION_ERROR:{type(exc).__name__}",
                )
        return stats
