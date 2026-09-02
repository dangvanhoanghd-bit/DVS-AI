from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from dvs_ai.services.truth_trend_store import TruthTrendStore


@dataclass(frozen=True)
class EvidenceReliability:
    family: str
    state: str
    reliability: float
    effective_samples: float
    raw_samples: int
    context: str
    method: str = "TIME_DECAY_BAYES_HIERARCHICAL"
    reason: str = ""


class EvidenceReliabilityService:
    """Observe-only reliability estimates from CLOSED PAPER outcomes.

    Only trades with an explicit evidence_snapshot_json recorded at signal time
    are eligible. Legacy rows are never reverse-engineered from reasoning text.
    The service does not change decision scores, thresholds, sizing, or execution.
    """

    FAMILIES = ("TIMING", "ENTRY", "ORDER_FLOW", "DIRECTION", "MARKET")

    def __init__(
        self,
        db_path: str = "data/dvs_paper_trades.db",
        *,
        half_life_days: float = 45.0,
        min_effective_samples: float = 20.0,
        prior_strength: float = 12.0,
    ) -> None:
        self.db_path = Path(db_path)
        self.half_life_days = max(7.0, float(half_life_days))
        self.min_effective_samples = max(5.0, float(min_effective_samples))
        self.prior_strength = max(2.0, float(prior_strength))
        self._trend_store = TruthTrendStore(str(self.db_path))
        self._cache_lock = threading.RLock()
        self._rows_cache: tuple[dict[str, object], ...] = ()
        self._rows_cache_signature: tuple[int, int] | None = None
        self._rows_cache_loaded_monotonic = 0.0
        self._rows_cache_ttl_s = 30.0
        self._index_cache: dict[
            tuple[str, str],
            tuple[dict[str, object], ...],
        ] = {}
        self._context_index_cache: dict[
            tuple[str, str, str],
            tuple[dict[str, object], ...],
        ] = {}
        self._last_trend_payload: dict[str, float] | None = None
        self._last_trend_append_monotonic = 0.0

    @staticmethod
    def _finite(value: object, default: float = 0.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        return number if math.isfinite(number) else default

    @staticmethod
    def _parse_time(value: object) -> datetime | None:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _decay(self, closed_at: object, now: datetime) -> float:
        parsed = self._parse_time(closed_at)
        if parsed is None:
            return 0.0
        age_days = max(0.0, (now - parsed).total_seconds() / 86400.0)
        return 0.5 ** (age_days / self.half_life_days)

    def _load_rows_uncached(self) -> list[dict[str, object]]:
        if not self.db_path.exists():
            return []
        with sqlite3.connect(self.db_path) as con:
            columns = {row[1] for row in con.execute("PRAGMA table_info(paper_trades)")}
            if "evidence_snapshot_json" not in columns:
                return []
            rows = con.execute("""
                SELECT symbol, direction, regime, r_multiple,
                       COALESCE(closed_at, created_at), evidence_snapshot_json
                FROM paper_trades
                WHERE status='CLOSED'
                  AND result NOT IN ('AMBIGUOUS','PARTIAL_AMBIGUOUS','EXPIRED')
                  AND evidence_snapshot_json IS NOT NULL
                  AND evidence_snapshot_json != ''
                ORDER BY COALESCE(closed_at, created_at), id
            """).fetchall()
        output: list[dict[str, object]] = []
        for symbol, direction, regime, r_multiple, closed_at, payload in rows:
            try:
                snapshot = json.loads(payload)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(snapshot, dict):
                continue
            output.append({
                "symbol": str(symbol).upper(),
                "direction": str(direction).upper(),
                "regime": str(regime).upper(),
                "win": self._finite(r_multiple) > 0.0,
                "closed_at": closed_at,
                "snapshot": snapshot,
            })
        return output

    def _database_signature(self) -> tuple[int, int] | None:
        try:
            stat = self.db_path.stat()
        except OSError:
            return None
        return int(stat.st_mtime_ns), int(stat.st_size)

    def _load_rows(self) -> tuple[dict[str, object], ...]:
        signature = self._database_signature()
        now_mono = time.monotonic()
        with self._cache_lock:
            cache_fresh = (
                signature == self._rows_cache_signature
                and (
                    now_mono - self._rows_cache_loaded_monotonic
                    < self._rows_cache_ttl_s
                )
            )
            if cache_fresh:
                return self._rows_cache

        loaded = tuple(self._load_rows_uncached())
        regime_index: dict[
            tuple[str, str],
            list[dict[str, object]],
        ] = {}
        context_index: dict[
            tuple[str, str, str],
            list[dict[str, object]],
        ] = {}
        for row in loaded:
            regime_key = (
                str(row["regime"]),
                str(row["direction"]),
            )
            context_key = (
                str(row["symbol"]),
                str(row["direction"]),
                str(row["regime"]),
            )
            regime_index.setdefault(regime_key, []).append(row)
            context_index.setdefault(context_key, []).append(row)

        with self._cache_lock:
            self._rows_cache = loaded
            self._rows_cache_signature = signature
            self._rows_cache_loaded_monotonic = now_mono
            self._index_cache = {
                key: tuple(value)
                for key, value in regime_index.items()
            }
            self._context_index_cache = {
                key: tuple(value)
                for key, value in context_index.items()
            }
            return self._rows_cache

    @staticmethod
    def _family_sample(row: dict[str, object], family: str) -> tuple[float, bool] | None:
        snapshot = row.get("snapshot")
        if not isinstance(snapshot, dict):
            return None
        item = snapshot.get(family)
        if not isinstance(item, dict):
            return None
        try:
            score = float(item.get("score"))
            quality = float(item.get("quality", 1.0))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(score) or not math.isfinite(quality):
            return None
        if not bool(item.get("available", True)):
            return None
        quality = max(0.0, min(1.0, quality))
        # Neutral evidence is not credited or blamed for the trade outcome.
        directional_strength = min(1.0, abs(score - 50.0) / 25.0)
        if directional_strength < 0.20 or quality <= 0.0:
            return None
        supports_trade = score >= 50.0
        correct = bool(row["win"]) if supports_trade else not bool(row["win"])
        return quality * directional_strength, correct

    def _aggregate(
        self,
        rows: Iterable[dict[str, object]],
        family: str,
        now: datetime,
    ) -> tuple[float, float, int]:
        weighted_correct = 0.0
        total_weight = 0.0
        raw_samples = 0
        for row in rows:
            sample = self._family_sample(row, family)
            if sample is None:
                continue
            strength, correct = sample
            weight = strength * self._decay(row.get("closed_at"), now)
            if weight <= 0.0:
                continue
            total_weight += weight
            weighted_correct += weight * float(correct)
            raw_samples += 1
        rate = weighted_correct / total_weight if total_weight > 0.0 else 0.5
        return rate, total_weight, raw_samples

    def evaluate(
        self,
        *,
        symbol: str,
        direction: str,
        regime: str,
        now: datetime | None = None,
    ) -> dict[str, EvidenceReliability]:
        rows = self._load_rows()
        now = now or datetime.now(timezone.utc)
        symbol = str(symbol).upper()
        direction = str(direction).upper()
        regime = str(regime).upper()
        results: dict[str, EvidenceReliability] = {}

        for family in self.FAMILIES:
            global_rate, global_eff, _ = self._aggregate(
                rows,
                family,
                now,
            )
            with self._cache_lock:
                regime_rows = self._index_cache.get(
                    (regime, direction),
                    (),
                )
                context_rows = self._context_index_cache.get(
                    (symbol, direction, regime),
                    (),
                )
            regime_rate, regime_eff, _ = self._aggregate(
                regime_rows,
                family,
                now,
            )
            context_rate, context_eff, context_raw = self._aggregate(
                context_rows,
                family,
                now,
            )

            if global_eff < self.min_effective_samples:
                results[family] = EvidenceReliability(
                    family, "UNKNOWN", 0.0, global_eff, context_raw,
                    f"{symbol}|{direction}|{regime}",
                    reason="insufficient global effective PAPER samples",
                )
                continue

            # Hierarchical shrinkage: context -> regime -> global.
            regime_posterior = (
                regime_eff * regime_rate + self.prior_strength * global_rate
            ) / (regime_eff + self.prior_strength)
            context_posterior = (
                context_eff * context_rate + self.prior_strength * regime_posterior
            ) / (context_eff + self.prior_strength)
            state = "VALIDATED" if context_eff >= self.min_effective_samples else "SHRUNK"
            results[family] = EvidenceReliability(
                family=family,
                state=state,
                reliability=max(0.0, min(100.0, context_posterior * 100.0)),
                effective_samples=context_eff,
                raw_samples=context_raw,
                context=f"{symbol}|{direction}|{regime}",
                reason=(
                    "context evidence sufficient"
                    if state == "VALIDATED"
                    else "context estimate shrunk toward regime/global prior"
                ),
            )
        trend_payload = {
            family.lower(): item.reliability
            for family, item in results.items()
        }
        now_mono = time.monotonic()
        with self._cache_lock:
            should_append = (
                self._last_trend_payload != trend_payload
                or now_mono - self._last_trend_append_monotonic >= 60.0
            )
            if should_append:
                self._last_trend_payload = dict(trend_payload)
                self._last_trend_append_monotonic = now_mono
        if should_append:
            self._trend_store.append(
                "RELIABILITY",
                "EVALUATED",
                trend_payload,
            )
        return results
