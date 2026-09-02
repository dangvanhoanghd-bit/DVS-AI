from __future__ import annotations

from math import isfinite
from typing import Any

import pandas as pd

from .base import LifecycleStage, MicrostructureEvidence
from .base_engine import EvidenceEngine


class PositionBuildingEngine(EvidenceEngine):
    """
    Futures positioning evidence from OI, funding, price, delta/CVD proxy and
    liquidation context.

    It emits evidence only and never creates a trade decision.
    """

    @staticmethod
    def _f(value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
            return number if isfinite(number) else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(100.0, float(value)))

    @staticmethod
    def _series(value: Any) -> tuple[float, ...]:
        if value is None:
            return ()
        try:
            if isinstance(value, pd.Series):
                items = value.tolist()
            elif isinstance(value, (list, tuple)):
                items = list(value)
            else:
                return ()
            out = []
            for item in items:
                # Preserve time continuity. Missing/invalid samples are neutral
                # separators instead of being removed and joining two unrelated
                # runs into a false persistence streak.
                try:
                    number = float(item)
                except (TypeError, ValueError):
                    number = 0.0
                out.append(number if isfinite(number) else 0.0)
            return tuple(out)
        except (TypeError, ValueError):
            return ()

    @classmethod
    def persistence_score(
        cls,
        oi_series: tuple[float, ...],
        direction: str,
    ) -> float:
        """
        Measures whether OI changes persist in the same build direction.
        Positive OI persistence matters for LONG_BUILDING/SHORT_BUILDING;
        negative OI persistence matters for covering/closing regimes.
        """
        if len(oi_series) < 3:
            return 0.0
        sign = 1.0 if direction in ("LONG_BUILDING", "SHORT_BUILDING") else -1.0
        aligned = [1.0 if value*sign > 0.0 else 0.0 for value in oi_series[-12:]]
        ratio = sum(aligned)/len(aligned)
        streak = 0
        for value in reversed(oi_series[-12:]):
            if value*sign > 0.0:
                streak += 1
            else:
                break
        return cls._clamp(ratio*70.0 + min(30.0, streak*5.0))

    @classmethod
    def acceleration_score(cls, oi_series: tuple[float, ...]) -> float:
        if len(oi_series) < 4:
            return 0.0
        recent = oi_series[-6:]
        deltas = [
            abs(recent[i])-abs(recent[i-1])
            for i in range(1, len(recent))
        ]
        positive = [value for value in deltas if value > 0.0]
        if not positive:
            return 0.0
        mean_accel = sum(positive)/len(deltas)
        consistency = len(positive)/len(deltas)
        return cls._clamp(mean_accel*40.0 + consistency*45.0)

    @classmethod
    def funding_extreme_score(cls, funding_pct: float) -> float:
        """
        Convert funding expressed in percentage points
        (Binance lastFundingRate * 100) into a 0-100 crowding score.

        0.10 means 0.10%/8h, not a decimal fraction.
        """
        funding = cls._f(funding_pct)
        return cls._clamp(
            max(0.0, abs(funding) - 0.01) * 120.0
        )

    def analyze(
        self,
        ohlcv: pd.DataFrame,
        context: dict,
    ) -> MicrostructureEvidence:
        oi = self._f(context.get("oi_change_15m_pct"))
        funding = self._f(context.get("funding_pct"))
        price_change = self._f(context.get("price_change_pct"))
        # Ratios are bounded by definition. Clamp untrusted context so one
        # malformed provider value cannot saturate the complete evidence score.
        delta_ratio = max(-1.0, min(1.0, self._f(context.get("delta_ratio"))))
        cvd_slope = max(-1.0, min(1.0, self._f(context.get("cvd_slope"))))
        liquidation_impulse = self._clamp(self._f(
            context.get("liquidation_impulse")
        ))
        absorption = self._clamp(self._f(context.get("absorption_score")))
        oi_series = self._series(context.get("oi_change_series"))
        delta_series = self._series(context.get("delta_ratio_series"))
        lifecycle = context.get("lifecycle_stage")
        order_flow_quality_gate = str(
            context.get("order_flow_quality_gate", "UNKNOWN")
        ).upper()
        order_flow_confidence_multiplier = max(0.0, min(1.0, self._f(
            context.get("order_flow_confidence_multiplier", 1.0), 1.0
        )))
        order_flow_quality_reasons = tuple(
            str(item) for item in (context.get("order_flow_quality_reasons") or ())
        )

        if isinstance(lifecycle, LifecycleStage):
            lifecycle_name = lifecycle.name
        else:
            lifecycle_name = str(lifecycle or "UNKNOWN").upper()

        oi_strength = self._clamp(abs(oi) * 22.0)
        funding_extreme = self.funding_extreme_score(funding)
        delta_strength = self._clamp(
            max(abs(delta_ratio), abs(cvd_slope)) * 100.0
        )

        evidence: list[str] = []
        explanation: list[str] = []

        if oi > 0.10 and price_change > 0.05:
            regime = "LONG_BUILDING"
            direction = "LONG"
            evidence.append("POSITION_LONG_BUILDING")
        elif oi > 0.10 and price_change < -0.05:
            regime = "SHORT_BUILDING"
            direction = "SHORT"
            evidence.append("POSITION_SHORT_BUILDING")
        elif oi < -0.10 and price_change > 0.05:
            regime = "SHORT_COVERING"
            direction = "LONG"
            evidence.append("POSITION_SHORT_COVERING")
        elif oi < -0.10 and price_change < -0.05:
            regime = "LONG_CLOSING"
            direction = "SHORT"
            evidence.append("POSITION_LONG_CLOSING")
        else:
            regime = "NEUTRAL"
            direction = "NEUTRAL"
            evidence.append("POSITION_NEUTRAL")

        persistence = self.persistence_score(oi_series, regime)
        acceleration = self.acceleration_score(oi_series)
        delta_persistence = 0.0
        if len(delta_series) >= 3 and direction != "NEUTRAL":
            sign = 1.0 if direction == "LONG" else -1.0
            aligned = sum(
                1 for value in delta_series[-12:]
                if value*sign > 0.0
            )
            delta_persistence = self._clamp(
                aligned/max(1, len(delta_series[-12:]))*100.0
            )

        # Directional order-flow confirmation.
        order_flow_confirm = 0.0
        if direction == "LONG":
            if delta_ratio > 0.08 or cvd_slope > 0.08:
                order_flow_confirm = 18.0
                evidence.append("CVD_DELTA_LONG_CONFIRM")
            elif delta_ratio < -0.08 and absorption >= 45:
                order_flow_confirm = 14.0
                evidence.append("SELL_ABSORPTION_LONG")
        elif direction == "SHORT":
            if delta_ratio < -0.08 or cvd_slope < -0.08:
                order_flow_confirm = 18.0
                evidence.append("CVD_DELTA_SHORT_CONFIRM")
            elif delta_ratio > 0.08 and absorption >= 45:
                order_flow_confirm = 14.0
                evidence.append("BUY_ABSORPTION_SHORT")

        # Funding contrarian context and crowding risk are independent.
        # A setup may have valid contrarian structure while funding is also
        # dangerously crowded; both facts must remain visible.
        contrarian_bonus = 0.0
        crowding_penalty = 0.0
        early_long = lifecycle_name in (
            "SPRING", "TEST", "ACCUMULATION", "REACCUMULATION"
        )
        early_short = lifecycle_name in (
            "UPTHRUST", "TEST", "DISTRIBUTION", "REDISTRIBUTION"
        )

        if direction == "LONG" and funding < -0.01 and early_long:
            contrarian_bonus = 16.0
            evidence.append("NEGATIVE_FUNDING_BULLISH_CONTEXT")
        elif direction == "SHORT" and funding > 0.01 and early_short:
            contrarian_bonus = 16.0
            evidence.append("POSITIVE_FUNDING_BEARISH_CONTEXT")

        if funding_extreme >= 60.0:
            crowding_penalty = -10.0
            evidence.append("FUNDING_CROWDING_RISK")

        funding_context = contrarian_bonus + crowding_penalty

        liquidation_bonus = 0.0
        if liquidation_impulse >= 35:
            liquidation_bonus = 8.0
            evidence.append("LIQUIDATION_IMPULSE")

        base = (
            0.30*oi_strength
            + 0.18*delta_strength
            + 0.14*absorption
            + 0.08*liquidation_impulse
            + 0.12*persistence
            + 0.08*acceleration
            + 0.06*delta_persistence
            + order_flow_confirm
            + funding_context
            + liquidation_bonus
        )
        if regime == "NEUTRAL":
            base *= 0.55

        score = self._clamp(base)
        agreement_factors = [
            oi_strength >= 35.0,
            delta_strength >= 25.0 or delta_persistence >= 55.0,
            absorption >= 45.0,
            persistence >= 55.0,
            direction != "NEUTRAL",
        ]
        position_confidence = self._clamp(
            sum(agreement_factors)/len(agreement_factors)*100.0
        )
        quality = self._clamp(
            score
            + (8.0 if lifecycle_name in (
                "SPRING", "TEST", "ACCUMULATION",
                "UPTHRUST", "DISTRIBUTION",
            ) else 0.0)
            - (18.0 if lifecycle_name in (
                "MARKUP", "MARKDOWN", "EXHAUSTION"
            ) else 0.0)
        )

        explanation.extend((
            f"Position regime {regime}.",
            f"OI {oi:+.3f}% · Price {price_change:+.3f}% · "
            f"Funding {funding:+.4f}% · Extreme {funding_extreme:.1f}/100.",
            f"Delta ratio {delta_ratio:+.3f} · CVD slope {cvd_slope:+.3f}.",
            f"Absorption {absorption:.1f} · Liquidation {liquidation_impulse:.1f}.",
            f"Persistence {persistence:.1f} · Acceleration {acceleration:.1f} · "
            f"Delta persistence {delta_persistence:.1f}.",
            f"Lifecycle {lifecycle_name} · Quality {quality:.1f}/100 · "
            f"Confidence {position_confidence:.1f}/100.",
        ))

        if persistence >= 60.0:
            evidence.append("POSITION_PERSISTENCE_CONFIRMED")
        if acceleration >= 55.0:
            evidence.append("POSITION_ACCELERATION")
        if position_confidence >= 70.0:
            evidence.append("POSITION_HIGH_CONFIDENCE")
        if direction != "NEUTRAL":
            evidence.append(f"POSITION_DIRECTION_{direction}")

        return MicrostructureEvidence(
            score=score,
            phase_quality=quality,
            stage=lifecycle if isinstance(lifecycle, LifecycleStage) else None,
            explanation=tuple(explanation),
            evidence=tuple(evidence),
            metadata={
                "implemented": True,
                "regime": regime,
                "direction": direction,
                "oi_change_15m_pct": oi,
                "funding_pct": funding,
                "funding_extreme_score": funding_extreme,
                "funding_crowding_risk": funding_extreme >= 60.0,
                "funding_contrarian_bonus": contrarian_bonus,
                "funding_crowding_penalty": crowding_penalty,
                "price_change_pct": price_change,
                "delta_ratio": delta_ratio,
                "cvd_slope": cvd_slope,
                "liquidation_impulse": liquidation_impulse,
                "absorption_score": absorption,
                "persistence_score": persistence,
                "acceleration_score": acceleration,
                "delta_persistence_score": delta_persistence,
                "position_confidence": position_confidence,
                "oi_series_samples": len(oi_series),
                "delta_series_samples": len(delta_series),
                "overall_quality": quality,
                "input_normalization": "FAIL_SAFE_V3",
                "order_flow_quality_gate": order_flow_quality_gate,
                "order_flow_confidence_multiplier": order_flow_confidence_multiplier,
                "order_flow_quality_reasons": order_flow_quality_reasons,
            },
        )
