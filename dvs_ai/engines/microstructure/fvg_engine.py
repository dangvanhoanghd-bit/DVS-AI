from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping

import pandas as pd

from .base import MicrostructureEvidence
from .base_engine import EvidenceEngine


class FVGDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class FVGState(str, Enum):
    FRESH = "FRESH"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True)
class FVGDetails:
    direction: FVGDirection
    state: FVGState
    age_bars: int
    zone_low: float
    zone_high: float
    gap_pct: float
    fill_pct: float
    displacement_score: float
    freshness_score: float
    reaction_quality: float
    overall_quality: float
    explanation: tuple[str, ...]
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        for name in (
            "gap_pct",
            "fill_pct",
            "displacement_score",
            "freshness_score",
            "reaction_quality",
            "overall_quality",
        ):
            object.__setattr__(self, name, float(getattr(self, name)))
        object.__setattr__(self, "age_bars", max(0, int(self.age_bars)))
        object.__setattr__(self, "explanation", tuple(self.explanation or ()))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata or {})))


class FVGEngine(EvidenceEngine):
    """Three-candle Fair Value Gap / imbalance evidence engine."""

    @staticmethod
    def _normalise(df: pd.DataFrame) -> pd.DataFrame:
        aliases = {"o":"open","h":"high","l":"low","c":"close","v":"volume"}
        out = df.rename(columns=aliases).copy()
        required = ("open","high","low","close","volume")
        missing = [c for c in required if c not in out.columns]
        if missing:
            raise ValueError("Missing OHLCV columns: " + ", ".join(missing))
        for c in required:
            out[c] = pd.to_numeric(out[c], errors="coerce")
        return out.dropna(subset=list(required)).reset_index(drop=True)

    @staticmethod
    def _clamp(x: float) -> float:
        return max(0.0, min(100.0, float(x)))

    def analyze(self, ohlcv: pd.DataFrame, context: dict) -> MicrostructureEvidence:
        data = self._normalise(ohlcv)
        if len(data) < 30:
            return MicrostructureEvidence(
                score=20.0,
                phase_quality=15.0,
                explanation=("Dữ liệu quá ít để phát hiện FVG.",),
                evidence=("INSUFFICIENT_FVG_HISTORY",),
                metadata={"implemented": True, "bars": len(data)},
            )

        avg_range = (data["high"]-data["low"]).rolling(20).mean().bfill()
        candidates: list[FVGDetails] = []

        for i in range(2, len(data)):
            a = data.iloc[i-2]
            b = data.iloc[i-1]
            c = data.iloc[i]
            price = max(float(b["close"]), 1e-12)
            body = abs(float(b["close"])-float(b["open"]))
            displacement = body/max(float(avg_range.iloc[i-1]), 1e-12)
            displacement_score = self._clamp(displacement*45.0)

            # Bullish FVG: candle 3 low above candle 1 high.
            if float(c["low"]) > float(a["high"]):
                low = float(a["high"])
                high = float(c["low"])
                candidates.append(self._evaluate(
                    data, i, FVGDirection.BULLISH, low, high,
                    displacement_score, price
                ))

            # Bearish FVG: candle 3 high below candle 1 low.
            if float(c["high"]) < float(a["low"]):
                low = float(c["high"])
                high = float(a["low"])
                candidates.append(self._evaluate(
                    data, i, FVGDirection.BEARISH, low, high,
                    displacement_score, price
                ))

        if not candidates:
            return MicrostructureEvidence(
                score=28.0,
                phase_quality=22.0,
                explanation=("Không có FVG ba nến đủ rõ.",),
                evidence=("NO_VALID_FVG",),
                metadata={"implemented": True, "gaps": ()},
            )

        best = max(candidates, key=lambda x: x.overall_quality)
        same_direction = [gap for gap in candidates if gap.direction == best.direction and abs(gap.age_bars-best.age_bars) <= 20]
        cluster_count = len(same_direction)
        cluster_bonus = min(10.0, max(0, cluster_count-1)*3.0)
        adjusted_quality = self._clamp(best.overall_quality+cluster_bonus)
        untouched = best.fill_pct <= 0.0
        evidence = (
            f"FVG_{best.direction.value}",
            f"FVG_{best.state.value}",
        )
        return MicrostructureEvidence(
            score=best.displacement_score,
            phase_quality=adjusted_quality,
            age_bars=best.age_bars,
            explanation=best.explanation,
            evidence=evidence,
            metadata={
                "implemented": True,
                "direction": best.direction.value,
                "state": best.state.value,
                "zone_low": best.zone_low,
                "zone_high": best.zone_high,
                "gap_pct": best.gap_pct,
                "fill_pct": best.fill_pct,
                "freshness_score": best.freshness_score,
                "reaction_quality": best.reaction_quality,
                "overall_quality": adjusted_quality,
                "base_quality": best.overall_quality,
                "cluster_count": cluster_count,
                "multi_fvg_cluster": cluster_count >= 2,
                "untouched": untouched,
                "all_gaps": tuple(candidates),
            },
        )

    def _evaluate(
        self,
        data: pd.DataFrame,
        origin: int,
        direction: FVGDirection,
        zone_low: float,
        zone_high: float,
        displacement_score: float,
        price: float,
    ) -> FVGDetails:
        later = data.iloc[origin+1:]
        height = max(zone_high-zone_low, 1e-12)
        age = len(data)-1-origin
        fill_pct = 0.0
        reaction = 0.0

        if not later.empty:
            if direction == FVGDirection.BULLISH:
                lowest = float(later["low"].min())
                fill_pct = self._clamp((zone_high-lowest)/height*100.0)
                after_touch = later[later["low"] <= zone_high]
                if not after_touch.empty:
                    first = after_touch.index[0]
                    follow = data.loc[first:first+3]
                    reaction = max(0.0, float(follow["high"].max())-zone_high)
            else:
                highest = float(later["high"].max())
                fill_pct = self._clamp((highest-zone_low)/height*100.0)
                after_touch = later[later["high"] >= zone_low]
                if not after_touch.empty:
                    first = after_touch.index[0]
                    follow = data.loc[first:first+3]
                    reaction = max(0.0, zone_low-float(follow["low"].min()))

        if fill_pct >= 100.0:
            state = FVGState.FILLED
        elif fill_pct > 0.0:
            state = FVGState.PARTIAL
        else:
            state = FVGState.FRESH

        freshness = self._clamp(
            100.0 - age*1.3 - min(45.0, fill_pct*0.45)
        )
        gap_pct = height/max(price, 1e-12)*100.0
        reaction_quality = self._clamp(reaction/height*30.0)
        overall = self._clamp(
            0.34*displacement_score
            + 0.28*freshness
            + 0.20*reaction_quality
            + 0.18*self._clamp(gap_pct*180.0)
            - (18.0 if state == FVGState.FILLED else 0.0)
        )
        explanation = (
            f"{direction.value} FVG {state.value}.",
            f"Zone {zone_low:.6g}-{zone_high:.6g}; age {age} bars.",
            f"Gap {gap_pct:.3f}% · Fill {fill_pct:.1f}% · Quality {overall:.1f}.",
        )
        return FVGDetails(
            direction=direction,
            state=state,
            age_bars=age,
            zone_low=zone_low,
            zone_high=zone_high,
            gap_pct=gap_pct,
            fill_pct=fill_pct,
            displacement_score=displacement_score,
            freshness_score=freshness,
            reaction_quality=reaction_quality,
            overall_quality=overall,
            explanation=explanation,
            metadata={"origin_index": origin},
        )
