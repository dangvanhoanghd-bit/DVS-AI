from __future__ import annotations

import logging
from dataclasses import replace
from threading import Lock
from collections import defaultdict, deque
from typing import Iterable, Callable, Any

from dvs_ai.domain.models import CoinAnalysis, MicrostructureSnapshot
from dvs_ai.engines.microstructure_engine import MicrostructureEngine
from dvs_ai.services.order_flow_store import PersistentOrderFlowStore
from dvs_ai.services.order_flow_data_quality_gate import OrderFlowDataQualityGate

log = logging.getLogger(__name__)


class MicrostructureService:
    """
    Phase-1 service.

    Current implementation bootstraps from Binance public REST for a small
    ranked set. The storage/API boundary is intentionally compatible with a
    future asynchronous WebSocket collector.
    """

    def __init__(
        self,
        provider,
        engine: MicrostructureEngine | None = None,
        order_flow_store: PersistentOrderFlowStore | None = None,
        order_flow_quality_gate: OrderFlowDataQualityGate | None = None,
        collector_diagnostics_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.provider = provider
        self.engine = engine or MicrostructureEngine()
        self.order_flow_store = order_flow_store or PersistentOrderFlowStore()
        self.order_flow_quality_gate = order_flow_quality_gate or OrderFlowDataQualityGate()
        self.collector_diagnostics_provider = collector_diagnostics_provider
        self._snapshots: dict[str, MicrostructureSnapshot] = {}
        self._oi_history = defaultdict(lambda: deque(maxlen=12))
        self._delta_history = defaultdict(lambda: deque(maxlen=12))
        self._lock = Lock()

    def ingest_force_orders(self, events: Iterable[dict]) -> int:
        """Accept decoded Binance forceOrder payloads from a future collector.

        This method is intentionally passive: it never starts a socket and
        never changes execution state. The caller owns connection lifecycle.
        """
        return self.order_flow_store.ingest_force_orders(events, realtime=True)

    def order_flow_diagnostics(self) -> dict:
        return self.order_flow_store.diagnostics()

    def analyze_symbol(
        self,
        analysis: CoinAnalysis,
    ) -> MicrostructureSnapshot:
        raw = self.provider.fetch_microstructure_raw(
            analysis.symbol,
            depth_limit=100,
            trade_limit=500,
        )
        # REST trades truthfully seed the persistent CVD accumulator. They are
        # marked bootstrap, never realtime. Duplicate aggregate-trade IDs are
        # ignored by the store across repeated hydration cycles.
        self.order_flow_store.ingest_agg_trades(
            analysis.symbol, raw.get("agg_trades") or (), realtime=False
        )
        flow = self.order_flow_store.snapshot(analysis.symbol, window_seconds=300)
        raw = dict(raw)
        raw["liquidations"] = list(flow.liquidation_events)
        raw["order_flow_store_quality"] = flow.data_quality
        with self._lock:
            previous = self._snapshots.get(analysis.symbol)
        previous_wall_state = None
        if previous is not None:
            from datetime import datetime, timezone
            try:
                previous_ts = datetime.strptime(
                    previous.generated_at,
                    "%Y-%m-%d %H:%M:%S",
                ).replace(tzinfo=timezone.utc).timestamp()
            except (TypeError, ValueError):
                previous_ts = 0.0
            previous_wall_state = {
                "bid": {
                    "price": previous.bid_wall_price,
                    "notional": previous.bid_wall_notional,
                    "streak": previous.bid_wall_streak,
                    "first_seen_ts": (
                        previous_ts-previous.bid_wall_age_seconds
                        if previous_ts > 0 else 0.0
                    ),
                    "last_seen_ts": previous_ts,
                    "raw_score": previous.bid_wall_score,
                    "age_seconds": previous.bid_wall_age_seconds,
                },
                "ask": {
                    "price": previous.ask_wall_price,
                    "notional": previous.ask_wall_notional,
                    "streak": previous.ask_wall_streak,
                    "first_seen_ts": (
                        previous_ts-previous.ask_wall_age_seconds
                        if previous_ts > 0 else 0.0
                    ),
                    "last_seen_ts": previous_ts,
                    "raw_score": previous.ask_wall_score,
                    "age_seconds": previous.ask_wall_age_seconds,
                },
            }
        snapshot = self.engine.analyze(
            symbol=analysis.symbol,
            raw=raw,
            last_price=analysis.snapshot.last_price,
            oi_change_15m_pct=analysis.snapshot.oi_change_15m_pct,
            funding_pct=analysis.snapshot.funding_pct,
            price_change_pct=analysis.snapshot.change_24h_pct,
            previous_wall_state=previous_wall_state,
        )
        flow_total = snapshot.aggressive_buy_usd + snapshot.aggressive_sell_usd
        delta_ratio = (
            snapshot.trade_delta_usd / flow_total
            if flow_total > 0.0 else 0.0
        )
        delta_ratio = max(-1.0, min(1.0, float(delta_ratio)))
        with self._lock:
            self._snapshots[analysis.symbol] = snapshot
            self._oi_history[analysis.symbol].append(
                float(analysis.snapshot.oi_change_15m_pct)
            )
            self._delta_history[analysis.symbol].append(delta_ratio)
        return snapshot

    def position_context(self, analysis: CoinAnalysis) -> dict:
        """Return normalized, real microstructure inputs for Position Building.

        This is intentionally derived only after ranked-symbol hydration. It
        prevents the broad scanner from issuing extra depth/trade requests for
        every universe symbol while ensuring the top-N footprint is recomputed
        with actual Delta, liquidation and persistence history.
        """
        micro = analysis.microstructure
        if micro is None:
            return {}
        flow_total = micro.aggressive_buy_usd + micro.aggressive_sell_usd
        delta_ratio = (
            micro.trade_delta_usd / flow_total
            if flow_total > 0.0 else 0.0
        )
        delta_ratio = max(-1.0, min(1.0, float(delta_ratio)))
        with self._lock:
            oi_series = tuple(self._oi_history.get(analysis.symbol, ()))
            delta_series = tuple(self._delta_history.get(analysis.symbol, ()))
        flow = self.order_flow_store.snapshot(analysis.symbol, window_seconds=300)
        collector_diag = {}
        if self.collector_diagnostics_provider is not None:
            try:
                collector_diag = dict(self.collector_diagnostics_provider() or {})
            except Exception as exc:
                log.warning("Order-flow diagnostics unavailable: %s", exc)
                collector_diag = {"state": "ERROR", "running": False}
        quality = self.order_flow_quality_gate.assess(
            flow,
            collector_diagnostics=collector_diag,
            liquidation_data_available=bool(micro.liquidation_data_available),
        )
        cvd_slope = 0.0
        flow_notional = flow.buy_notional + flow.sell_notional
        if flow_notional > 0.0:
            # Dimensionless bounded slope proxy: five-minute CVD velocity
            # normalized by observed notional per second.
            notional_per_second = flow_notional / max(1.0, flow.window_seconds)
            cvd_slope = max(-1.0, min(1.0,
                flow.cvd_slope_usd_per_sec / max(1.0, notional_per_second)
            ))
        elif len(delta_series) >= 2:
            cvd_slope = max(-1.0, min(1.0, delta_series[-1]-delta_series[-2]))
        gated_delta = delta_ratio * quality.confidence_multiplier if quality.allow_cvd else 0.0
        gated_cvd = cvd_slope * quality.confidence_multiplier if quality.allow_cvd else 0.0
        gated_liquidation = (
            float(micro.liquidation_impulse) * quality.confidence_multiplier
            if quality.allow_liquidation else 0.0
        )
        return {
            "delta_ratio": gated_delta,
            "cvd_slope": gated_cvd,
            "liquidation_impulse": gated_liquidation,
            "absorption_score": float(micro.absorption_score),
            "oi_change_series": oi_series,
            "delta_ratio_series": delta_series,
            "microstructure_data_quality": str(micro.data_quality),
            "liquidation_data_available": bool(micro.liquidation_data_available),
            "cumulative_cvd_usd": float(flow.cumulative_cvd_usd),
            "order_flow_data_quality": flow.data_quality,
            "order_flow_trade_events": int(flow.trade_events),
            "liquidation_event_count": int(flow.liquidation_event_count),
            "order_flow_quality_gate": quality.state,
            "order_flow_confidence_multiplier": quality.confidence_multiplier,
            "order_flow_allow_confirmation": quality.allow_directional_confirmation,
            "order_flow_allow_cvd": quality.allow_cvd,
            "order_flow_allow_liquidation": quality.allow_liquidation,
            "order_flow_event_age_seconds": quality.event_age_seconds,
            "order_flow_quality_reasons": quality.reasons,
        }

    def hydrate_ranked(
        self,
        results: dict[str, CoinAnalysis],
        max_symbols: int = 8,
    ) -> dict[str, CoinAnalysis]:
        hydrated = dict(results)
        ranked = sorted(
            (
                item for item in results.values()
                if item.symbol != "BTC/USDT:USDT"
            ),
            key=lambda item: (
                item.opportunity_gate == "RANKED",
                -item.opportunity_rank,
                item.opportunity_score,
            ),
            reverse=True,
        )
        for analysis in ranked[:max(1, int(max_symbols))]:
            try:
                snapshot = self.analyze_symbol(analysis)
                gate = self._direction_gate(analysis, snapshot)
                reasons = list(analysis.reasons)
                context = self.position_context(replace(analysis, microstructure=snapshot))
                quality_gate = str(context.get("order_flow_quality_gate", "BLOCKED"))
                if not bool(context.get("order_flow_allow_confirmation", False)):
                    gate = "QUALITY_BLOCKED"
                reasons.append(
                    "Microstructure: "
                    f"COS {snapshot.composite_operator_score:.1f} · "
                    f"{snapshot.operator_bias} · {gate} · OFQ {quality_gate}"
                )
                hydrated[analysis.symbol] = replace(
                    analysis,
                    microstructure=snapshot,
                    microstructure_gate=gate,
                    reasons=tuple(reasons),
                )
            except Exception as exc:
                log.warning(
                    "Microstructure unavailable %s: %s",
                    analysis.symbol,
                    exc,
                )
        return hydrated


    @staticmethod
    def _direction_gate(
        analysis: CoinAnalysis,
        snapshot: MicrostructureSnapshot,
    ) -> str:
        aligned = (
            analysis.direction == "LONG"
            and snapshot.operator_bias == "SMART_MONEY_LONG"
        ) or (
            analysis.direction == "SHORT"
            and snapshot.operator_bias == "SMART_MONEY_SHORT"
        )
        opposed = (
            analysis.direction == "LONG"
            and snapshot.operator_bias == "SMART_MONEY_SHORT"
        ) or (
            analysis.direction == "SHORT"
            and snapshot.operator_bias == "SMART_MONEY_LONG"
        )
        cos = snapshot.composite_operator_score
        if aligned:
            if cos >= 82:
                return "STRONG_CONFIRMATION"
            if cos >= 68:
                return "CONFIRMATION"
            if cos >= 55:
                return "WEAK_CONFIRMATION"
        if opposed:
            if cos >= 82:
                return "STRONG_CONFLICT"
            if cos >= 68:
                return "CONFLICT"
            if cos >= 55:
                return "WEAK_CONFLICT"
        return "OBSERVE"

    @staticmethod
    def apply_decision_adjustment(
        analysis: CoinAnalysis,
        weight: float = 0.25,
        confirm_bonus: float = 6.0,
        conflict_penalty: float = 12.0,
    ) -> CoinAnalysis:
        """
        Apply microstructure as a confirmation/denial layer after Wyckoff,
        Direction, Maturity and Market Bias have already produced an analysis.

        Microstructure cannot create READY from WAIT/RUNNING and cannot bypass
        liquidation, maturity or market-bias hard gates.
        """
        micro = analysis.microstructure
        if micro is None:
            return analysis

        gate = analysis.microstructure_gate
        confidence = float(analysis.confidence_score)
        status = analysis.entry_status
        reasons = list(analysis.reasons)

        scaled = (
            micro.composite_operator_score
            * max(0.0, min(0.50, float(weight)))
            / 100.0
        )
        delta = 0.0

        confirmation_factors = {
            "STRONG_CONFIRMATION": 1.00,
            "CONFIRMATION": 0.72,
            "WEAK_CONFIRMATION": 0.35,
        }
        conflict_factors = {
            "STRONG_CONFLICT": 1.00,
            "CONFLICT": 0.75,
            "WEAK_CONFLICT": 0.40,
        }

        if gate == "QUALITY_BLOCKED":
            reasons.append("Microstructure confirmation blocked by order-flow data quality.")
        elif gate in confirmation_factors:
            if (
                status.value not in ("WAIT", "RUNNING")
                and analysis.risk.liquidation_safe
                and analysis.maturity_gate not in ("LATE", "EXHAUSTION")
                and not analysis.market_bias_gate.startswith("BLOCK")
            ):
                delta = min(
                    max(0.0, float(confirm_bonus)),
                    scaled * 100.0 * confirmation_factors[gate],
                )
                confidence += delta
        elif gate in conflict_factors:
            delta = -min(
                max(0.0, float(conflict_penalty)),
                scaled * 100.0 * conflict_factors[gate],
            )
            confidence += delta
            if gate == "STRONG_CONFLICT":
                status = type(status).WAIT
            elif gate == "CONFLICT" and status.value == "READY":
                status = type(status).SETUP

        confidence = max(0.0, min(92.0, confidence))
        if delta:
            reasons.append(
                "Microstructure Decision Adjustment: "
                f"{delta:+.1f} confidence · {gate} · "
                f"COS {micro.composite_operator_score:.1f}."
            )

        return replace(
            analysis,
            confidence_score=confidence,
            entry_status=status,
            microstructure_gate=gate,
            reasons=tuple(reasons),
        )

    def snapshot(self, symbol: str) -> MicrostructureSnapshot | None:
        with self._lock:
            return self._snapshots.get(symbol)

    def all_snapshots(self) -> tuple[MicrostructureSnapshot, ...]:
        with self._lock:
            return tuple(self._snapshots.values())
