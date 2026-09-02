from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .base import LifecycleStage, MicrostructureEvidence
from .base_engine import EvidenceEngine


class OrderBlockDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class OrderBlockState(str, Enum):
    NONE = "NONE"
    CANDIDATE = "CANDIDATE"
    CONFIRMED = "CONFIRMED"
    FRESH = "FRESH"
    MITIGATED = "MITIGATED"
    # Reserved for a future standalone "broken but not yet invalidated"
    # lifecycle. In the current model, a close through the zone is treated
    # as INVALIDATED immediately, so BROKEN is intentionally unreachable.
    BROKEN = "BROKEN"
    BREAKER = "BREAKER"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True)
class OrderBlockDetails:
    direction: OrderBlockDirection
    state: OrderBlockState
    age_bars: int
    zone_low: float
    zone_high: float
    midpoint: float
    detection_confidence: float
    freshness_score: float
    mitigation_score: float
    reaction_quality: float
    overall_quality: float
    lifecycle_stage: LifecycleStage | None
    invalidated: bool
    breaker: bool
    bos_confirmed: bool
    impulse_score: float
    volume_score: float
    retest_count: int
    nested: bool
    institutional: bool
    explanation: tuple[str, ...]
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        for name in (
            "detection_confidence",
            "freshness_score",
            "mitigation_score",
            "reaction_quality",
            "overall_quality",
            "impulse_score",
            "volume_score",
        ):
            object.__setattr__(
                self,
                name,
                max(0.0, min(100.0, float(getattr(self, name)))),
            )
        object.__setattr__(self, "age_bars", max(0, int(self.age_bars)))
        object.__setattr__(self, "retest_count", max(0, int(self.retest_count)))
        object.__setattr__(self, "explanation", tuple(self.explanation or ()))
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata or {})),
        )


class OrderBlockEngine(EvidenceEngine):
    """
    Evidence-only Order Block Engine V2.

    Detection logic:
    1. Find the last opposite-colour candle before an impulsive displacement.
    2. Require or infer BOS/CHOCH from subsequent structure break.
    3. Track Fresh -> Mitigated -> Broken -> Breaker/Invalidated lifecycle.
    4. Score detection, freshness, mitigation, reaction and lifecycle context.

    This engine never creates a trade decision.
    """

    REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")

    @staticmethod
    def _f(value: Any, default: float = 0.0) -> float:
        try:
            result = float(value)
            return result if isfinite(result) else default
        except (TypeError, ValueError):
            return default

    @classmethod
    def _normalise(cls, frame: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("ohlcv must be a pandas DataFrame")
        aliases = {"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}
        data = frame.rename(columns=aliases).copy()
        missing = [column for column in cls.REQUIRED_COLUMNS if column not in data.columns]
        if missing:
            raise ValueError("Missing OHLCV columns: " + ", ".join(missing))
        for column in cls.REQUIRED_COLUMNS:
            data[column] = pd.to_numeric(data[column], errors="coerce")
        return data.dropna(subset=list(cls.REQUIRED_COLUMNS)).reset_index(drop=True)

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(100.0, float(value)))

    @staticmethod
    def _lifecycle_bonus(
        direction: OrderBlockDirection,
        lifecycle: LifecycleStage | None,
    ) -> float:
        if lifecycle is None:
            return 0.0
        bullish_good = {
            LifecycleStage.SPRING,
            LifecycleStage.TEST,
            LifecycleStage.ACCUMULATION,
            LifecycleStage.REACCUMULATION,
        }
        bearish_good = {
            LifecycleStage.UPTHRUST,
            LifecycleStage.TEST,
            LifecycleStage.DISTRIBUTION,
            LifecycleStage.REDISTRIBUTION,
        }
        late = {
            LifecycleStage.EXHAUSTION,
            LifecycleStage.MARKUP,
            LifecycleStage.MARKDOWN,
        }
        if direction == OrderBlockDirection.BULLISH and lifecycle in bullish_good:
            return 10.0
        if direction == OrderBlockDirection.BEARISH and lifecycle in bearish_good:
            return 10.0
        if lifecycle in late:
            return -8.0
        return 0.0

    @staticmethod
    def _extract_lifecycle(
        context: Mapping[str, Any],
    ) -> LifecycleStage | None:
        raw = context.get("lifecycle_stage") or context.get("stage")
        if isinstance(raw, LifecycleStage):
            return raw
        if raw is None:
            return None
        text = str(raw).strip().lower()
        for stage in LifecycleStage:
            if text in (stage.name.lower(), stage.value.lower()):
                return stage
        return None

    @staticmethod
    def _candidate_score(
        body: float,
        candle_range: float,
        impulse_atr: float,
        volume_ratio: float,
        bos_confirmed: bool,
    ) -> tuple[float, float, float]:
        small_body_quality = max(
            0.0,
            1.0 - body / max(candle_range, 1e-12),
        ) * 100.0
        impulse_score = min(100.0, max(0.0, impulse_atr) * 28.0)
        volume_score = min(100.0, max(0.0, volume_ratio-0.6) * 55.0)
        detection = (
            0.28 * small_body_quality
            + 0.34 * impulse_score
            + 0.18 * volume_score
            + (20.0 if bos_confirmed else 0.0)
        )
        return detection, impulse_score, volume_score

    def _scan_candidate(
        self,
        data: pd.DataFrame,
        direction: OrderBlockDirection,
    ) -> dict[str, Any] | None:
        if len(data) < 60:
            return None

        ranges = (data["high"]-data["low"]).clip(lower=1e-12)
        atr = ranges.rolling(14).mean().bfill()
        avg_volume = data["volume"].rolling(20).mean().bfill().clip(lower=1e-12)

        start = max(5, len(data)-55)
        end = len(data)-3
        best: dict[str, Any] | None = None

        for index in range(start, end):
            row = data.iloc[index]
            body = abs(float(row["close"])-float(row["open"]))
            candle_range = float(ranges.iloc[index])
            volume_ratio = float(row["volume"]/avg_volume.iloc[index])

            if direction == OrderBlockDirection.BULLISH:
                opposite = row["close"] <= row["open"]
                future = data.iloc[index+1:min(index+6, len(data))]
                displacement = float(future["high"].max()-row["high"])
                impulse_atr = displacement/max(float(atr.iloc[index]), 1e-12)
                prior_high = float(data["high"].iloc[max(0, index-12):index].max())
                bos_confirmed = bool(future["close"].max() > prior_high)
                zone_low = float(row["low"])
                zone_high = float(max(row["open"], row["close"]))
            else:
                opposite = row["close"] >= row["open"]
                future = data.iloc[index+1:min(index+6, len(data))]
                displacement = float(row["low"]-future["low"].min())
                impulse_atr = displacement/max(float(atr.iloc[index]), 1e-12)
                prior_low = float(data["low"].iloc[max(0, index-12):index].min())
                bos_confirmed = bool(future["close"].min() < prior_low)
                zone_low = float(min(row["open"], row["close"]))
                zone_high = float(row["high"])

            if not opposite or impulse_atr < 0.8:
                continue

            detection, impulse_score, volume_score = self._candidate_score(
                body=body,
                candle_range=candle_range,
                impulse_atr=impulse_atr,
                volume_ratio=volume_ratio,
                bos_confirmed=bos_confirmed,
            )
            if detection < 45.0:
                continue

            candidate = {
                "index": index,
                "zone_low": zone_low,
                "zone_high": zone_high,
                "detection": detection,
                "impulse_score": impulse_score,
                "volume_score": volume_score,
                "bos_confirmed": bos_confirmed,
                "impulse_atr": impulse_atr,
                "volume_ratio": volume_ratio,
            }
            if best is None or candidate["detection"] > best["detection"]:
                best = candidate

        return best

    def _evaluate_state(
        self,
        data: pd.DataFrame,
        candidate: dict[str, Any],
        direction: OrderBlockDirection,
    ) -> dict[str, Any]:
        index = int(candidate["index"])
        zone_low = float(candidate["zone_low"])
        zone_high = float(candidate["zone_high"])
        midpoint = (zone_low+zone_high)/2.0
        later = data.iloc[index+1:]
        age = len(data)-1-index
        zone_height = max(zone_high-zone_low, 1e-12)

        touched = False
        body_touch = False
        retest_count = 0
        max_penetration = 0.0
        invalidated = False
        broken = False
        reaction_quality = 0.0
        mitigation_score = 0.0
        breaker = False

        if not later.empty:
            if direction == OrderBlockDirection.BULLISH:
                touched_mask = later["low"] <= zone_high
                touched = bool(touched_mask.any())
                retest_count = int(touched_mask.sum())
                if touched:
                    first_pos = int(np.flatnonzero(touched_mask.to_numpy())[0])
                    touch_row = later.iloc[first_pos]
                    penetration = max(0.0, zone_high-float(touch_row["low"]))
                    max_penetration = min(1.5, penetration/zone_height)
                    body_touch = float(touch_row["close"]) <= zone_high
                    follow = later.iloc[first_pos:min(first_pos+4, len(later))]
                    reaction = float(follow["high"].max()-zone_high)
                    reaction_quality = self._clamp(reaction/zone_height*35.0)
                    mitigation_score = self._clamp(
                        45.0
                        + min(25.0, max_penetration*30.0)
                        + min(20.0, reaction_quality*0.25)
                        + (10.0 if not body_touch else 0.0)
                    )
                invalidated = bool((later["close"] < zone_low).any())
                # Current invariant: a confirmed close through the zone
                # invalidates the OB immediately. Therefore `broken` mirrors
                # `invalidated`, and OrderBlockState.BROKEN remains reserved.
                broken = invalidated
                if invalidated:
                    after_break = later[later["close"] < zone_low]
                    first_break_index = after_break.index[0]
                    post_break = data.loc[first_break_index:]
                    breaker = bool((post_break["high"] >= zone_low).any())
            else:
                touched_mask = later["high"] >= zone_low
                touched = bool(touched_mask.any())
                retest_count = int(touched_mask.sum())
                if touched:
                    first_pos = int(np.flatnonzero(touched_mask.to_numpy())[0])
                    touch_row = later.iloc[first_pos]
                    penetration = max(0.0, float(touch_row["high"])-zone_low)
                    max_penetration = min(1.5, penetration/zone_height)
                    body_touch = float(touch_row["close"]) >= zone_low
                    follow = later.iloc[first_pos:min(first_pos+4, len(later))]
                    reaction = float(zone_low-follow["low"].min())
                    reaction_quality = self._clamp(reaction/zone_height*35.0)
                    mitigation_score = self._clamp(
                        45.0
                        + min(25.0, max_penetration*30.0)
                        + min(20.0, reaction_quality*0.25)
                        + (10.0 if not body_touch else 0.0)
                    )
                invalidated = bool((later["close"] > zone_high).any())
                # See bullish branch above: BROKEN is a reserved future state.
                broken = invalidated
                if invalidated:
                    after_break = later[later["close"] > zone_high]
                    first_break_index = after_break.index[0]
                    post_break = data.loc[first_break_index:]
                    breaker = bool((post_break["low"] <= zone_high).any())

        freshness = self._clamp(
            100.0
            - min(70.0, age*1.5)
            - (25.0 if touched else 0.0)
            - (35.0 if invalidated else 0.0)
        )

        if invalidated and breaker:
            state = OrderBlockState.BREAKER
        elif invalidated:
            state = OrderBlockState.INVALIDATED
        elif broken:
            state = OrderBlockState.BROKEN
        elif touched:
            state = OrderBlockState.MITIGATED
        elif candidate["bos_confirmed"]:
            state = OrderBlockState.FRESH
        else:
            state = OrderBlockState.CANDIDATE

        return {
            "state": state,
            "age": age,
            "midpoint": midpoint,
            "touched": touched,
            "body_touch": body_touch,
            "max_penetration": max_penetration,
            "invalidated": invalidated,
            "broken": broken,
            "breaker": breaker,
            "freshness": freshness,
            "mitigation_score": mitigation_score,
            "reaction_quality": reaction_quality,
            "retest_count": retest_count,
        }

    def _build_details(
        self,
        data: pd.DataFrame,
        candidate: dict[str, Any],
        direction: OrderBlockDirection,
        lifecycle: LifecycleStage | None,
    ) -> OrderBlockDetails:
        state = self._evaluate_state(data, candidate, direction)
        lifecycle_bonus = self._lifecycle_bonus(direction, lifecycle)

        nested = bool(candidate["zone_high"]-candidate["zone_low"] <= max(float((data["high"]-data["low"]).rolling(14).mean().iloc[-1]), 1e-12)*0.75)
        institutional = bool(candidate["bos_confirmed"] and candidate["impulse_score"] >= 65 and candidate["volume_score"] >= 45)

        overall = (
            0.32 * candidate["detection"]
            + 0.20 * state["freshness"]
            + 0.18 * state["mitigation_score"]
            + 0.18 * state["reaction_quality"]
            + 0.12 * candidate["impulse_score"]
            + lifecycle_bonus
        )
        if state["invalidated"]:
            overall -= 35.0
        if state["breaker"]:
            overall += 8.0
        if institutional:
            overall += 7.0
        if nested:
            overall += 3.0
        if state["retest_count"] >= 3:
            overall -= min(12.0, (state["retest_count"]-2)*4.0)

        explanation = [
            f"{direction.value} Order Block {state['state'].value}.",
            (
                f"Zone {candidate['zone_low']:.6g} - "
                f"{candidate['zone_high']:.6g}; age {state['age']} bars."
            ),
            (
                f"Detection {candidate['detection']:.1f}, "
                f"Freshness {state['freshness']:.1f}, "
                f"Mitigation {state['mitigation_score']:.1f}, "
                f"Reaction {state['reaction_quality']:.1f}."
            ),
        ]
        if candidate["bos_confirmed"]:
            explanation.append("BOS/CHOCH displacement confirmed after origin candle.")
        else:
            explanation.append("Candidate only: structural break is not confirmed.")
        if lifecycle is not None:
            explanation.append(f"Lifecycle context: {lifecycle.value}.")
        if state["breaker"]:
            explanation.append("Broken block retested from the opposite side: Breaker candidate.")
        elif state["invalidated"]:
            explanation.append("Order Block invalidated by a body close through the zone.")
        elif state["touched"]:
            explanation.append("Order Block has been mitigated and reaction was measured.")
        else:
            explanation.append("Order Block remains fresh and unmitigated.")
        explanation.append(f"Retests {state['retest_count']} · Nested={nested} · Institutional={institutional}.")

        return OrderBlockDetails(
            direction=direction,
            state=state["state"],
            age_bars=state["age"],
            zone_low=candidate["zone_low"],
            zone_high=candidate["zone_high"],
            midpoint=state["midpoint"],
            detection_confidence=candidate["detection"],
            freshness_score=state["freshness"],
            mitigation_score=state["mitigation_score"],
            reaction_quality=state["reaction_quality"],
            overall_quality=self._clamp(overall),
            lifecycle_stage=lifecycle,
            invalidated=state["invalidated"],
            breaker=state["breaker"],
            bos_confirmed=candidate["bos_confirmed"],
            impulse_score=candidate["impulse_score"],
            volume_score=candidate["volume_score"],
            retest_count=state["retest_count"],
            nested=nested,
            institutional=institutional,
            explanation=tuple(explanation),
            metadata={
                "index": candidate["index"],
                "impulse_atr": candidate["impulse_atr"],
                "volume_ratio": candidate["volume_ratio"],
                "touched": state["touched"],
                "body_touch": state["body_touch"],
                "max_penetration": state["max_penetration"],
                "retest_count": state["retest_count"],
                "nested": nested,
                "institutional": institutional,
            },
        )

    def analyze(
        self,
        ohlcv: pd.DataFrame,
        context: dict,
    ) -> MicrostructureEvidence:
        data = self._normalise(ohlcv)
        lifecycle = self._extract_lifecycle(context)

        if len(data) < 60:
            return MicrostructureEvidence(
                score=25.0,
                phase_quality=20.0,
                explanation=("Dữ liệu dưới 60 nến; chưa đủ phát hiện Order Block.",),
                evidence=("INSUFFICIENT_ORDER_BLOCK_HISTORY",),
                metadata={"implemented": True, "bars": len(data)},
            )

        bullish = self._scan_candidate(data, OrderBlockDirection.BULLISH)
        bearish = self._scan_candidate(data, OrderBlockDirection.BEARISH)

        details: list[OrderBlockDetails] = []
        if bullish is not None:
            details.append(
                self._build_details(
                    data,
                    bullish,
                    OrderBlockDirection.BULLISH,
                    lifecycle,
                )
            )
        if bearish is not None:
            details.append(
                self._build_details(
                    data,
                    bearish,
                    OrderBlockDirection.BEARISH,
                    lifecycle,
                )
            )

        if not details:
            return MicrostructureEvidence(
                score=30.0,
                phase_quality=25.0,
                explanation=("Chưa phát hiện Order Block có displacement đủ mạnh.",),
                evidence=("NO_VALID_ORDER_BLOCK",),
                metadata={"implemented": True, "blocks": ()},
            )

        preferred_direction = None
        if lifecycle in (
            LifecycleStage.SPRING,
            LifecycleStage.ACCUMULATION,
            LifecycleStage.REACCUMULATION,
        ):
            preferred_direction = OrderBlockDirection.BULLISH
        elif lifecycle in (
            LifecycleStage.UPTHRUST,
            LifecycleStage.DISTRIBUTION,
            LifecycleStage.REDISTRIBUTION,
        ):
            preferred_direction = OrderBlockDirection.BEARISH

        preferred = [
            item
            for item in details
            if item.direction == preferred_direction
        ]
        selection_pool = preferred or details
        best = max(
            selection_pool,
            key=lambda item: item.overall_quality,
        )
        evidence = [
            f"ORDER_BLOCK_{best.direction.value}",
            f"ORDER_BLOCK_{best.state.value}",
        ]
        if best.bos_confirmed:
            evidence.append("ORDER_BLOCK_BOS_CONFIRMED")
        if best.breaker:
            evidence.append("BREAKER_BLOCK")
        if best.invalidated:
            evidence.append("ORDER_BLOCK_INVALIDATED")

        return MicrostructureEvidence(
            score=best.detection_confidence,
            phase_quality=best.overall_quality,
            age_bars=best.age_bars,
            explanation=best.explanation,
            evidence=tuple(evidence),
            metadata={
                "implemented": True,
                "selected_direction": best.direction.value,
                "selected_state": best.state.value,
                "zone_low": best.zone_low,
                "zone_high": best.zone_high,
                "midpoint": best.midpoint,
                "detection_confidence": best.detection_confidence,
                "freshness_score": best.freshness_score,
                "mitigation_score": best.mitigation_score,
                "reaction_quality": best.reaction_quality,
                "overall_quality": best.overall_quality,
                "invalidated": best.invalidated,
                "breaker": best.breaker,
                "bos_confirmed": best.bos_confirmed,
                "lifecycle_stage": (
                    best.lifecycle_stage.value
                    if best.lifecycle_stage is not None
                    else None
                ),
                "all_blocks": tuple(details),
            },
        )
