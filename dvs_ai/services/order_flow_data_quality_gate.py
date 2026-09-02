from __future__ import annotations

import math
import time
from dataclasses import dataclass, asdict
from typing import Any, Callable

from dvs_ai.services.order_flow_store import OrderFlowSnapshot


@dataclass(frozen=True)
class OrderFlowQualityAssessment:
    state: str
    confidence_multiplier: float
    allow_directional_confirmation: bool
    allow_cvd: bool
    allow_liquidation: bool
    event_age_seconds: float | None
    reasons: tuple[str, ...]

    def diagnostics(self) -> dict[str, Any]:
        return asdict(self)


class OrderFlowDataQualityGate:
    """Fail-safe quality boundary for order-flow evidence.

    The gate never creates a signal. It only decides how much of the available
    order-flow evidence may be trusted by Position Building and the later
    microstructure confirmation layer.
    """

    def __init__(
        self,
        *,
        stale_after_seconds: float = 25.0,
        min_realtime_trades: int = 3,
        bootstrap_multiplier: float = 0.40,
        degraded_multiplier: float = 0.55,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.stale_after_seconds = max(2.0, float(stale_after_seconds))
        self.min_realtime_trades = max(1, int(min_realtime_trades))
        self.bootstrap_multiplier = max(0.0, min(1.0, float(bootstrap_multiplier)))
        self.degraded_multiplier = max(0.0, min(1.0, float(degraded_multiplier)))
        self._clock = clock

    @staticmethod
    def _finite(value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        return number if math.isfinite(number) else default

    def assess(
        self,
        snapshot: OrderFlowSnapshot,
        *,
        collector_diagnostics: dict[str, Any] | None = None,
        liquidation_data_available: bool = False,
        now_ts: float | None = None,
    ) -> OrderFlowQualityAssessment:
        diag = dict(collector_diagnostics or {})
        now = self._finite(now_ts, self._clock())
        newest = self._finite(snapshot.newest_event_ts)
        age = None if newest <= 0.0 else max(0.0, now - newest)
        reasons: list[str] = []

        if snapshot.data_quality == "EMPTY" or snapshot.trade_events <= 0:
            return OrderFlowQualityAssessment(
                state="BLOCKED",
                confidence_multiplier=0.0,
                allow_directional_confirmation=False,
                allow_cvd=False,
                allow_liquidation=False,
                event_age_seconds=age,
                reasons=("NO_ORDER_FLOW_TRADES",),
            )

        if age is None or age > self.stale_after_seconds:
            reasons.append("STALE_ORDER_FLOW")

        unresolved = max(0, int(self._finite(diag.get("gaps_unresolved"))))
        if unresolved:
            reasons.append("UNRESOLVED_AGGTRADE_GAP")

        collector_state = str(diag.get("state") or "").upper()
        collector_running = bool(diag.get("running", False))
        if snapshot.data_quality == "REALTIME" and diag:
            if collector_state != "CONNECTED" or not collector_running:
                reasons.append("COLLECTOR_NOT_HEALTHY")

        liq_warnings = max(0, int(self._finite(diag.get("liquidation_gap_warnings"))))
        allow_liquidation = bool(liquidation_data_available)
        if not allow_liquidation:
            reasons.append("LIQUIDATION_FEED_UNAVAILABLE")
        elif liq_warnings:
            allow_liquidation = False
            reasons.append("LIQUIDATION_GAP_INCOMPLETE")

        if "STALE_ORDER_FLOW" in reasons:
            return OrderFlowQualityAssessment(
                state="BLOCKED",
                confidence_multiplier=0.0,
                allow_directional_confirmation=False,
                allow_cvd=False,
                allow_liquidation=False,
                event_age_seconds=age,
                reasons=tuple(reasons),
            )

        if snapshot.data_quality == "BOOTSTRAP":
            reasons.append("REST_BOOTSTRAP_ONLY")
            return OrderFlowQualityAssessment(
                state="DEGRADED",
                confidence_multiplier=self.bootstrap_multiplier,
                allow_directional_confirmation=False,
                allow_cvd=True,
                allow_liquidation=False,
                event_age_seconds=age,
                reasons=tuple(reasons),
            )

        if snapshot.trade_events < self.min_realtime_trades:
            reasons.append("INSUFFICIENT_REALTIME_SAMPLES")

        severe_degradation = any(reason in reasons for reason in (
            "UNRESOLVED_AGGTRADE_GAP",
            "COLLECTOR_NOT_HEALTHY",
            "INSUFFICIENT_REALTIME_SAMPLES",
        ))
        if severe_degradation:
            return OrderFlowQualityAssessment(
                state="DEGRADED",
                confidence_multiplier=self.degraded_multiplier,
                allow_directional_confirmation=False,
                allow_cvd=True,
                allow_liquidation=allow_liquidation,
                event_age_seconds=age,
                reasons=tuple(reasons),
            )

        return OrderFlowQualityAssessment(
            state="FULL",
            confidence_multiplier=1.0,
            allow_directional_confirmation=True,
            allow_cvd=True,
            allow_liquidation=allow_liquidation,
            event_age_seconds=age,
            reasons=tuple(reasons),
        )
