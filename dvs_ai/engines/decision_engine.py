from __future__ import annotations
from datetime import datetime
from dataclasses import replace
import logging
from dvs_ai.engines.risk_engine import RiskEngine
from dvs_ai.engines.reasoning_engine import SmartMoneyReasoningEngine
from dvs_ai.engines.footprint_graph_engine import FootprintGraphEngine
from dvs_ai.engines.evidence_fusion_engine import EvidenceFusionEngine, EvidenceSignal
from dvs_ai.domain.models import (
    CoinAnalysis, EntryStatus, MarketSnapshot, TimeframeAnalysis, TradePlan,
    StructureAnalysis, RegimeAnalysis, AlignmentAnalysis, SmartEntryAnalysis
)

logger = logging.getLogger(__name__)


class DecisionEngine:
    def __init__(self, config=None):
        self.config = config
        self.risk_engine = RiskEngine(config)
        self.reasoning_engine = SmartMoneyReasoningEngine()
        self.footprint_graph_engine = FootprintGraphEngine()
        self.evidence_fusion_engine = EvidenceFusionEngine(
            family_weights=getattr(config, "evidence_fusion_family_weights", None),
            source_multipliers=getattr(config, "evidence_fusion_source_multipliers", None),
            contradiction_penalty=getattr(config, "evidence_fusion_contradiction_penalty", 14.0),
            contradiction_cap=getattr(config, "evidence_fusion_contradiction_cap", 68.0),
        )

    WEIGHTS = {"15m": .40, "1h": .35, "4h": .17, "1d": .08}

    @staticmethod
    def classify_oi(price_change: float, oi_change: float) -> str:
        if abs(price_change) < .05 or abs(oi_change) < .10:
            return "OI trung tính"
        if price_change > 0 and oi_change > 0: return "Long build-up"
        if price_change < 0 and oi_change > 0: return "Short build-up"
        if price_change > 0 and oi_change < 0: return "Short covering"
        return "Long unwinding"


    def combine(
        self, symbol: str, snap: MarketSnapshot,
        tf: dict[str, TimeframeAnalysis], structure: StructureAnalysis,
        regime: RegimeAnalysis, alignment: AlignmentAnalysis,
        smart_entry: SmartEntryAnalysis
    ) -> CoinAnalysis:
        lt = sum(
            tf[k].long_trend_score * self.WEIGHTS[k]
            for k in self.WEIGHTS
        )
        st = sum(
            tf[k].short_trend_score * self.WEIGHTS[k]
            for k in self.WEIGHTS
        )
        le = sum(
            tf[k].long_entry_score * self.WEIGHTS[k]
            for k in self.WEIGHTS
        )
        se = sum(
            tf[k].short_entry_score * self.WEIGHTS[k]
            for k in self.WEIGHTS
        )

        oi_state = self.classify_oi(
            tf["15m"].price_change_pct,
            snap.oi_change_15m_pct,
        )
        if oi_state == "Long build-up":
            lt += 7
            le += 8
        elif oi_state == "Short build-up":
            st += 7
            se += 8
        elif oi_state == "Short covering":
            le += 3
        elif oi_state == "Long unwinding":
            se += 3

        # 15m + 1h money-flow confirmation.
        if tf["15m"].cmf > 0 and tf["1h"].cmf > 0:
            le += 8
        if tf["15m"].cmf < 0 and tf["1h"].cmf < 0:
            se += 8

        # Smooth enough to discourage crowded direction before RiskEngine.
        if snap.funding_pct > 0.06:
            le -= min(10.0, 8.0 + (snap.funding_pct - 0.06) * 20.0)
        if snap.funding_pct < -0.06:
            se -= min(10.0, 8.0 + (abs(snap.funding_pct) - 0.06) * 20.0)

        event = structure.liquidity_event.lower()
        wyckoff = structure.wyckoff_signal.lower()
        sweep_state = getattr(structure, "sweep_volume_state", "NONE")

        spring_confirmed = (
            ("quét đáy" in event or "spring" in wyckoff)
            and sweep_state != "UNCONFIRMED"
        )
        upthrust_confirmed = (
            ("quét đỉnh" in event or "upthrust" in wyckoff)
            and sweep_state != "UNCONFIRMED"
        )
        if spring_confirmed:
            le += 12
            lt += 5
        elif "quét đáy" in event:
            le += 3

        if upthrust_confirmed:
            se += 12
            st += 5
        elif "quét đỉnh" in event:
            se += 3

        if "breakout xác nhận" in event:
            le += 6
        if "breakdown xác nhận" in event:
            se += 6
        if "tránh đuổi" in " ".join(structure.warnings).lower():
            le -= 5
            se -= 5

        # MTF alignment is a major source of confidence.
        if alignment.label == "ĐỒNG PHA LONG":
            lt += 12
            le += 14
        elif alignment.label == "ĐỒNG PHA SHORT":
            st += 12
            se += 14
        elif alignment.label == "MÂU THUẪN":
            le -= 14
            se -= 14
            lt -= 5
            st -= 5
        elif "NGHIÊNG" in alignment.label:
            le -= 6
            se -= 6

        # Regime is a gate, not just a small decoration.
        if regime.direction == "LONG":
            lt += 8
            le += 5
        elif regime.direction == "SHORT":
            st += 8
            se += 5

        if regime.regime in ("RANGE", "TRANSITION"):
            le -= 7
            se -= 7
        elif regime.strength < 45:
            le -= 5
            se -= 5

        if smart_entry.long_opportunity_index >= 65:
            le += min(
                16.0,
                (smart_entry.long_opportunity_index - 60.0) * 0.4,
            )
        if smart_entry.short_opportunity_index >= 65:
            se += min(
                16.0,
                (smart_entry.short_opportunity_index - 60.0) * 0.4,
            )
        # SmartEntry state is derived from LOI/SOI and cannot cast a
        # second positive vote under another name.

        lt, st, le, se = [
            max(0.0, min(100.0, x))
            for x in (lt, st, le, se)
        ]

        long_case = (lt + le) >= (st + se)
        direction = "LONG" if long_case else "SHORT"
        trend, entry = (lt, le) if long_case else (st, se)
        maturity_15m = (
            tf["15m"].long_trend_maturity
            if direction == "LONG"
            else tf["15m"].short_trend_maturity
        )
        maturity_1h = (
            tf["1h"].long_trend_maturity
            if direction == "LONG"
            else tf["1h"].short_trend_maturity
        )
        lifecycle_15m = (
            tf["15m"].long_trend_lifecycle
            if direction == "LONG"
            else tf["15m"].short_trend_lifecycle
        )
        lifecycle_1h = (
            tf["1h"].long_trend_lifecycle
            if direction == "LONG"
            else tf["1h"].short_trend_lifecycle
        )
        avg_maturity = (
            0.65 * maturity_15m
            + 0.35 * maturity_1h
        )
        maturity_gate = self._maturity_gate(avg_maturity)
        lifecycle = self._combined_lifecycle(
            avg_maturity,
            lifecycle_15m,
            lifecycle_1h,
        )
        status = self._entry_status(
            trend=trend,
            entry=entry,
            r15=tf["15m"],
            direction=direction,
            maturity=avg_maturity,
            lifecycle=lifecycle,
            maturity_gate=maturity_gate,
        )

        quality_gate = "PENDING"

        if direction == "LONG":
            directional_agreement = max(0.0, lt - st)
            directional_conflict = max(0.0, st - lt)
        else:
            directional_agreement = max(0.0, st - lt)
            directional_conflict = max(0.0, lt - st)

        # More conservative and directional than the former 45/45 formula.
        confidence = (
            0.40 * trend
            + 0.40 * entry
            + 0.14 * directional_agreement
            - 0.14 * directional_conflict
        )
        # SMP reuses Smart Entry evidence. It can reduce confidence when
        # consensus is weak, but cannot add another positive vote.
        smp_modifier = (
            0.82
            + 0.18*max(
                0.0,
                min(100.0, smart_entry.smart_money_probability),
            )/100.0
        )
        confidence *= smp_modifier
        confidence = max(0.0, min(100.0, confidence))

        # Relative penalty + absolute cap. A very strong raw score must not
        # remain visually "high confidence" after the move is already late.
        if maturity_gate == "EXHAUSTION":
            confidence = min(
                confidence * 0.45,
                45.0,
            )
        elif avg_maturity > 78:
            confidence = min(
                confidence * 0.68,
                60.0,
            )
        elif maturity_gate == "LATE":
            confidence = min(
                confidence * 0.78,
                65.0,
            )
        elif 32 <= avg_maturity <= 55:
            confidence *= 1.14
        elif maturity_gate == "UNFORMED":
            confidence *= 0.82
        confidence = max(0.0, min(100.0, confidence))

        plan = self._trade_plan(
            direction, snap.last_price, tf["15m"]
        )
        risk = self.risk_engine.analyze(
            snap, tf, alignment, regime,
            direction, trade_plan=plan,
        )
        confidence = max(
            0.0,
            confidence - risk.risk_score * 0.22,
        )
        if not risk.liquidation_safe:
            confidence = min(confidence, 22.0)
            status = EntryStatus.WAIT

        # Hard conflict cannot become READY merely from one strong module.
        if (
            alignment.label == "MÂU THUẪN"
            or regime.regime == "TRANSITION"
        ) and status == EntryStatus.READY:
            status = EntryStatus.SETUP

        status, quality_gate = self._quality_gate(
            status=status,
            maturity=avg_maturity,
            maturity_gate=maturity_gate,
            lifecycle=lifecycle,
            extension=self._directional_extension(
                tf["15m"],
                direction,
            ),
        )

        (
            direction_confirmation_score,
            direction_confirmation_gate,
            direction_confirmation_reasons,
        ) = self._direction_confirmation(
            direction,
            tf,
            structure,
            regime,
            alignment,
            smart_entry,
        )

        if direction_confirmation_gate == "BLOCK":
            confidence = min(confidence, 49.0)
            status = EntryStatus.WAIT
        elif (
            direction_confirmation_gate == "WATCH"
            and status == EntryStatus.READY
        ):
            confidence = min(confidence, 64.0)
            status = EntryStatus.SETUP

        if (
            status == EntryStatus.READY
            and confidence >= 72
            and risk.risk_score < 55
        ):
            action = f"READY {direction}"
            timing = (
                "Chờ retest trong Entry Zone; "
                "không vào giữa nến mở rộng."
            )
        elif status == EntryStatus.SETUP and confidence >= 55:
            action = f"CHUẨN BỊ {direction}"
            timing = (
                "Chờ nến 15m xác nhận, MTF không xấu đi "
                "và OI/CMF không đảo chiều."
            )
        elif status == EntryStatus.RUNNING:
            action = "KHÔNG ĐUỔI GIÁ"
            timing = "Giá đã chạy xa vùng tối ưu; chờ cấu trúc mới."
        else:
            action = "ĐỨNG NGOÀI"
            timing = "Chưa đủ đồng thuận hoặc rủi ro cao."

        priority = self._priority(confidence, status)
        reasons = self._reasons(
            tf, snap, oi_state, direction, structure,
            regime, alignment, risk, smart_entry,
        )
        reasons.append(
            f"Trend Maturity: {avg_maturity:.1f}/100 · "
            f"{lifecycle} · Gate {maturity_gate}/{quality_gate}"
        )
        reasons.append(
            f"Direction Confirmation: "
            f"{direction_confirmation_score:.1f}/100 · "
            f"{direction_confirmation_gate}"
        )
        if direction_confirmation_reasons:
            reasons.append(
                "Direction evidence: "
                + ", ".join(direction_confirmation_reasons[:5])
            )
        reasons.append(
            f"Maturity 15m/1h: {maturity_15m:.1f}/"
            f"{maturity_1h:.1f}"
        )
        if avg_maturity > 68:
            reasons.append(
                "Xu hướng đã đi xa: không mở lệnh mới nếu thiếu "
                "pullback/retest chất lượng."
            )
        if plan.plan_repaired:
            reasons.append(
                f"Trade Plan Repaired: {plan.plan_repair_reason}"
            )

        return CoinAnalysis(
            symbol=symbol,
            snapshot=snap,
            timeframes=tf,
            long_trend_score=lt,
            short_trend_score=st,
            long_entry_score=le,
            short_entry_score=se,
            direction=direction,
            entry_status=status,
            priority_status=priority,
            oi_state=oi_state,
            phase_summary=(
                f"{tf['15m'].market_phase} / "
                f"{tf['1h'].market_phase}"
            ),
            confidence_score=confidence,
            reasons=tuple(reasons),
            trade_plan=plan,
            structure=structure,
            regime=regime,
            alignment=alignment,
            risk=risk,
            smart_entry=smart_entry,
            action=action,
            timing=timing,
            generated_at=datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            trend_maturity_score=avg_maturity,
            trend_lifecycle=lifecycle,
            maturity_15m=maturity_15m,
            maturity_1h=maturity_1h,
            maturity_gate=maturity_gate,
            direction_confirmation_score=direction_confirmation_score,
            direction_confirmation_gate=direction_confirmation_gate,
        )




    @staticmethod
    def _early_maturity_quality(maturity: float) -> float:
        maturity = max(0.0, min(100.0, float(maturity)))
        if maturity < 22:
            return maturity/22.0*45.0
        if maturity < 48:
            return 70.0+(maturity-22.0)/26.0*30.0
        if maturity < 68:
            return 100.0-(maturity-48.0)/20.0*25.0
        if maturity < 82:
            return 55.0-(maturity-68.0)/14.0*35.0
        return 5.0

    def apply_footprint_v31(
        self,
        analysis: CoinAnalysis,
        footprint,
        reliability_by_family: dict[str, object] | None = None,
    ) -> CoinAnalysis:
        reasons = list(analysis.reasons)
        status = analysis.entry_status
        direction = analysis.direction.upper()
        lifecycle = str(
            getattr(footprint, "lifecycle_stage", "UNKNOWN")
        ).upper()
        footprint_score = float(getattr(footprint, "score", 0.0))
        raw_score = float(
            getattr(footprint, "raw_score", footprint_score)
        )
        position_score = float(
            getattr(footprint, "position_building_score", 0.0)
        )
        position_regime = str(
            getattr(footprint, "position_building_regime", "UNKNOWN")
        )
        depth = str(
            getattr(footprint, "confirmation_depth", "NONE")
        )
        alignment = str(
            getattr(footprint, "direction_alignment", "NOT_APPLIED")
        )
        multiplier = float(
            getattr(footprint, "context_multiplier", 1.0)
        )
        position_meta = {}
        for component in getattr(footprint, "components", ()):
            metadata = getattr(component, "metadata", {}) or {}
            if metadata.get("regime") == position_regime:
                position_meta = metadata
                break
        persistence_score = float(position_meta.get("persistence_score", 0.0))
        acceleration_score = float(position_meta.get("acceleration_score", 0.0))
        position_confidence = float(position_meta.get("position_confidence", 0.0))

        hard_reasons: list[str] = []

        # Preserve every non-compensable gate already applied by combine().
        # apply_footprint_v31() runs later in the pipeline and must never
        # resurrect a blocked/extended setup merely because Footprint is high.
        if analysis.direction_confirmation_gate == "BLOCK":
            hard_reasons.append("DIRECTION_CONFIRMATION_BLOCK")
        if getattr(analysis.alignment, "label", "") == "MÂU THUẪN":
            hard_reasons.append("MTF_ALIGNMENT_CONFLICT")
        if getattr(analysis.regime, "regime", "") == "TRANSITION":
            hard_reasons.append("REGIME_TRANSITION")
        if analysis.maturity_gate == "EXHAUSTION":
            hard_reasons.append("MATURITY_EXHAUSTION")
        if analysis.entry_status == EntryStatus.RUNNING:
            hard_reasons.append("TREND_ALREADY_RUNNING_EXTENDED")

        if lifecycle in ("MARKUP", "MARKDOWN", "EXHAUSTION"):
            hard_reasons.append("LIFECYCLE_TOO_LATE")
        if footprint_score < 60.0:
            hard_reasons.append("FOOTPRINT_TOO_WEAK")
        if alignment == "CONFLICT":
            hard_reasons.append("FOOTPRINT_DIRECTION_CONFLICT")
        if position_score < 48.0:
            hard_reasons.append("POSITION_BUILDING_TOO_WEAK")
        if position_meta.get("oi_series_samples", 0) >= 3 and persistence_score < 35.0:
            hard_reasons.append("POSITION_PERSISTENCE_TOO_WEAK")
        if analysis.market_bias_gate.startswith("BLOCK"):
            hard_reasons.append("MARKET_BIAS_BLOCK")
        if not analysis.risk.liquidation_safe:
            hard_reasons.append("LIQUIDATION_UNSAFE")
        if analysis.trade_plan.rr_to_tp2 < 1.5:
            hard_reasons.append("RR_TOO_LOW")

        early_quality = self._early_maturity_quality(
            analysis.trend_maturity_score
        )
        smart_entry_score = (
            analysis.smart_entry.long_opportunity_index
            if direction == "LONG"
            else analysis.smart_entry.short_opportunity_index
        )
        structure_quality = max(
            0.0,
            min(100.0, analysis.direction_confirmation_score),
        )
        market_quality_map = {
            "PASS": 80.0,
            "COUNTERTREND_CONFIRMED": 65.0,
            "DOWNGRADE_OPPOSING": 40.0,
            "BLOCK_OPPOSING_STRONG": 25.0,
        }
        market_quality = market_quality_map.get(
            analysis.market_bias_gate,
            40.0,
        )
        # Evidence Fusion V2: correlated evidence is fused inside a family
        # before families vote. Position durability refines ORDER_FLOW quality
        # and cannot become a second independent Position Building vote.
        order_flow_quality = max(0.0, min(1.0, float(
            position_meta.get("order_flow_confidence_multiplier", 1.0)
        )))
        oi_samples = int(position_meta.get("oi_series_samples", 0))
        durability_available = oi_samples >= 3
        durability_quality = (
            0.55*persistence_score
            + 0.25*acceleration_score
            + 0.20*position_confidence
        ) if durability_available else 0.0
        reliability_by_family = reliability_by_family or {}
        reliability_enabled = bool(getattr(self.config, "evidence_fusion_reliability_enabled", True))
        def family_reliability(family: str):
            if not reliability_enabled:
                return None
            item = reliability_by_family.get(family)
            if item is None or str(getattr(item, "state", "UNKNOWN")).upper() == "UNKNOWN":
                return None
            value = float(getattr(item, "reliability", 0.0)) / 100.0
            return max(0.0, min(1.0, value))

        market_conflict_strength = 1.0 if analysis.market_bias_gate.startswith("BLOCK") else (
            0.55 if analysis.market_bias_gate == "DOWNGRADE_OPPOSING" else 0.0
        )
        direction_conflict_strength = 1.0 if analysis.direction_confirmation_gate == "BLOCK" else 0.0
        footprint_conflict_strength = 1.0 if alignment == "CONFLICT" else 0.0
        order_flow_source = "PROXY"
        if str(position_meta.get("order_flow_quality_gate", "")).upper() == "BLOCKED":
            order_flow_source = "UNKNOWN"
        elif str(position_meta.get("order_flow_quality_gate", "")).upper() == "DEGRADED":
            order_flow_source = "BOOTSTRAP"

        fusion = self.evidence_fusion_engine.fuse((
            EvidenceSignal("EARLY_TIMING", "TIMING", early_quality,
                           reliability=family_reliability("TIMING")),
            EvidenceSignal("SMART_ENTRY", "ENTRY", smart_entry_score,
                           reliability=family_reliability("ENTRY")),
            EvidenceSignal(
                "FOOTPRINT", "ORDER_FLOW", footprint_score,
                quality=order_flow_quality,
                reliability=family_reliability("ORDER_FLOW"),
                source=order_flow_source,
                contradiction=footprint_conflict_strength > 0.0,
                contradiction_strength=footprint_conflict_strength,
            ),
            EvidenceSignal(
                "POSITION_DURABILITY", "ORDER_FLOW", durability_quality,
                quality=order_flow_quality, available=durability_available,
                reliability=family_reliability("ORDER_FLOW"), source=order_flow_source,
            ),
            EvidenceSignal(
                "DIRECTION_CONFIRMATION", "DIRECTION", structure_quality,
                reliability=family_reliability("DIRECTION"),
                contradiction=direction_conflict_strength > 0.0,
                contradiction_strength=direction_conflict_strength,
            ),
            EvidenceSignal(
                "MARKET_CONTEXT", "MARKET", market_quality,
                reliability=family_reliability("MARKET"),
                contradiction=market_conflict_strength > 0.0,
                contradiction_strength=market_conflict_strength,
            ),
        ))
        final_score = fusion.score
        active_weight = fusion.active_weight
        quality_component_names = fusion.components

        if hard_reasons:
            gate = "BLOCK:"+"|".join(hard_reasons)
            status = EntryStatus.WAIT
        elif analysis.maturity_gate == "LATE":
            # LATE is a downgrade, not a full invalidation. This mirrors
            # combine(): a late trend may remain SETUP, but never READY.
            gate = "TREND_MATURITY_LATE_CAP"
            if status == EntryStatus.READY:
                status = EntryStatus.SETUP
            elif status == EntryStatus.WAIT and final_score >= 62.0:
                status = EntryStatus.SETUP
        elif not bool(
            getattr(footprint, "strong_confirmation", False)
        ):
            gate = "SETUP_ONLY"
            if status == EntryStatus.READY:
                status = EntryStatus.SETUP
        elif final_score >= 76.0:
            gate = "READY_CANDIDATE"
            status = EntryStatus.READY
        elif final_score >= 62.0:
            gate = "SETUP"
            status = EntryStatus.SETUP
        else:
            gate = "QUALITY_TOO_LOW"
            status = EntryStatus.WAIT

        # Harmonic consensus prevents one high layer from compensating
        # fully for a weak/conflicting layer.
        technical_confidence = max(
            0.0,
            min(100.0, analysis.confidence_score),
        )
        if technical_confidence > 0.0 and final_score > 0.0:
            confidence = (
                2.0*technical_confidence*final_score
                / (technical_confidence+final_score)
            )
        else:
            confidence = 0.0
        confidence = min(92.0, confidence)

        if status == EntryStatus.WAIT:
            confidence = min(confidence, 54.0)
        elif status == EntryStatus.SETUP:
            confidence = min(confidence, 71.0)

        alignment_score = (
            100.0 if alignment == "ALIGNED"
            else 50.0 if alignment in ("NEUTRAL", "NOT_APPLIED")
            else 0.0
        )
        reasons.extend((
            f"Footprint V4 raw/context {raw_score:.1f}/{footprint_score:.1f} "
            f"(×{multiplier:.2f}) · {depth} · {alignment}",
            f"Position Building {position_score:.1f} · {position_regime}",
            f"Early Entry {early_quality:.1f} · "
            f"Decision V4 Audit {final_score:.1f} · "
            f"Active/effective weight {active_weight:.2f}/{fusion.effective_weight:.2f} · Gate {gate}",
            "Decision components: " + ", ".join(quality_component_names),
            f"Evidence fusion: {fusion.method} · families {', '.join(fusion.families)} · penalty {fusion.directional_penalty:.1f}",
            "Fusion family details: " + ", ".join(fusion.family_details),
            "Confidence fusion: HARMONIC_TECHNICAL_QUALITY",
        ))

        if (
            status == EntryStatus.READY
            and confidence >= 72.0
            and analysis.risk.risk_score < 55.0
        ):
            revised_action = f"READY {direction}"
            revised_timing = (
                "Chờ retest trong Entry Zone; "
                "không vào giữa nến mở rộng."
            )
        elif status == EntryStatus.SETUP and confidence >= 55.0:
            revised_action = f"CHUẨN BỊ {direction}"
            revised_timing = (
                "Chờ nến 15m xác nhận và Footprint không suy yếu."
            )
        elif status == EntryStatus.RUNNING:
            revised_action = "KHÔNG ĐUỔI GIÁ"
            revised_timing = "Giá đã chạy xa vùng tối ưu; chờ cấu trúc mới."
        else:
            revised_action = "ĐỨNG NGOÀI"
            revised_timing = "Chưa đủ đồng thuận hoặc có hard gate."
        revised_priority = self._priority(confidence, status)

        staged = replace(
            analysis,
            entry_status=status,
            confidence_score=confidence,
            action=revised_action,
            timing=revised_timing,
            priority_status=revised_priority,
            reasons=tuple(reasons),
            footprint=footprint,
            footprint_raw_score=raw_score,
            footprint_score=footprint_score,
            footprint_context_multiplier=multiplier,
            footprint_confirmation_depth=depth,
            footprint_direction_alignment=alignment,
            footprint_gate=gate,
            position_building_score=position_score,
            position_building_regime=position_regime,
            early_entry_score=early_quality,
            smart_money_alignment_score=alignment_score,
            decision_quality_score=final_score,
            position_persistence_score=persistence_score,
            position_acceleration_score=acceleration_score,
            position_confidence_score=position_confidence,
            decision_quality_active_weight=active_weight,
            decision_quality_components=quality_component_names,
            decision_hard_reasons=tuple(hard_reasons),
            confidence_fusion_method="HARMONIC_TECHNICAL_QUALITY",
        )
        graph = self.footprint_graph_engine.build(staged)
        staged = replace(
            staged,
            footprint_chain=graph.chain,
            footprint_chain_text=graph.chain_text,
            footprint_chain_completeness=graph.completeness,
        )
        narrative = self.reasoning_engine.build(
            staged,
            final_score=final_score,
        )
        return replace(
            staged,
            reasoning_headline=narrative.headline,
            reasoning_support=narrative.supporting_evidence,
            reasoning_conflicts=narrative.conflicting_evidence,
            reasoning_hard_blocks=narrative.hard_blocks,
            market_narrative=narrative.market_story,
            next_confirmation=narrative.next_confirmation,
            reasoning_text=narrative.text,
        )



    @staticmethod
    def _direction_confirmation(
        direction: str,
        tf: dict[str, TimeframeAnalysis],
        structure: StructureAnalysis,
        regime: RegimeAnalysis,
        alignment: AlignmentAnalysis,
        smart_entry: SmartEntryAnalysis,
    ) -> tuple[float, str, list[str]]:
        """
        Confirm that the chosen direction is supported by actual transition
        evidence, not merely by a large aggregate score.
        """
        side = direction.upper()
        r15 = tf["15m"]
        r1h = tf["1h"]
        event = str(structure.liquidity_event).lower()
        wyckoff = str(structure.wyckoff_signal).lower()
        test = str(getattr(structure, "wyckoff_test", "")).upper()
        reasons: list[str] = []
        score = 0.0

        if side == "LONG":
            if r15.cmf > 0:
                score += 16
                reasons.append("CMF15m dương")
            if r1h.cmf > 0:
                score += 12
                reasons.append("CMF1h dương")
            if r15.close > r15.ema20:
                score += 14
                reasons.append("Giá trên EMA20")
            if r15.rsi >= 48:
                score += 10
                reasons.append("RSI giữ trên vùng trung tính")
            if "spring" in wyckoff or "quét đáy" in event:
                score += 18
                reasons.append("Spring/Sweep đáy")
            if "TEST AFTER SPRING" in test:
                score += 16
                reasons.append("Test sau Spring")
            if "breakout xác nhận" in event:
                score += 14
                reasons.append("Breakout xác nhận")
            if alignment.label == "ĐỒNG PHA LONG":
                score += 12
            if regime.direction == "LONG":
                score += 10
            # LOI is already consumed in the entry score upstream.

            # Long is invalidated by strong bearish confirmation.
            if r15.cmf < -0.08 and r15.close < r15.ema20:
                score -= 22
            if "upthrust" in wyckoff and "TEST AFTER UPTHRUST" in test:
                score -= 18

        elif side == "SHORT":
            if r15.cmf < 0:
                score += 18
                reasons.append("CMF15m âm")
            if r1h.cmf < 0:
                score += 14
                reasons.append("CMF1h âm")
            if r15.close < r15.ema20:
                score += 16
                reasons.append("Giá dưới EMA20")
            if r15.rsi <= 52:
                score += 10
                reasons.append("RSI mất vùng trung tính")
            if "upthrust" in wyckoff or "quét đỉnh" in event:
                score += 16
                reasons.append("Upthrust/Sweep đỉnh")
            if "TEST AFTER UPTHRUST" in test:
                score += 18
                reasons.append("Test sau Upthrust")
            if "breakdown xác nhận" in event:
                score += 16
                reasons.append("Breakdown xác nhận")
            if alignment.label == "ĐỒNG PHA SHORT":
                score += 12
            if regime.direction == "SHORT":
                score += 10
            # SOI is already consumed in the entry score upstream.

            # Prevent the old failure mode: Upthrust alone cannot overpower
            # positive money flow and intact bullish structure.
            if r15.cmf > 0.08 and r15.close >= r15.ema20:
                score -= 28
                reasons.append("Phạt SHORT: CMF dương và chưa mất EMA20")
            if r1h.cmf > 0.05:
                score -= 14
                reasons.append("Phạt SHORT: CMF1h còn dương")
            if "spring" in wyckoff and "TEST AFTER SPRING" in test:
                score -= 18
        else:
            raise ValueError(f"Unsupported direction: {direction}")

        score = max(0.0, min(100.0, score))
        if score >= 72:
            gate = "CONFIRMED"
        elif score >= 55:
            gate = "WATCH"
        else:
            gate = "BLOCK"
        return score, gate, reasons


    @staticmethod
    def _maturity_gate(maturity: float) -> str:
        if maturity < 28:
            return "UNFORMED"
        if maturity < 48:
            return "EARLY_FORMATION"
        if maturity < 68:
            return "CONFIRMED"
        if maturity < 82:
            return "LATE"
        return "EXHAUSTION"

    @staticmethod
    def _combined_lifecycle(
        score: float,
        lifecycle_15m: str,
        lifecycle_1h: str,
    ) -> str:
        if score >= 82:
            return "EXHAUSTION"
        if score >= 68:
            return "LATE_TREND"
        if (
            "FIRST_RETEST" in (lifecycle_15m, lifecycle_1h)
            and score < 68
        ):
            return "FIRST_RETEST"
        if score >= 48:
            return "CONFIRMED_TREND"
        if score >= 28:
            return "EARLY_FORMATION"
        return "UNFORMED"

    @staticmethod
    def _directional_extension(
        r15: TimeframeAnalysis,
        direction: str,
    ) -> float:
        atr = max(
            float(r15.atr),
            float(r15.close) * 0.002,
            1e-12,
        )
        side = str(direction).upper()
        if side == "LONG":
            return max(
                0.0,
                float(r15.close) - float(r15.ema20),
            ) / atr
        if side == "SHORT":
            return max(
                0.0,
                float(r15.ema20) - float(r15.close),
            ) / atr
        raise ValueError(
            f"Unsupported trade direction: {direction}"
        )

    @staticmethod
    def _extension_limit(
        maturity_gate: str,
        lifecycle: str,
    ) -> float:
        """Maturity-adaptive maximum EMA20 extension for fresh entries."""
        limits = {
            "UNFORMED": 1.10,
            "EARLY_FORMATION": 1.55,
            "CONFIRMED": 1.80,
            "LATE": 1.35,
            "EXHAUSTION": 0.90,
        }
        limit = limits.get(maturity_gate, 1.35)
        if lifecycle == "FIRST_RETEST":
            limit = max(limit, 1.70)
        return limit

    @classmethod
    def _entry_status(
        cls,
        trend: float,
        entry: float,
        r15: TimeframeAnalysis,
        direction: str,
        maturity: float = 50.0,
        lifecycle: str = "UNFORMED",
        maturity_gate: str | None = None,
    ) -> EntryStatus:
        gate = maturity_gate or cls._maturity_gate(maturity)
        extension = cls._directional_extension(r15, direction)
        extension_limit = cls._extension_limit(gate, lifecycle)

        if gate == "EXHAUSTION" or lifecycle == "EXHAUSTION":
            return EntryStatus.RUNNING if max(trend, entry) >= 58 else EntryStatus.WAIT
        if extension > extension_limit:
            return EntryStatus.RUNNING if max(trend, entry) >= 58 else EntryStatus.WAIT
        if gate == "LATE" or lifecycle == "LATE_TREND":
            return EntryStatus.SETUP if entry >= 58 else EntryStatus.WAIT
        if gate == "UNFORMED":
            return EntryStatus.SETUP if entry >= 62 else EntryStatus.WAIT
        # Balanced trend-hunter thresholds. Late/exhaustion and extension
        # blocks above remain unchanged.
        if lifecycle == "FIRST_RETEST":
            if trend >= 58 and entry >= 64:
                return EntryStatus.READY
            if trend >= 45 and entry >= 48:
                return EntryStatus.SETUP

        if lifecycle == "EARLY_FORMATION":
            if trend >= 60 and entry >= 66:
                return EntryStatus.READY
            if trend >= 48 and entry >= 50:
                return EntryStatus.SETUP

        if lifecycle == "CONFIRMED_TREND":
            if trend >= 63 and entry >= 68:
                return EntryStatus.READY
            if trend >= 52 and entry >= 54:
                return EntryStatus.SETUP

        if entry >= 56 and trend >= 45:
            return EntryStatus.SETUP
        return EntryStatus.WAIT

    @staticmethod
    def _quality_gate(
        status: EntryStatus,
        maturity: float,
        maturity_gate: str,
        lifecycle: str,
        extension: float,
    ) -> tuple[EntryStatus, str]:
        limit = DecisionEngine._extension_limit(maturity_gate, lifecycle)
        if maturity_gate == "EXHAUSTION":
            return EntryStatus.RUNNING, "BLOCK_EXHAUSTION"
        if extension > limit:
            return EntryStatus.RUNNING, f"BLOCK_EXTENSION_{extension:.2f}ATR"
        if maturity_gate == "LATE" or lifecycle == "LATE_TREND" or maturity > 78:
            if status == EntryStatus.READY:
                return EntryStatus.SETUP, "DOWNGRADE_LATE"
            return status, "LATE_MONITOR"
        if maturity_gate == "UNFORMED":
            if status == EntryStatus.READY:
                return EntryStatus.SETUP, "DOWNGRADE_UNFORMED"
            return status, "UNFORMED_MONITOR"
        return status, "PASS"

    @staticmethod
    def _priority(conf,status):
        if conf >= 78 and status == EntryStatus.READY: return "🔥 THEO DÕI NÓNG"
        if conf >= 66 and status in (EntryStatus.READY,EntryStatus.SETUP): return "🟢 THEO DÕI"
        if conf >= 52: return "🟡 QUAN SÁT"
        return "⚪ ĐỨNG NGOÀI"


    @staticmethod
    def _trade_plan(direction, price, r15):
        atr = max(r15.atr, price * 0.002)
        atr_pct = atr / max(price, 1e-12)
        zone_factor = 0.65 if atr_pct >= 0.025 else 0.80
        invalidation_factor = 0.45 if atr_pct >= 0.025 else 0.35
        plan_repaired = False
        plan_repair_reason = ""

        if direction == "LONG":
            entry_a = max(r15.support, price - zone_factor * atr)
            entry_b = price - 0.2 * atr
            entry_low = min(entry_a, entry_b)
            entry_high = max(entry_a, entry_b)
            entry_mid = (entry_low + entry_high) / 2.0

            invalidation = min(r15.support, entry_low) - invalidation_factor * atr
            invalidation = min(invalidation, entry_low - 0.20 * atr)

            risk = max(entry_mid - invalidation, 0.45 * atr)
            tp1 = entry_mid + 1.5 * risk
            tp2 = entry_mid + 2.3 * risk
            confirmations = (
                "Giữ swing low 15m",
                "CMF 15m tăng, CMF 1h không xấu",
                "OI không giảm mạnh khi retest",
                "Không xuất hiện Upthrust",
            )
            cancels = (
                "Đóng 15m dưới invalidation",
                "CMF 15m và 1h cùng âm mạnh",
                "BTC bán tháo bất thường",
            )
            valid = invalidation < entry_low < entry_high < tp1 < tp2
        else:
            entry_a = price + 0.2 * atr
            entry_b = min(r15.resistance, price + zone_factor * atr)
            entry_low = min(entry_a, entry_b)
            entry_high = max(entry_a, entry_b)
            entry_mid = (entry_low + entry_high) / 2.0

            invalidation = max(r15.resistance, entry_high) + invalidation_factor * atr
            invalidation = max(invalidation, entry_high + 0.20 * atr)

            risk = max(invalidation - entry_mid, 0.45 * atr)
            tp1 = entry_mid - 1.5 * risk
            tp2 = entry_mid - 2.3 * risk
            confirmations = (
                "Không vượt swing high 15m",
                "CMF 15m suy yếu, 1h không cải thiện",
                "OI không giảm mạnh khi giá giảm",
                "Không xuất hiện Spring",
            )
            cancels = (
                "Đóng 15m trên invalidation",
                "CMF 15m và 1h cùng dương mạnh",
                "BTC tăng mạnh kéo altcoin",
            )
            valid = tp2 < tp1 < entry_low < entry_high < invalidation

        if not valid:
            plan_repaired = True
            plan_repair_reason = (
                "Trade-plan geometry adjusted after support/resistance "
                "produced an invalid ordering."
            )
            logger.warning(
                "Trade plan repaired | direction=%s price=%.8g "
                "support=%.8g resistance=%.8g atr=%.8g",
                direction,
                price,
                r15.support,
                r15.resistance,
                atr,
            )
            # Soft repair for small geometry violations caused by unusual
            # support/resistance values. Recalculate the complete plan once.
            minimum_gap = max(0.15 * atr, price * 0.0005)
            if direction == "LONG":
                entry_low = min(entry_low, entry_high - minimum_gap)
                entry_high = max(entry_high, entry_low + minimum_gap)
                entry_mid = (entry_low + entry_high) / 2.0
                invalidation = min(
                    invalidation,
                    entry_low - minimum_gap,
                )
                risk = max(
                    entry_mid - invalidation,
                    0.45 * atr,
                )
                tp1 = entry_mid + 1.5 * risk
                tp2 = entry_mid + 2.3 * risk
                valid = (
                    invalidation < entry_low
                    < entry_high < tp1 < tp2
                )
            else:
                entry_low = min(entry_low, entry_high - minimum_gap)
                entry_high = max(entry_high, entry_low + minimum_gap)
                entry_mid = (entry_low + entry_high) / 2.0
                invalidation = max(
                    invalidation,
                    entry_high + minimum_gap,
                )
                risk = max(
                    invalidation - entry_mid,
                    0.45 * atr,
                )
                tp1 = entry_mid - 1.5 * risk
                tp2 = entry_mid - 2.3 * risk
                valid = (
                    tp2 < tp1 < entry_low
                    < entry_high < invalidation
                )

        if not valid:
            raise ValueError(
                f"Trade plan invariant failed after repair: {direction}; "
                f"tp2={tp2}, tp1={tp1}, "
                f"entry=({entry_low}, {entry_high}), "
                f"invalidation={invalidation}"
            )

        rr = abs(tp2 - entry_mid) / max(
            abs(entry_mid - invalidation),
            1e-12,
        )
        return TradePlan(
            direction,
            entry_low,
            entry_high,
            invalidation,
            tp1,
            tp2,
            rr,
            confirmations,
            cancels,
            plan_repaired,
            plan_repair_reason,
        )

    @staticmethod
    def _reasons(
        tf, snap, oi_state, direction, structure,
        regime, alignment, risk, smart_entry
    ):
        out = []
        for k in ("15m", "1h", "4h", "1d"):
            r = tf[k]
            out.append(
                f"{k}: CMF {r.cmf:+.3f}, RSI {r.rsi:.1f}, ADX {r.adx:.1f}, "
                f"Vol x{r.relative_volume:.2f}, pha {r.market_phase}"
            )
        out.append(f"OI 15m {snap.oi_change_15m_pct:+.2f}% → {oi_state}")
        out.append(f"Funding {snap.funding_pct:+.4f}%")
        out.append(f"Smart Entry: {smart_entry.state}")
        out.extend(smart_entry.explanation)
        out.append(f"Regime: {regime.description}")
        out.append(f"MTF: {alignment.description}")
        out.append(
            f"Risk {risk.risk_score:.0f}/100 ({risk.risk_level}), "
            f"size factor x{risk.size_factor:.2f}"
        )
        out.append(
            f"Leverage {risk.leverage:.1f}x | Liq {risk.liquidation_price:.8g} | "
            f"Max safe {risk.max_safe_leverage:.1f}x | "
            f"Margin ~{risk.margin_required:.2f} USDT | "
            f"Notional ~{risk.position_notional:.2f} USDT"
        )
        out.append(
            f"Dynamic Buffer: "
            f"{getattr(risk, 'dynamic_buffer_used', 0.0):.4f} "
            f"({getattr(risk, 'dynamic_buffer_used', 0.0) * 100:.2f}%)"
        )
        out.append(
            f"Effective Stop: "
            f"{getattr(risk, 'effective_stop_distance', 0.0):.8g} "
            f"(Effective Stop Distance)"
        )
        out.append(
            f"Leverage Constraint: "
            f"{getattr(risk, 'leverage_constraint_state', 'UNKNOWN')} "
            f"(Leverage Constraint State)"
        )
        out.extend(risk.warnings)
        out.append(f"Liquidity: {structure.liquidity_event}")
        out.append(
            f"Sweep Volume State: "
            f"{getattr(structure, 'sweep_volume_state', 'NONE')}"
        )
        out.append(
            f"Wyckoff: {structure.wyckoff_signal} | {structure.effort_result}"
        )
        out.append(
            f"Structure Wyckoff Test: "
            f"{getattr(structure, 'wyckoff_test', 'NONE')} "
            f"({getattr(structure, 'wyckoff_test_score', 0.0):.0f}/100)"
        )
        out.extend(structure.warnings)
        out.append(
            "OI và Wyckoff là suy luận heuristic, cần xác nhận bằng hành vi giá tiếp theo."
        )
        return out
