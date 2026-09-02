from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExplainableNarrativeResult:
    headline: str
    market_story: tuple[str, ...]
    decision_path: tuple[str, ...]
    decision_blockers: tuple[str, ...]
    smart_entry_story: tuple[str, ...]
    smart_money_story: tuple[str, ...]
    next_confirmation: tuple[str, ...]
    observe_only: bool = True


class ExplainableNarrativeEngine:
    """Deterministic, observe-only explanation layer.

    It translates already-computed engine states into concise operational
    language. It never changes scores, gates, risk, direction, or execution.
    """

    @staticmethod
    def _state(ok: bool) -> str:
        return "PASS" if ok else "WAIT"

    def evaluate(self, analysis) -> ExplainableNarrativeResult:
        tf15 = analysis.timeframes.get("15m")
        cmf = float(getattr(tf15, "cmf", 0.0)) if tf15 else 0.0
        rsi = float(getattr(tf15, "rsi", 50.0)) if tf15 else 50.0
        adx = float(getattr(tf15, "adx", 0.0)) if tf15 else 0.0
        se = analysis.smart_entry
        ex = getattr(analysis, "composite_exhaustion", None)
        micro = getattr(analysis, "microstructure", None)

        direction = str(getattr(analysis, "direction", "NEUTRAL"))
        action = str(getattr(analysis, "action", "ĐỨNG NGOÀI"))
        entry_status = getattr(getattr(analysis, "entry_status", None), "value", "WAIT")
        risk_score = float(getattr(getattr(analysis, "risk", None), "risk_score", 100.0))
        alignment_label = str(getattr(getattr(analysis, "alignment", None), "label", "UNKNOWN"))
        alignment_score = max(
            float(getattr(getattr(analysis, "alignment", None), "long_score", 0.0)),
            float(getattr(getattr(analysis, "alignment", None), "short_score", 0.0)),
        )
        structure_test = str(getattr(getattr(analysis, "structure", None), "wyckoff_test", "NONE"))
        structure_score = float(getattr(getattr(analysis, "structure", None), "wyckoff_test_score", 0.0))
        footprint_gate = str(getattr(analysis, "footprint_gate", "NOT_APPLIED"))
        market_gate = str(getattr(analysis, "market_bias_gate", "NOT_APPLIED"))
        conf_gate = str(getattr(analysis, "direction_confirmation_gate", "NOT_APPLIED"))

        market_story = (
            f"Regime {analysis.regime.regime}, bias {analysis.regime.direction}, strength {analysis.regime.strength:.0f}/100.",
            f"15m: CMF {cmf:+.3f}, RSI {rsi:.1f}, ADX {adx:.1f}; alignment {alignment_label} ({alignment_score:.0f}/100).",
            f"Composite: {getattr(ex, 'state', 'NOT_EVALUATED')}; selling pressure {getattr(ex, 'selling_pressure', 0.0):.1f}/100; bottom evidence {getattr(ex, 'bottom_formation_probability', 0.0):.1f}/100.",
        )

        trend_ok = direction in {"LONG", "SHORT"} and analysis.regime.strength >= 50
        alignment_ok = alignment_score >= 55 and "MÂU THUẪN" not in alignment_label.upper()
        risk_ok = risk_score <= 50
        footprint_ok = footprint_gate not in {"BLOCK", "BLOCKED", "HARD_BLOCK"}
        smart_ok = str(se.state).upper() not in {"NO EDGE", "WAIT", "NONE"}
        structure_ok = structure_test.upper() not in {"", "NONE"} and structure_score >= 45
        entry_ok = entry_status in {"SETUP", "READY", "RUNNING"}

        decision_path = (
            f"Market regime: {self._state(trend_ok)} — {analysis.regime.regime}/{direction}",
            f"Multi-timeframe: {self._state(alignment_ok)} — {alignment_label}",
            f"Risk gate: {self._state(risk_ok)} — {risk_score:.0f}/100",
            f"Footprint gate: {self._state(footprint_ok)} — {footprint_gate}",
            f"Structure confirmation: {self._state(structure_ok)} — {structure_test} {structure_score:.0f}/100",
            f"Smart Entry: {self._state(smart_ok)} — {se.state}",
            f"Entry status: {self._state(entry_ok)} — {entry_status}",
            f"Final action: {action}",
        )

        blockers=[]
        if not trend_ok: blockers.append("Regime/direction chưa đủ mạnh hoặc còn trung tính.")
        if not alignment_ok: blockers.append("Đa khung chưa đồng pha đủ mạnh.")
        if not risk_ok: blockers.append(f"Risk {risk_score:.0f}/100 vượt ngưỡng vận hành.")
        if market_gate in {"BLOCK", "BLOCKED", "HARD_BLOCK"}: blockers.append("Market bias hard gate đang chặn.")
        if conf_gate in {"BLOCK", "BLOCKED", "HARD_BLOCK"}: blockers.append("Direction confirmation hard gate đang chặn.")
        if not footprint_ok: blockers.append(f"Footprint gate đang chặn ({footprint_gate}).")
        if not structure_ok: blockers.append("Chưa có Structure Test/Spring/Upthrust đủ mạnh.")
        if not smart_ok: blockers.append("Smart Entry chưa có edge xác nhận.")
        if not entry_ok: blockers.append(f"Entry status vẫn là {entry_status}.")
        if not blockers: blockers.append("Không phát hiện hard blocker; vẫn cần tuân thủ Decision Engine.")

        absorption = float(getattr(se, "absorption_score", 0.0))
        weak = float(getattr(se, "weak_hand_score", 0.0))
        panic = float(getattr(se, "panic_flush_score", 0.0))
        smart_entry_story = (
            f"Weak-hand {weak:.0f}/100: " + ("áp lực xả rõ" if weak >= 60 else "chưa có capitulation rõ"),
            f"Absorption {absorption:.0f}/100: " + ("có hấp thụ đáng chú ý" if absorption >= 55 else "passive buyer chưa đủ mạnh"),
            f"Panic flush {panic:.0f}/100: " + ("panic đang hiện diện" if panic >= 55 else "chưa có panic flush xác nhận"),
            f"LOI/SOI {se.long_opportunity_index:.0f}/{se.short_opportunity_index:.0f}; state {se.state}.",
        )

        ofi=float(getattr(micro, "ofi_score", 0.0))
        book=float(getattr(micro, "book_imbalance", 0.0))
        smart_money_story = (
            f"Composite {getattr(ex, 'state', 'NOT_EVALUATED')}: distribution {getattr(ex, 'distribution_progress', 0.0):.1f}/100, pressure {getattr(ex, 'selling_pressure', 0.0):.1f}/100.",
            f"Exhaustion {getattr(ex, 'exhaustion_score', 0.0):.1f}/100; absorption {getattr(ex, 'absorption_score', 0.0):.1f}/100; passive bid {getattr(ex, 'passive_bid_score', 0.0):.1f}/100.",
            f"Micro flow: OFI {ofi:+.1f}, book imbalance {book:+.3f}; bottom state {getattr(ex, 'bottom_state', 'NOT_EVALUATED')}.",
            "Composite đang giảm lực bán." if getattr(ex, 'state', '') in {"SELLING_EXHAUSTING", "SELLING_PAUSED", "ABSORPTION_WATCH"} else "Composite chưa cho thấy quá trình dừng bán đủ rõ.",
        )

        next_confirmation=[]
        if not structure_ok: next_confirmation.append("Chờ Structure Test/Spring/Upthrust được xác nhận.")
        if absorption < 55: next_confirmation.append("Chờ absorption/passive bid tăng bền vững.")
        if ofi <= 8 or book <= 0.02: next_confirmation.append("Chờ OFI và book imbalance cùng chuyển thuận hướng.")
        if not alignment_ok: next_confirmation.append("Chờ 15m và 1h đồng pha rõ hơn.")
        if not entry_ok: next_confirmation.append("Chờ Entry chuyển SETUP/READY.")
        if not next_confirmation: next_confirmation.append("Tiếp tục quan sát và giữ nguyên hard gates hiện tại.")

        headline = f"{analysis.symbol}: {action} — " + (blockers[0] if blockers else "không có blocker")
        return ExplainableNarrativeResult(
            headline=headline,
            market_story=market_story,
            decision_path=decision_path,
            decision_blockers=tuple(blockers),
            smart_entry_story=smart_entry_story,
            smart_money_story=smart_money_story,
            next_confirmation=tuple(next_confirmation),
            observe_only=True,
        )
