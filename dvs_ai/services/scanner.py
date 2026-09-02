from __future__ import annotations
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import replace, is_dataclass
from dvs_ai.data.binance_provider import BinanceFuturesProvider
from dvs_ai.engines.indicator_engine import IndicatorEngine
from dvs_ai.engines.decision_engine import DecisionEngine
from dvs_ai.engines.structure_engine import StructureEngine
from dvs_ai.engines.regime_engine import MarketRegimeEngine
from dvs_ai.engines.alignment_engine import MultiTimeframeEngine
from dvs_ai.engines.smart_entry_engine import SmartEntryEngine
from dvs_ai.engines.microstructure import FootprintOrchestrator
from dvs_ai.engines.composite_exhaustion_engine import CompositeExhaustionEngine
from dvs_ai.engines.explainable_narrative_engine import ExplainableNarrativeEngine
from dvs_ai.domain.models import CoinAnalysis, MarketBrief, EntryStatus
from dvs_ai.services.microstructure_service import MicrostructureService
from dvs_ai.services.probability_calibration_service import ProbabilityCalibrationService
from dvs_ai.services.adaptive_confidence_service import AdaptiveConfidenceService
from dvs_ai.services.calibration_drift_monitor import CalibrationDriftMonitor
from dvs_ai.services.evidence_reliability_service import EvidenceReliabilityService
from dvs_ai.services.frame_ownership_telemetry import FRAME_OWNERSHIP
from dvs_ai.services.network_startup_telemetry import NETWORK_STARTUP
from dvs_ai.services.stage_boundary_telemetry import STAGE_BOUNDARY

log = logging.getLogger(__name__)

class ScannerService:
    def __init__(self, provider, indicator, decision, ohlcv_limit=260, structure=None, regime=None, alignment=None, smart_entry=None, microstructure_service=None, probability_calibrator=None, adaptive_confidence_service=None, calibration_drift_monitor=None, evidence_reliability_service=None):
        self.provider=provider
        self.indicator=indicator
        self.decision=decision
        self.ohlcv_limit=ohlcv_limit
        self.structure=structure or StructureEngine()
        self.regime=regime or MarketRegimeEngine()
        self.alignment=alignment or MultiTimeframeEngine()
        self.smart_entry=smart_entry or SmartEntryEngine()
        self.microstructure = microstructure_service or MicrostructureService(provider)
        self.probability_calibrator = probability_calibrator or ProbabilityCalibrationService()
        self.adaptive_confidence_service = adaptive_confidence_service or AdaptiveConfidenceService(db_path=str(self.probability_calibrator.db_path))
        self.calibration_drift_monitor = calibration_drift_monitor or CalibrationDriftMonitor(db_path=str(self.probability_calibrator.db_path))
        self.evidence_reliability_service = evidence_reliability_service or EvidenceReliabilityService(db_path=str(self.probability_calibrator.db_path))
        self.footprint_orchestrator = FootprintOrchestrator()
        self.composite_exhaustion_engine = CompositeExhaustionEngine()
        self.explainable_narrative_engine = ExplainableNarrativeEngine()
        self.universe_cache=[]
        self.universe_cursor=0
        # SCAN-DISCOVERY-02-R3: independent cursor for bounded watchlist quota.
        self.pinned_cursor=0
        self._frame_lock = threading.RLock()
        self._frame_cache: OrderedDict[
            tuple[str, str, int],
            tuple[float, object],
        ] = OrderedDict()
        self._frame_cache_max = 500
        self._frame_cache_ttl = 25.0

    def _frame(
        self,
        symbol: str,
        timeframe: str,
        scan_id: str = "UNKNOWN",
    ):
        key = (symbol, timeframe, int(self.ohlcv_limit))
        now = time.monotonic()
        with self._frame_lock:
            cached = self._frame_cache.get(key)
            if cached is not None:
                expires_at, frame = cached
                if expires_at > now:
                    self._frame_cache.move_to_end(key)
                    FRAME_OWNERSHIP.checkout(
                        frame, scan_id=scan_id, symbol=symbol,
                        timeframe=timeframe, cache_hit=True,
                    )
                    return frame
                self._frame_cache.pop(key, None)

        frame = self.provider.fetch_ohlcv(
            symbol,
            timeframe,
            self.ohlcv_limit,
        )
        with self._frame_lock:
            self._frame_cache[key] = (
                now+self._frame_cache_ttl,
                frame,
            )
            self._frame_cache.move_to_end(key)
            while len(self._frame_cache) > self._frame_cache_max:
                self._frame_cache.popitem(last=False)
        FRAME_OWNERSHIP.checkout(
            frame, scan_id=scan_id, symbol=symbol,
            timeframe=timeframe, cache_hit=False,
        )
        return frame

    def scan_coin(
        self,
        symbol: str,
        timeframes: tuple[str, ...],
        scan_id: str = "UNKNOWN",
    ) -> CoinAnalysis:
        snapshot_started = time.monotonic()
        NETWORK_STARTUP.emit(
            "snapshot_fetch_enter",
            scan_id=str(scan_id or "UNKNOWN"),
            symbol=symbol,
        )
        try:
            snap = self.provider.fetch_snapshot(symbol)
        except Exception as exc:
            NETWORK_STARTUP.emit(
                "snapshot_fetch_error",
                scan_id=str(scan_id or "UNKNOWN"),
                symbol=symbol,
                elapsed_ms=round(
                    max(0.0, time.monotonic() - snapshot_started) * 1000.0,
                    3,
                ),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise
        NETWORK_STARTUP.emit(
            "snapshot_fetch_exit",
            scan_id=str(scan_id or "UNKNOWN"),
            symbol=symbol,
            elapsed_ms=round(
                max(0.0, time.monotonic() - snapshot_started) * 1000.0,
                3,
            ),
        )
        STAGE_BOUNDARY.emit("snapshot_done", scan_id=scan_id, symbol=symbol)
        analyses = {}
        frames = {}
        for tf in timeframes:
            STAGE_BOUNDARY.emit("frame_fetch_enter", scan_id=scan_id, symbol=symbol, timeframe=tf)
            df = self._frame(symbol, tf, scan_id=scan_id)
            frames[tf] = df
            STAGE_BOUNDARY.emit("frame_fetch_exit", scan_id=scan_id, symbol=symbol, timeframe=tf)
            STAGE_BOUNDARY.emit("indicator_enter", scan_id=scan_id, symbol=symbol, timeframe=tf)
            with FRAME_OWNERSHIP.operation(
                df, scan_id=scan_id, symbol=symbol,
                timeframe=tf, engine="IndicatorEngine.analyze",
            ):
                analyses[tf] = self.indicator.analyze(df, tf)
            STAGE_BOUNDARY.emit("timeframe_done", scan_id=scan_id, symbol=symbol, timeframe=tf)

        STAGE_BOUNDARY.emit("all_timeframes_done", scan_id=scan_id, symbol=symbol, timeframes=tuple(timeframes))
        if "15m" not in analyses or "15m" not in frames:
            raise ValueError(
                f"{symbol}: Footprint yêu cầu dữ liệu khung 15m"
            )

        STAGE_BOUNDARY.emit("structure_enter", scan_id=scan_id, symbol=symbol)
        structure = self.structure.analyze(frames)
        STAGE_BOUNDARY.emit("structure_exit", scan_id=scan_id, symbol=symbol)
        STAGE_BOUNDARY.emit("regime_enter", scan_id=scan_id, symbol=symbol)
        regime = self.regime.analyze(analyses)
        STAGE_BOUNDARY.emit("regime_exit", scan_id=scan_id, symbol=symbol)
        STAGE_BOUNDARY.emit("alignment_enter", scan_id=scan_id, symbol=symbol)
        alignment = self.alignment.analyze(analyses)
        STAGE_BOUNDARY.emit("alignment_exit", scan_id=scan_id, symbol=symbol)
        STAGE_BOUNDARY.emit("smart_entry_enter", scan_id=scan_id, symbol=symbol)
        smart_entry = self.smart_entry.analyze(
            frames,
            analyses,
            snap,
            structure,
            alignment,
            regime,
        )
        STAGE_BOUNDARY.emit("smart_entry_exit", scan_id=scan_id, symbol=symbol)
        STAGE_BOUNDARY.emit("decision_combine_enter", scan_id=scan_id, symbol=symbol)
        analysis = self.decision.combine(
            symbol,
            snap,
            analyses,
            structure,
            regime,
            alignment,
            smart_entry,
        )
        STAGE_BOUNDARY.emit("decision_combine_exit", scan_id=scan_id, symbol=symbol)
        STAGE_BOUNDARY.emit("context_build_enter", scan_id=scan_id, symbol=symbol)
        footprint_context = {
            "_native2_scan_id": str(scan_id or "UNKNOWN"),
            "_native2_symbol": symbol,
            "_native2_timeframe": "15m",
            "liquidity_event": structure.liquidity_event,
            "wyckoff_signal": structure.wyckoff_signal,
            "wyckoff_test": getattr(structure, "wyckoff_test", ""),
            "support": getattr(structure, "support", None),
            "resistance": getattr(structure, "resistance", None),
            "oi_change_15m_pct": getattr(
                snap, "oi_change_15m_pct", 0.0
            ),
            "funding_pct": getattr(snap, "funding_pct", 0.0),
            "price_change_pct": getattr(
                analyses["15m"], "price_change_pct", 0.0
            ),
            "delta_ratio": getattr(snap, "delta_ratio", 0.0),
            "cvd_slope": getattr(snap, "cvd_slope", 0.0),
            "liquidation_impulse": getattr(
                snap, "liquidation_impulse", 0.0
            ),
            "absorption_score": getattr(
                smart_entry,
                "absorption_score",
                getattr(
                    getattr(analysis, "microstructure", None),
                    "absorption_score",
                    0.0,
                ),
            ),
            "lifecycle_stage": getattr(
                structure,
                "lifecycle_stage",
                getattr(analysis, "trend_lifecycle", "UNKNOWN"),
            ),
            "oi_change_series": tuple(
                getattr(snap, "oi_change_history", ()) or ()
            ),
            "delta_ratio_series": tuple(
                getattr(snap, "delta_ratio_history", ()) or ()
            ),
        }
        STAGE_BOUNDARY.emit("context_build_exit", scan_id=scan_id, symbol=symbol)
        STAGE_BOUNDARY.emit("footprint_enter", scan_id=scan_id, symbol=symbol)
        with FRAME_OWNERSHIP.operation(
            frames["15m"], scan_id=scan_id, symbol=symbol,
            timeframe="15m", engine="FootprintOrchestrator.scan_coin",
        ):
            footprint_result = self.footprint_orchestrator.analyze(
                frames["15m"],
                footprint_context,
                expected_direction=analysis.direction,
            )
        STAGE_BOUNDARY.emit("footprint_exit", scan_id=scan_id, symbol=symbol)
        STAGE_BOUNDARY.emit("reliability_apply_enter", scan_id=scan_id, symbol=symbol)
        analysis = self._apply_footprint_with_reliability(
            analysis, footprint_result["composite"],
        )
        STAGE_BOUNDARY.emit("reliability_apply_exit", scan_id=scan_id, symbol=symbol)
        STAGE_BOUNDARY.emit("result_build_enter", scan_id=scan_id, symbol=symbol)
        result = self._attach_explainable_narrative(self._attach_composite_exhaustion(analysis))
        STAGE_BOUNDARY.emit("result_build_exit", scan_id=scan_id, symbol=symbol)
        STAGE_BOUNDARY.emit("scan_coin_return", scan_id=scan_id, symbol=symbol)
        return result


    def refresh_universe(
        self,
        universe_size: int,
        min_quote_volume: float,
    ) -> list[str]:
        self.universe_cache = self.provider.discover_usdt_perpetuals(
            limit=universe_size,
            min_quote_volume=min_quote_volume,
        )
        if self.universe_cursor >= len(self.universe_cache):
            self.universe_cursor = 0
        return list(self.universe_cache)


    def deep_scan_batch(
        self,
        universe: list[str],
        deep_scan_size: int,
        pinned: list[str] | tuple[str, ...] = (),
    ) -> list[str]:
        # PRODUCT-02B-r2: liquidity admission owns eligibility.
        btc = "BTC/USDT:USDT"
        batch_size = max(1, int(deep_scan_size))
        if not universe:
            return [btc][:batch_size]

        unique = list(dict.fromkeys(universe))
        pinned_clean = list(dict.fromkeys(pinned))
        admitted_set = set(unique)
        admitted_pinned_non_btc = [
            symbol for symbol in pinned_clean
            if symbol != btc and symbol in admitted_set
        ]
        pinned_quota_total = min(
            1 + len(admitted_pinned_non_btc),
            max(1, batch_size // 3),
        )
        pinned_room = max(0, pinned_quota_total - 1)

        fixed = [btc]
        if admitted_pinned_non_btc and pinned_room:
            pinned_start = self.pinned_cursor % len(admitted_pinned_non_btc)
            selected_pins = min(pinned_room, len(admitted_pinned_non_btc))
            for offset in range(selected_pins):
                fixed.append(admitted_pinned_non_btc[(pinned_start + offset) % len(admitted_pinned_non_btc)])
            self.pinned_cursor = (pinned_start + selected_pins) % len(admitted_pinned_non_btc)

        room = batch_size - len(fixed)
        candidates = [symbol for symbol in unique if symbol not in fixed]
        if room <= 0 or not candidates:
            return fixed[:batch_size]

        start = self.universe_cursor % len(candidates)
        rotating = []
        for offset in range(min(room, len(candidates))):
            rotating.append(candidates[(start + offset) % len(candidates)])
        self.universe_cursor = (start + len(rotating)) % len(candidates)
        return fixed + rotating



    @staticmethod
    def build_market_brief(
        results: dict[str, CoinAnalysis],
    ) -> MarketBrief:
        btc = results.get("BTC/USDT:USDT")
        alts = [
            value
            for symbol, value in results.items()
            if symbol != "BTC/USDT:USDT"
        ]
        if not btc:
            return MarketBrief(
                "UNKNOWN", 0.0, "TRUNG TÍNH", "CAO",
                "Chưa có dữ liệu BTC.",
                "NEUTRAL", 0.0,
            )

        long_count = sum(x.direction == "LONG" for x in alts)
        short_count = sum(x.direction == "SHORT" for x in alts)
        neutral_count = max(0, len(alts)-long_count-short_count)
        directional_count = long_count+short_count
        breadth = (
            100.0*long_count/directional_count
            if directional_count > 0
            else 50.0
        )
        btc_bias = btc.direction

        if btc_bias == "LONG" and breadth >= 65:
            code = "STRONG_LONG"
            label = "ƯU TIÊN LONG MẠNH"
            risk = "THẤP/TRUNG BÌNH"
            strength = min(100.0, 65.0 + (breadth-65.0))
        elif btc_bias == "LONG" and breadth >= 55:
            code = "LONG"
            label = "ƯU TIÊN LONG"
            risk = "TRUNG BÌNH"
            strength = breadth
        elif btc_bias == "SHORT" and breadth <= 35:
            code = "STRONG_SHORT"
            label = "ƯU TIÊN SHORT MẠNH"
            risk = "TRUNG BÌNH/CAO"
            strength = min(100.0, 65.0 + (35.0-breadth))
        elif btc_bias == "SHORT" and breadth <= 45:
            code = "SHORT"
            label = "ƯU TIÊN SHORT"
            risk = "TRUNG BÌNH/CAO"
            strength = 100.0-breadth
        else:
            code = "NEUTRAL"
            label = "ĐỨNG NGOÀI/CHỌN LỌC"
            risk = "TRUNG BÌNH"
            strength = abs(breadth-50.0)*2.0

        summary = (
            f"BTC nghiêng {btc_bias}, {breadth:.0f}% alt có hướng "
            f"nghiêng Long ({long_count} Long/{short_count} Short/"
            f"{neutral_count} Neutral). Market Bias: {label}."
        )
        return MarketBrief(
            btc_bias, breadth, label, risk, summary,
            code, strength,
        )

    @staticmethod
    def _countertrend_confirmed(
        analysis: CoinAnalysis,
        bias_code: str,
    ) -> bool:
        r15 = analysis.timeframes["15m"]
        structure = analysis.structure
        event = str(structure.liquidity_event).lower()
        wyckoff = str(structure.wyckoff_signal).lower()
        test = str(getattr(structure, "wyckoff_test", "")).upper()

        if bias_code in ("STRONG_LONG", "LONG"):
            return (
                analysis.direction == "SHORT"
                and ("upthrust" in wyckoff or "quét đỉnh" in event)
                and (
                    "TEST AFTER UPTHRUST" in test
                    or "breakdown xác nhận" in event
                )
                and r15.cmf < 0
                and r15.close < r15.ema20
            )

        if bias_code in ("STRONG_SHORT", "SHORT"):
            return (
                analysis.direction == "LONG"
                and ("spring" in wyckoff or "quét đáy" in event)
                and (
                    "TEST AFTER SPRING" in test
                    or "breakout xác nhận" in event
                )
                and r15.cmf > 0
                and r15.close > r15.ema20
            )
        return False

    @classmethod
    def apply_market_bias_gate(
        cls,
        analysis: CoinAnalysis,
        brief: MarketBrief,
    ) -> CoinAnalysis:
        code = brief.bias_code
        opposing = (
            code in ("STRONG_LONG", "LONG")
            and analysis.direction == "SHORT"
        ) or (
            code in ("STRONG_SHORT", "SHORT")
            and analysis.direction == "LONG"
        )

        if not opposing or code == "NEUTRAL":
            return replace(
                analysis,
                market_bias_code=code,
                market_bias_gate="PASS",
            )

        confirmed = cls._countertrend_confirmed(
            analysis,
            code,
        )
        reasons = list(analysis.reasons)

        if confirmed:
            # Counter-trend trades remain research setups, never fresh MAIN READY.
            status = (
                EntryStatus.SETUP
                if analysis.entry_status == EntryStatus.READY
                else analysis.entry_status
            )
            confidence = min(analysis.confidence_score, 62.0)
            reasons.append(
                f"Market Bias {code}: counter-trend được xác nhận cấu trúc; "
                "chỉ giữ ở SETUP/Shadow."
            )
            return replace(
                analysis,
                entry_status=status,
                confidence_score=confidence,
                action=(
                    f"CHUẨN BỊ {analysis.direction}"
                    if status == EntryStatus.SETUP
                    else analysis.action
                ),
                reasons=tuple(reasons),
                market_bias_code=code,
                market_bias_gate="COUNTERTREND_CONFIRMED",
            )

        if code.startswith("STRONG_"):
            reasons.append(
                f"Market Bias {code}: chặn hướng {analysis.direction} "
                "do chưa có xác nhận đảo chiều cấu trúc."
            )
            return replace(
                analysis,
                entry_status=EntryStatus.WAIT,
                confidence_score=min(
                    analysis.confidence_score,
                    49.0,
                ),
                action="ĐỨNG NGOÀI",
                timing="Chờ market bias trung tính hoặc đảo chiều được xác nhận.",
                reasons=tuple(reasons),
                market_bias_code=code,
                market_bias_gate="BLOCK_OPPOSING_STRONG",
            )

        status = (
            EntryStatus.SETUP
            if analysis.entry_status == EntryStatus.READY
            else analysis.entry_status
        )
        reasons.append(
            f"Market Bias {code}: hạ cấp hướng đối nghịch xuống SETUP."
        )
        return replace(
            analysis,
            entry_status=status,
            confidence_score=min(
                analysis.confidence_score,
                59.0,
            ),
            action=(
                f"CHUẨN BỊ {analysis.direction}"
                if status == EntryStatus.SETUP
                else analysis.action
            ),
            reasons=tuple(reasons),
            market_bias_code=code,
            market_bias_gate="DOWNGRADE_OPPOSING",
        )


    @staticmethod
    def calibrate_context_confidence(
        analysis: CoinAnalysis,
        brief: MarketBrief,
        max_boost: float = 5.0,
    ) -> CoinAnalysis:
        """Apply only a small evidence-backed recovery after hard gates."""
        base = float(analysis.confidence_score)
        reasons = list(analysis.reasons)

        aligned_bias = (
            brief.bias_code in ("STRONG_LONG", "LONG")
            and analysis.direction == "LONG"
        ) or (
            brief.bias_code in ("STRONG_SHORT", "SHORT")
            and analysis.direction == "SHORT"
        ) or brief.bias_code == "NEUTRAL"

        hard_safe = (
            analysis.entry_status
            not in (EntryStatus.WAIT, EntryStatus.RUNNING)
            and analysis.direction_confirmation_gate == "CONFIRMED"
            and analysis.market_bias_gate
            not in ("BLOCK_OPPOSING_STRONG", "DOWNGRADE_OPPOSING")
            and aligned_bias
            and analysis.risk.liquidation_safe
            and analysis.trend_lifecycle in (
                "EARLY_FORMATION",
                "FIRST_RETEST",
                "CONFIRMED_TREND",
            )
            and analysis.maturity_gate not in ("LATE", "EXHAUSTION")
        )

        adjustment = 0.0
        calibrated = base
        if hard_safe:
            entry = (
                analysis.long_entry_score
                if analysis.direction == "LONG"
                else analysis.short_entry_score
            )
            trend = (
                analysis.long_trend_score
                if analysis.direction == "LONG"
                else analysis.short_trend_score
            )
            evidence_target = (
                0.24 * trend
                + 0.24 * entry
                + 0.20 * analysis.direction_confirmation_score
                + 0.14 * analysis.smart_entry.smart_money_probability
                + 0.10 * max(0.0, 100.0-analysis.risk.risk_score)
                + 0.08 * min(
                    100.0,
                    analysis.trade_plan.rr_to_tp2 * 35.0,
                )
            )
            calibrated = max(
                base,
                min(base + max(0.0, float(max_boost)), evidence_target),
            )
            adjustment = calibrated - base
            if adjustment >= 0.25:
                reasons.append(
                    f"Confidence Calibration: +{adjustment:.1f} "
                    "nhờ các bằng chứng độc lập cùng xác nhận."
                )

        return replace(
            analysis,
            confidence_score=max(0.0, min(100.0, calibrated)),
            confidence_before_context=base,
            confidence_context_adjustment=adjustment,
            reasons=tuple(reasons),
        )


    def annotate_calibrated_probabilities(
        self,
        analyses: dict[str, CoinAnalysis],
    ) -> dict[str, CoinAnalysis]:
        """Attach validated PAPER probability without changing confidence gates."""
        output: dict[str, CoinAnalysis] = {}
        self.probability_calibrator.fit(force=True)
        drift = self.calibration_drift_monitor.evaluate(force=True)
        for symbol, analysis in analyses.items():
            probability, model = self.probability_calibrator.calibrate(
                analysis.confidence_score
            )
            reasons = list(analysis.reasons)
            if model.validated:
                reasons.append(
                    f"PAPER calibrated probability: {probability:.1f}% "
                    f"({model.samples} determinate closed trades)."
                )
            adaptive = self.adaptive_confidence_service.adapt(
                base_probability=probability,
                raw_confidence=analysis.confidence_score,
                direction=analysis.direction,
                regime=getattr(analysis.regime, "regime", "UNKNOWN"),
                calibrator=self.probability_calibrator,
            )
            if adaptive.state == "VALIDATED" and abs(adaptive.adjustment) >= 0.25:
                reasons.append(
                    f"Adaptive PAPER probability: {adaptive.probability:.1f}% "
                    f"({adaptive.context_key}, {adaptive.samples} samples)."
                )
            if drift.state in {"WATCH", "DRIFT"}:
                reasons.append(
                    f"Calibration drift monitor: {drift.state} "
                    f"(Brier Δ {drift.recent_brier - drift.reference_brier:+.3f}, "
                    f"ECE Δ {drift.recent_ece - drift.reference_ece:+.3f}, "
                    f"PSI {drift.confidence_psi:.3f})."
                )
            reliability = self.evidence_reliability_service.evaluate(
                symbol=getattr(analysis, "symbol", "UNKNOWN"),
                direction=getattr(analysis, "direction", "UNKNOWN"),
                regime=getattr(getattr(analysis, "regime", None), "regime", "UNKNOWN"),
            )
            reliability_summary = tuple(
                f"{family}:{item.state}:{item.reliability:.1f}%:{item.effective_samples:.1f}"
                for family, item in reliability.items()
            )
            states = {item.state for item in reliability.values()}
            reliability_state = (
                "VALIDATED" if states == {"VALIDATED"}
                else "PARTIAL" if states & {"VALIDATED", "SHRUNK"}
                else "UNKNOWN"
            )
            if reliability_state != "UNKNOWN":
                reasons.append(
                    "Evidence reliability (observe-only): "
                    + ", ".join(reliability_summary)
                )
            output[symbol] = replace(
                analysis,
                calibrated_probability=probability,
                probability_calibration_state=model.state,
                probability_calibration_samples=model.samples,
                probability_calibration_method=(
                    "BAYES_BIN_PAV_CHRONO_HOLDOUT"
                    if model.validated else "OBSERVE_ONLY"
                ),
                adaptive_probability=adaptive.probability,
                adaptive_confidence_state=adaptive.state,
                adaptive_confidence_adjustment=adaptive.adjustment,
                adaptive_confidence_samples=adaptive.samples,
                adaptive_confidence_context=adaptive.context_key,
                calibration_drift_state=drift.state,
                calibration_drift_samples=drift.samples,
                calibration_drift_brier_delta=drift.recent_brier - drift.reference_brier,
                calibration_drift_ece_delta=drift.recent_ece - drift.reference_ece,
                calibration_drift_psi=drift.confidence_psi,
                evidence_reliability_state=reliability_state,
                evidence_reliability_summary=reliability_summary,
                evidence_reliability_method="TIME_DECAY_BAYES_HIERARCHICAL",
                reasons=tuple(reasons),
            )
        return output

    @staticmethod
    def _opportunity_breakdown(
        analysis: CoinAnalysis,
    ) -> dict[str, float | str]:
        entry = (
            analysis.long_entry_score
            if analysis.direction == "LONG"
            else analysis.short_entry_score
        )
        trend = (
            analysis.long_trend_score
            if analysis.direction == "LONG"
            else analysis.short_trend_score
        )
        rr_score = min(
            100.0,
            max(0.0, analysis.trade_plan.rr_to_tp2 * 35.0),
        )

        base = (
            0.24 * analysis.confidence_score
            + 0.19 * entry
            + 0.15 * trend
            + 0.16 * analysis.direction_confirmation_score
            + 0.10 * analysis.smart_entry.smart_money_probability
            + 0.10 * max(0.0, 100.0-analysis.risk.risk_score)
            + 0.06 * rr_score
        )

        bonuses: list[tuple[str, float]] = []
        if analysis.entry_status == EntryStatus.READY:
            bonuses.append(("READY", 5.0))
        elif analysis.entry_status == EntryStatus.SETUP:
            bonuses.append(("SETUP", 2.0))
        if analysis.market_bias_gate == "PASS":
            bonuses.append(("MARKET_BIAS_PASS", 3.0))
        bonus = sum(value for _, value in bonuses)

        # Correlated decision failures must not be stacked. WAIT is often the
        # downstream consequence of the other gates, not an independent
        # negative observation.
        penalties: list[tuple[str, float]] = []
        if analysis.entry_status in (
            EntryStatus.WAIT,
            EntryStatus.RUNNING,
        ):
            penalties.append(("ENTRY_STATUS_WAIT", 25.0))
        if analysis.market_bias_gate.startswith("BLOCK"):
            penalties.append(("MARKET_BIAS_BLOCK", 25.0))
        if analysis.direction_confirmation_gate == "BLOCK":
            penalties.append(("DIRECTION_BLOCK", 25.0))
        elif analysis.direction_confirmation_gate == "WATCH":
            penalties.append(("DIRECTION_WATCH", 6.0))
        if analysis.maturity_gate in ("LATE", "EXHAUSTION"):
            penalties.append(("MATURITY_LATE", 20.0))

        penalty_reason, penalty = max(
            penalties,
            key=lambda item: item[1],
            default=("NONE", 0.0),
        )
        final = max(0.0, min(100.0, base+bonus-penalty))

        return {
            "base": float(base),
            "bonus": float(bonus),
            "penalty": float(penalty),
            "penalty_reason": penalty_reason,
            "final": float(final),
        }

    @classmethod
    def _opportunity_score(cls, analysis: CoinAnalysis) -> float:
        return float(cls._opportunity_breakdown(analysis)["final"])


    @classmethod
    def rank_opportunities(
        cls,
        results: dict[str, CoinAnalysis],
        minimum_score: float = 52.0,
    ) -> dict[str, CoinAnalysis]:
        ranked = dict(results)
        for direction in ("LONG", "SHORT"):
            candidates = [
                analysis
                for analysis in ranked.values()
                if analysis.symbol != "BTC/USDT:USDT"
                and analysis.direction == direction
            ]
            candidates.sort(
                key=cls._opportunity_score,
                reverse=True,
            )
            candidate_count = len(candidates)

            for rank, analysis in enumerate(candidates, start=1):
                breakdown = cls._opportunity_breakdown(analysis)
                score = float(breakdown["final"])
                percentile = (
                    100.0
                    if candidate_count <= 1
                    else 100.0 * (
                        candidate_count-rank
                    ) / (candidate_count-1)
                )
                gate = (
                    "RANKED"
                    if score >= minimum_score
                    else "LOW_QUALITY"
                )
                reasons = list(getattr(analysis, "reasons", ()))
                reasons.append(
                    f"Opportunity Ranking: #{rank} {direction} · "
                    f"{score:.1f}/100 · P{percentile:.0f} · {gate}"
                )
                reasons.append(
                    "Opportunity Breakdown: "
                    f"base {float(breakdown['base']):.1f} "
                    f"+ bonus {float(breakdown['bonus']):.1f} "
                    f"- penalty {float(breakdown['penalty']):.1f} "
                    f"({breakdown['penalty_reason']})."
                )

                ranked[analysis.symbol] = replace(
                    analysis,
                    opportunity_score=score,
                    opportunity_rank=rank,
                    opportunity_gate=gate,
                    opportunity_base_score=float(
                        breakdown["base"]
                    ),
                    opportunity_bonus=float(
                        breakdown["bonus"]
                    ),
                    opportunity_penalty=float(
                        breakdown["penalty"]
                    ),
                    opportunity_penalty_reason=str(
                        breakdown["penalty_reason"]
                    ),
                    opportunity_percentile=percentile,
                    reasons=tuple(reasons),
                )
        return ranked



    def hydrate_microstructure(
        self,
        results: dict[str, CoinAnalysis],
        max_symbols: int = 8,
    ) -> dict[str, CoinAnalysis]:
        return self.microstructure.hydrate_ranked(
            results,
            max_symbols=max_symbols,
        )




    def _attach_composite_exhaustion(self, analysis):
        """Attach observe-only exhaustion data without breaking legacy mocks."""
        if not is_dataclass(analysis):
            return analysis
        try:
            exhaustion = self.composite_exhaustion_engine.evaluate(analysis)
            return replace(
                analysis,
                composite_exhaustion=exhaustion,
                composite_distribution_progress=exhaustion.distribution_progress,
                composite_selling_pressure=exhaustion.selling_pressure,
                composite_exhaustion_score=exhaustion.exhaustion_score,
                bottom_formation_probability=exhaustion.bottom_formation_probability,
                bottom_formation_state=exhaustion.bottom_state,
                composite_timeline=exhaustion.timeline,
            )
        except Exception as exc:
            log.warning("Composite exhaustion unavailable %s: %s", getattr(analysis, "symbol", "UNKNOWN"), exc)
            return analysis

    def _attach_explainable_narrative(self, analysis):
        """Attach observe-only narrative without changing any decision field."""
        if not is_dataclass(analysis):
            return analysis
        try:
            narrative = self.explainable_narrative_engine.evaluate(analysis)
            return replace(
                analysis,
                explainable_narrative=narrative,
                explainable_headline=narrative.headline,
                explainable_blockers=narrative.decision_blockers,
                explainable_next_confirmation=narrative.next_confirmation,
            )
        except Exception as exc:
            log.warning("Explainable narrative unavailable %s: %s", getattr(analysis, "symbol", "UNKNOWN"), exc)
            return analysis

    def _fusion_reliability(self, analysis: CoinAnalysis) -> dict[str, object]:
        try:
            return self.evidence_reliability_service.evaluate(
                symbol=getattr(analysis, "symbol", "UNKNOWN"),
                direction=getattr(analysis, "direction", "UNKNOWN"),
                regime=getattr(getattr(analysis, "regime", None), "regime", "UNKNOWN"),
            )
        except Exception as exc:
            log.warning("Evidence reliability unavailable %s: %s", getattr(analysis, "symbol", "UNKNOWN"), exc)
            return {}

    def _apply_footprint_with_reliability(self, analysis, footprint):
        reliability = self._fusion_reliability(analysis)
        try:
            return self.decision.apply_footprint_v31(
                analysis, footprint, reliability_by_family=reliability,
            )
        except TypeError as exc:
            if "reliability_by_family" not in str(exc):
                raise
            return self.decision.apply_footprint_v31(analysis, footprint)

    def refresh_position_footprint(
        self,
        results: dict[str, CoinAnalysis],
        scan_id: str = "UNKNOWN",
    ) -> dict[str, CoinAnalysis]:
        """Recompute top-N Footprint using hydrated microstructure evidence.

        The initial universe scan intentionally uses cheap snapshot data. After
        hydration, this second pass wires real Delta/CVD proxy, liquidation,
        absorption and rolling persistence into Position Building.
        """
        refreshed = dict(results)
        for symbol, analysis in results.items():
            if analysis.microstructure is None:
                continue
            try:
                frame_15m = self._frame(symbol, "15m", scan_id=scan_id)
                context = {
                    "_native2_scan_id": str(scan_id or "UNKNOWN"),
                    "_native2_symbol": symbol,
                    "_native2_timeframe": "15m",
                    "liquidity_event": analysis.structure.liquidity_event,
                    "wyckoff_signal": analysis.structure.wyckoff_signal,
                    "wyckoff_test": getattr(analysis.structure, "wyckoff_test", ""),
                    "support": getattr(analysis.structure, "support", None),
                    "resistance": getattr(analysis.structure, "resistance", None),
                    "oi_change_15m_pct": analysis.snapshot.oi_change_15m_pct,
                    "funding_pct": analysis.snapshot.funding_pct,
                    "price_change_pct": analysis.timeframes["15m"].price_change_pct,
                    "lifecycle_stage": getattr(
                        analysis.structure, "lifecycle_stage",
                        analysis.trend_lifecycle,
                    ),
                }
                context.update(self.microstructure.position_context(analysis))
                with FRAME_OWNERSHIP.operation(
                    frame_15m, scan_id=scan_id, symbol=symbol,
                    timeframe="15m", engine="FootprintOrchestrator.refresh",
                ):
                    footprint = self.footprint_orchestrator.analyze(
                        frame_15m, context, expected_direction=analysis.direction,
                    )["composite"]
                updated = self._apply_footprint_with_reliability(
                    analysis, footprint,
                )
                refreshed[symbol] = self._attach_explainable_narrative(self._attach_composite_exhaustion(updated))
            except Exception as exc:
                log.warning(
                    "Position footprint refresh unavailable %s: %s",
                    symbol, exc,
                )
        return refreshed

    def apply_microstructure_adjustments(
        self,
        results: dict[str, CoinAnalysis],
        weight: float,
        confirm_bonus: float,
        conflict_penalty: float,
    ) -> dict[str, CoinAnalysis]:
        adjusted = dict(results)
        for symbol, analysis in results.items():
            if analysis.microstructure is None:
                continue
            adjusted[symbol] = (
                self.microstructure.apply_decision_adjustment(
                    analysis,
                    weight=weight,
                    confirm_bonus=confirm_bonus,
                    conflict_penalty=conflict_penalty,
                )
            )
        return adjusted
