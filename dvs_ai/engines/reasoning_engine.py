from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class DecisionNarrative:
    action: str
    headline: str
    supporting_evidence: tuple[str, ...]
    conflicting_evidence: tuple[str, ...]
    hard_blocks: tuple[str, ...]
    market_story: tuple[str, ...]
    next_confirmation: tuple[str, ...]
    summary: str

    @property
    def text(self) -> str:
        sections = [self.headline]
        if self.supporting_evidence:
            sections.append(
                "BẰNG CHỨNG ỦNG HỘ\n✓ "
                + "\n✓ ".join(self.supporting_evidence)
            )
        if self.conflicting_evidence:
            sections.append(
                "BẰNG CHỨNG XUNG ĐỘT\n△ "
                + "\n△ ".join(self.conflicting_evidence)
            )
        if self.hard_blocks:
            sections.append(
                "HARD GATE CHẶN LỆNH\n✗ "
                + "\n✗ ".join(self.hard_blocks)
            )
        if self.market_story:
            sections.append(
                "CÂU CHUYỆN SMART MONEY\n- "
                + "\n- ".join(self.market_story)
            )
        if self.next_confirmation:
            sections.append(
                "CẦN XÁC NHẬN TIẾP\n→ "
                + "\n→ ".join(self.next_confirmation)
            )
        sections.append("KẾT LUẬN\n" + self.summary)
        return "\n\n".join(sections)


class SmartMoneyReasoningEngine:
    """Explainable, deterministic narrative layer. It never changes decisions."""

    BLOCK_LABELS = {
        "LIFECYCLE_TOO_LATE": "Lifecycle đã quá muộn; tránh đuổi theo xu hướng.",
        "FOOTPRINT_TOO_WEAK": "Footprint chưa đủ mạnh để xác nhận dòng tiền lớn.",
        "FOOTPRINT_DIRECTION_CONFLICT": "Footprint đang ngược hướng với tín hiệu.",
        "POSITION_BUILDING_TOO_WEAK": "OI/Funding/Delta chưa xác nhận xây vị thế.",
        "MARKET_BIAS_BLOCK": "Bối cảnh BTC/thị trường đang chặn hướng giao dịch.",
        "LIQUIDATION_UNSAFE": "Khoảng cách thanh lý không an toàn.",
        "RR_TOO_LOW": "R:R kế hoạch thấp hơn tiêu chuẩn.",
    }

    @staticmethod
    def _clean_gate(gate: str) -> tuple[str, ...]:
        text = str(gate or "")
        if not text.startswith("BLOCK:"):
            return ()
        return tuple(
            token for token in text.split(":", 1)[1].split("|") if token
        )

    @staticmethod
    def _component_score(footprint, name: str) -> float:
        scores = getattr(footprint, "component_scores", {}) or {}
        try:
            return float(scores.get(name, 0.0))
        except Exception:
            return 0.0

    def build(self, analysis, *, final_score: float | None = None) -> DecisionNarrative:
        direction = str(analysis.direction).upper()
        status = getattr(analysis.entry_status, "value", str(analysis.entry_status))
        footprint = getattr(analysis, "footprint", None)
        fp_score = float(getattr(analysis, "footprint_score", 0.0))
        position_score = float(getattr(analysis, "position_building_score", 0.0))
        alignment = str(
            getattr(analysis, "footprint_direction_alignment", "NOT_APPLIED")
        )
        depth = str(
            getattr(analysis, "footprint_confirmation_depth", "NONE")
        )
        lifecycle = str(
            getattr(footprint, "lifecycle_stage", getattr(analysis, "trend_lifecycle", "UNKNOWN"))
        ).upper()
        gate = str(getattr(analysis, "footprint_gate", "NOT_APPLIED"))
        blocks = self._clean_gate(gate)

        support: list[str] = []
        conflict: list[str] = []
        story: list[str] = []
        next_steps: list[str] = []

        ob = self._component_score(footprint, "order_block")
        fvg = self._component_score(footprint, "fvg")
        bos = self._component_score(footprint, "bos_choch")
        liquidity = self._component_score(footprint, "liquidity_sweep")
        absorption = self._component_score(footprint, "absorption")

        if fp_score >= 72:
            support.append(f"Footprint mạnh {fp_score:.1f}/100.")
        elif fp_score >= 60:
            support.append(f"Footprint đạt ngưỡng tối thiểu {fp_score:.1f}/100.")
        else:
            conflict.append(f"Footprint yếu {fp_score:.1f}/100.")

        if depth == "STRONG":
            support.append("Có ít nhất 3 nhóm bằng chứng độc lập đồng thuận.")
        elif depth in ("CONFIRMED", "WEAK"):
            conflict.append(f"Confirmation Depth mới ở mức {depth}.")
        else:
            conflict.append("Chưa có chiều sâu xác nhận Footprint.")

        if alignment == "ALIGNED":
            support.append(f"Footprint đồng hướng {direction}.")
        elif alignment == "CONFLICT":
            conflict.append("Footprint ngược hướng Decision.")
        else:
            conflict.append(f"Direction Alignment đang ở mức {alignment}.")

        if position_score >= 65:
            support.append(f"Position Building mạnh {position_score:.1f}/100.")
        elif position_score >= 48:
            support.append(f"Position Building vừa đủ {position_score:.1f}/100.")
        else:
            conflict.append(f"Position Building yếu {position_score:.1f}/100.")

        if ob >= 65:
            support.append(f"Order Block chất lượng {ob:.0f}/100.")
        elif ob > 0:
            conflict.append(f"Order Block chưa mạnh ({ob:.0f}/100).")

        if bos >= 65:
            support.append(f"BOS/CHOCH đã xác nhận ({bos:.0f}/100).")
        elif bos > 0:
            conflict.append(f"BOS/CHOCH chưa rõ ({bos:.0f}/100).")

        if liquidity >= 65:
            support.append(f"Liquidity Sweep/Grab rõ ({liquidity:.0f}/100).")
        elif liquidity > 0:
            conflict.append(f"Liquidity evidence yếu ({liquidity:.0f}/100).")

        if fvg >= 65:
            support.append(f"FVG hỗ trợ hướng giao dịch ({fvg:.0f}/100).")
        if absorption >= 60:
            support.append(f"Absorption xác nhận hấp thụ ({absorption:.0f}/100).")

        oi_state = str(getattr(analysis, "oi_state", "OI trung tính"))
        funding = float(getattr(analysis.snapshot, "funding_pct", 0.0))
        regime = str(getattr(analysis, "position_building_regime", "UNKNOWN"))
        story.append(f"Lifecycle hiện tại: {lifecycle}.")
        story.append(f"OI state: {oi_state}; Position regime: {regime}.")
        story.append(f"Funding hiện tại {funding:+.4f}%.")
        persistence = float(getattr(analysis, "position_persistence_score", 0.0))
        acceleration = float(getattr(analysis, "position_acceleration_score", 0.0))
        position_confidence = float(getattr(analysis, "position_confidence_score", 0.0))
        if persistence > 0.0:
            story.append(
                f"Position persistence {persistence:.1f}; "
                f"acceleration {acceleration:.1f}; confidence {position_confidence:.1f}."
            )
        chain = str(getattr(analysis, "footprint_chain_text", ""))
        if chain and chain != "NO_CONFIRMED_CHAIN":
            story.append(f"Footprint chain: {chain}.")

        if "LONG_BUILDING" in regime:
            story.append("OI và giá đang cho thấy phe Long mở vị thế mới.")
        elif "SHORT_BUILDING" in regime:
            story.append("OI và giá đang cho thấy phe Short mở vị thế mới.")
        elif "SHORT_COVERING" in regime:
            story.append("Đà tăng có phần đến từ Short Covering, chưa chắc là Long mới.")
        elif "LONG_CLOSING" in regime:
            story.append("Đà giảm có phần đến từ Long Closing, chưa chắc là Short mới.")
        else:
            story.append("Chưa có dấu hiệu xây vị thế rõ ràng từ thị trường phái sinh.")

        if lifecycle in ("MARKUP", "MARKDOWN", "EXHAUSTION"):
            story.append("Cấu trúc đã đi xa; ưu tiên bảo toàn vốn hơn là đuổi giá.")
        elif lifecycle in ("SPRING", "TEST", "ACCUMULATION", "UPTHRUST", "DISTRIBUTION"):
            story.append("Cấu trúc đang ở vùng có thể hình thành setup sớm nếu xác nhận đủ.")

        for token in blocks:
            label = self.BLOCK_LABELS.get(token, token.replace("_", " ").title())
            next_steps.append(label)

        if not blocks and status == "SETUP":
            next_steps.extend((
                "Chờ Confirmation Depth lên STRONG.",
                "Chờ Position Building và hướng Footprint tiếp tục đồng thuận.",
            ))
        elif status == "WAIT" and not next_steps:
            next_steps.append("Chờ Quality Score và Confidence vượt ngưỡng an toàn.")
        elif status == "READY":
            next_steps.append("Giữ nguyên risk plan; không tăng size ngoài Position Sizer.")

        hard_labels = tuple(
            self.BLOCK_LABELS.get(token, token.replace("_", " ").title())
            for token in blocks
        )
        action = "ĐỨNG NGOÀI" if status == "WAIT" else status
        headline = f"{analysis.symbol} · {direction} · {action}"
        quality_text = (
            f"Decision Quality {final_score:.1f}/100. "
            if final_score is not None else ""
        )
        summary = (
            f"{quality_text}Hệ thống giữ trạng thái {status}. "
            + (
                "Có hard gate nên không được nâng lên lệnh giao dịch."
                if blocks
                else "Không có hard gate mới ngoài các điều kiện hiển thị."
            )
        )
        return DecisionNarrative(
            action=action,
            headline=headline,
            supporting_evidence=tuple(support[:8]),
            conflicting_evidence=tuple(conflict[:8]),
            hard_blocks=hard_labels,
            market_story=tuple(story[:8]),
            next_confirmation=tuple(next_steps[:8]),
            summary=summary,
        )
