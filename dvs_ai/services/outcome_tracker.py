from __future__ import annotations
import threading
import time

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path


class OutcomeTracker:
    """
    Resolve signal-history outcomes with the same execution philosophy used
    by PaperTradeService.

    TP1 is an intermediate state, not a final win:
        ACTIVE -> TP1_HIT -> TP2 / PARTIAL_STOP / PARTIAL_AMBIGUOUS

    Fractions intentionally match PaperTradeService.
    """

    TP1_CLOSE_FRACTION = 0.50
    RUNNER_FRACTION = 0.50

    def __init__(
        self,
        provider,
        db_path: str = "data/dvs_signals.db",
    ) -> None:
        self.provider = provider
        self.db_path = Path(db_path)
        self._ensure_schema()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self) -> None:
        if not self.db_path.exists():
            return
        with self._connect() as con:
            columns = {
                row[1]
                for row in con.execute(
                    "PRAGMA table_info(scan_signals)"
                ).fetchall()
            }
            migrations = {
                "outcome_detail": "TEXT",
                "tp1_hit_time": "TEXT",
                "tp1_realized_r": "REAL DEFAULT 0",
            }
            for name, ddl in migrations.items():
                if name not in columns:
                    con.execute(
                        f"ALTER TABLE scan_signals "
                        f"ADD COLUMN {name} {ddl}"
                    )

    @staticmethod
    def _to_ms(text: str) -> int:
        dt = datetime.strptime(
            text,
            "%Y-%m-%d %H:%M:%S",
        )
        return int(
            dt.replace(tzinfo=timezone.utc).timestamp() * 1000
        )

    @staticmethod
    def _timestamp_text(timestamp_ms: int) -> str:
        return datetime.fromtimestamp(
            timestamp_ms / 1000,
            tz=timezone.utc,
        ).strftime("%Y-%m-%d %H:%M:%S")

    def _fetch_chunk(self, symbol, since, limit, *, cancel_event=None, deadline_monotonic=None):
        def cancelled() -> bool:
            deadline = deadline_monotonic() if callable(deadline_monotonic) else deadline_monotonic
            return bool((cancel_event is not None and cancel_event.is_set()) or
                        (deadline is not None and time.monotonic() >= float(deadline)))

        last_error = None
        for delay in (0.0, 0.5, 1.0, 2.0):
            if cancelled():
                raise InterruptedError("outcome tracker cancelled before provider fetch")
            if delay:
                if cancel_event is not None:
                    if cancel_event.wait(delay):
                        raise InterruptedError("outcome tracker cancelled during provider backoff")
                else:
                    time.sleep(delay)
            if cancelled():
                raise InterruptedError("outcome tracker cancelled before provider retry")
            try:
                return self.provider.exchange.fetch_ohlcv(
                    symbol,
                    timeframe="1m",
                    since=since,
                    limit=limit,
                )
            except Exception as exc:
                last_error = exc
                name = type(exc).__name__.lower()
                if (
                    "ratelimit" not in name
                    and "timeout" not in name
                ):
                    break
        if last_error:
            raise last_error
        return []

    def _persist_outcome(
        self,
        *,
        signal_id: int,
        outcome: str,
        outcome_time: str,
        outcome_price: float | None,
        r_multiple: float | None,
        outcome_detail: str | None,
        tp1_hit_time: str | None,
        tp1_realized_r: float,
    ) -> None:
        with self._connect() as con:
            con.execute("""
                UPDATE scan_signals
                SET outcome=?,
                    outcome_time=?,
                    outcome_price=?,
                    r_multiple=?,
                    outcome_detail=?,
                    tp1_hit_time=?,
                    tp1_realized_r=?
                WHERE id=?
            """, (
                outcome,
                outcome_time,
                outcome_price,
                r_multiple,
                outcome_detail,
                tp1_hit_time,
                tp1_realized_r,
                signal_id,
            ))

    def evaluate_pending(
        self,
        limit: int = 100,
        chunk_size: int = 1000,
        max_chunks: int = 8,
        expiry_days: int = 7,
        cancel_event: threading.Event | None = None,
        deadline_monotonic=None,
    ) -> dict[str, int]:
        if not self.db_path.exists():
            return {
                "checked": 0,
                "updated": 0,
                "errors": 0,
                "expired": 0,
                "tp1_intermediate": 0,
            }

        self._ensure_schema()

        with self._connect() as con:
            rows = con.execute("""
                SELECT id, generated_at, symbol, direction,
                       invalidation, tp1, tp2, price
                FROM scan_signals
                WHERE outcome='PENDING'
                ORDER BY id ASC
                LIMIT ?
            """, (int(limit),)).fetchall()

        checked = updated = errors = expired = 0
        tp1_intermediate = 0

        def cancellation_requested() -> bool:
            deadline = deadline_monotonic() if callable(deadline_monotonic) else deadline_monotonic
            return bool((cancel_event is not None and cancel_event.is_set()) or
                        (deadline is not None and time.monotonic() >= float(deadline)))

        for row in rows:
            if cancellation_requested():
                raise InterruptedError("outcome tracker cancelled during shutdown")
            checked += 1
            (
                signal_id,
                generated_at,
                symbol,
                direction,
                invalidation,
                tp1,
                tp2,
                entry_price,
            ) = row

            try:
                side = str(direction).upper()
                if side not in ("LONG", "SHORT"):
                    raise ValueError(
                        f"Unsupported direction: {direction}"
                    )

                entry = float(entry_price)
                stop = float(invalidation)
                target1 = float(tp1)
                target2 = float(tp2)
                risk = max(abs(entry-stop), 1e-12)
                tp1_r_full = abs(target1-entry) / risk
                tp2_r_full = abs(target2-entry) / risk

                created = datetime.strptime(
                    generated_at,
                    "%Y-%m-%d %H:%M:%S",
                ).replace(tzinfo=timezone.utc)
                age_days = (
                    datetime.now(timezone.utc)-created
                ).days

                since = self._to_ms(generated_at)
                current_status = "ACTIVE"
                tp1_hit_time = None
                tp1_realized_r = 0.0

                final_outcome = None
                final_time = None
                final_price = None
                final_r = None
                outcome_detail = None
                last_candle_time = None
                last_close = entry

                for _ in range(max_chunks):
                    if cancellation_requested():
                        raise InterruptedError("outcome tracker cancelled during candle fetch")
                    candles = self._fetch_chunk(
                        symbol,
                        since,
                        chunk_size,
                        cancel_event=cancel_event,
                        deadline_monotonic=deadline_monotonic,
                    )
                    if not candles:
                        break

                    for ts, _, high, low, close, _ in candles:
                        if cancellation_requested():
                            raise InterruptedError("outcome tracker cancelled during candle evaluation")
                        high = float(high)
                        low = float(low)
                        close = float(close)
                        last_close = close
                        last_candle_time = self._timestamp_text(ts)

                        if side == "LONG":
                            stop_hit = low <= stop
                            tp1_hit_now = high >= target1
                            tp2_hit_now = high >= target2
                        else:
                            stop_hit = high >= stop
                            tp1_hit_now = low <= target1
                            tp2_hit_now = low <= target2

                        if current_status == "ACTIVE":
                            # OHLC cannot reveal which extreme occurred first.
                            if stop_hit and (
                                tp1_hit_now or tp2_hit_now
                            ):
                                final_outcome = "AMBIGUOUS"
                                final_time = last_candle_time
                                final_price = close
                                final_r = 0.0
                                outcome_detail = (
                                    "AMBIGUOUS_ACTIVE_CANDLE"
                                )
                                break

                            if stop_hit:
                                final_outcome = "INVALID"
                                final_time = last_candle_time
                                final_price = stop
                                final_r = -1.0
                                outcome_detail = (
                                    "STOP_BEFORE_TP1"
                                )
                                break

                            # TP2 implies that TP1 was crossed first or
                            # simultaneously within the same favourable move.
                            if tp2_hit_now:
                                tp1_hit_time = last_candle_time
                                tp1_realized_r = (
                                    self.TP1_CLOSE_FRACTION
                                    * tp1_r_full
                                )
                                final_outcome = "TP2"
                                final_time = last_candle_time
                                final_price = target2
                                final_r = (
                                    tp1_realized_r
                                    + self.RUNNER_FRACTION
                                    * tp2_r_full
                                )
                                outcome_detail = (
                                    "TP2_WITH_PARTIAL_TP1"
                                )
                                break

                            if tp1_hit_now:
                                current_status = "TP1_HIT"
                                tp1_hit_time = last_candle_time
                                tp1_realized_r = (
                                    self.TP1_CLOSE_FRACTION
                                    * tp1_r_full
                                )
                                tp1_intermediate += 1
                                # Critical consistency rule:
                                # TP1 is not a final outcome.
                                continue

                        if current_status == "TP1_HIT":
                            if stop_hit and tp2_hit_now:
                                final_outcome = (
                                    "PARTIAL_AMBIGUOUS"
                                )
                                final_time = last_candle_time
                                final_price = close
                                final_r = tp1_realized_r
                                outcome_detail = (
                                    "AMBIGUOUS_AFTER_TP1"
                                )
                                break

                            if stop_hit:
                                final_outcome = "PARTIAL_STOP"
                                final_time = last_candle_time
                                final_price = stop
                                final_r = (
                                    tp1_realized_r
                                    - self.RUNNER_FRACTION
                                )
                                outcome_detail = (
                                    "TP1_THEN_STOP"
                                )
                                break

                            if tp2_hit_now:
                                final_outcome = "TP2"
                                final_time = last_candle_time
                                final_price = target2
                                final_r = (
                                    tp1_realized_r
                                    + self.RUNNER_FRACTION
                                    * tp2_r_full
                                )
                                outcome_detail = (
                                    "TP1_THEN_TP2"
                                )
                                break

                    if final_outcome:
                        break

                    if len(candles) < chunk_size:
                        break

                    next_since = int(candles[-1][0]) + 1
                    if next_since <= since:
                        break
                    since = next_since

                if final_outcome:
                    self._persist_outcome(
                        signal_id=signal_id,
                        outcome=final_outcome,
                        outcome_time=final_time,
                        outcome_price=final_price,
                        r_multiple=final_r,
                        outcome_detail=outcome_detail,
                        tp1_hit_time=tp1_hit_time,
                        tp1_realized_r=tp1_realized_r,
                    )
                    updated += 1
                    continue

                # Expire only after replaying all available candles, so an
                # old signal is not expired before its actual TP/Stop is seen.
                if age_days >= expiry_days:
                    expiry_detail = (
                        "EXPIRED_AFTER_TP1"
                        if current_status == "TP1_HIT"
                        else "EXPIRED_NO_FINAL_OUTCOME"
                    )
                    expiry_time = (
                        last_candle_time
                        or datetime.now(timezone.utc).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                    )
                    self._persist_outcome(
                        signal_id=signal_id,
                        outcome="EXPIRED",
                        outcome_time=expiry_time,
                        outcome_price=last_close,
                        r_multiple=None,
                        outcome_detail=expiry_detail,
                        tp1_hit_time=tp1_hit_time,
                        tp1_realized_r=tp1_realized_r,
                    )
                    expired += 1
                    updated += 1

            except InterruptedError:
                raise
            except Exception:
                errors += 1

        return {
            "checked": checked,
            "updated": updated,
            "errors": errors,
            "expired": expired,
            "tp1_intermediate": tp1_intermediate,
        }
