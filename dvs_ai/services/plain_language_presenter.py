from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlainLanguageView:
    traffic_light: str
    traffic_label: str
    headline: str
    direction_text: str
    risk_text: str
    reasons: tuple[str, ...]
    next_steps: tuple[str, ...]
    caution: str


class PlainLanguagePresenter:
    """Converts immutable analysis output into beginner-friendly language.

    Observe-only: this class reads analysis fields and returns text. It does not
    mutate scores, gates, risk, action, direction, sizing, or execution state.
    """

    @staticmethod
    def _traffic(action: str, entry_status: str, risk_score: float) -> tuple[str, str]:
        normalized = f"{action} {entry_status}".upper()
        if risk_score > 60 or any(x in normalized for x in ("ĐỨNG NGOÀI", "STAND ASIDE", "BLOCK")):
            return "RED", "ĐỨNG NGOÀI"
        if any(x in normalized for x in ("READY", "VÀO LỆNH", "ENTER")) and risk_score <= 50:
            return "GREEN", "CÓ THỂ HÀNH ĐỘNG"
        return "YELLOW", "THEO DÕI"

    def build(self, analysis) -> PlainLanguageView:
        action = str(getattr(analysis, "action", "ĐỨNG NGOÀI"))
        direction = str(getattr(analysis, "direction", "NEUTRAL"))
        entry_status = str(getattr(getattr(analysis, "entry_status", None), "value", "WAIT"))
        risk_score = float(getattr(getattr(analysis, "risk", None), "risk_score", 100.0))
        risk_level = str(getattr(getattr(analysis, "risk", None), "risk_level", "CAO"))
        narrative = getattr(analysis, "explainable_narrative", None)
        blockers = tuple(getattr(analysis, "explainable_blockers", ()) or ())
        next_confirmation = tuple(getattr(analysis, "explainable_next_confirmation", ()) or ())
        traffic, traffic_label = self._traffic(action, entry_status, risk_score)

        if direction == "LONG":
            direction_text = "Hệ thống đang nghiêng về phía tăng, nhưng chỉ nên Long khi mọi điều kiện xác nhận đã đủ."
        elif direction == "SHORT":
            direction_text = "Hệ thống đang nghiêng về phía giảm, nhưng không nên đuổi giá khi điểm vào chưa rõ."
        else:
            direction_text = "Thị trường chưa có hướng đủ rõ; ưu tiên bảo toàn vốn."

        market_story = tuple(getattr(narrative, "market_story", ()) or ())
        simple_reasons = []
        for blocker in blockers[:4]:
            text = str(blocker)
            replacements = {
                "Regime/direction chưa đủ mạnh hoặc còn trung tính.": "Xu hướng chưa đủ mạnh.",
                "Đa khung chưa đồng pha đủ mạnh.": "Các khung thời gian chưa cùng hướng.",
                "Smart Entry chưa có edge xác nhận.": "Chưa xuất hiện điểm vào có lợi thế rõ.",
                "Chưa có Structure Test/Spring/Upthrust đủ mạnh.": "Chưa có tín hiệu xác nhận đảo chiều hoặc tiếp diễn.",
            }
            simple_reasons.append(replacements.get(text, text))
        if not simple_reasons:
            simple_reasons = [str(x) for x in market_story[:3]] or ["Chưa có đủ bằng chứng để hành động."]

        simple_next = []
        for item in next_confirmation[:4]:
            text = str(item)
            text = text.replace("Structure Test/Spring/Upthrust", "tín hiệu xác nhận cấu trúc")
            text = text.replace("absorption/passive bid", "lực hấp thụ mua")
            text = text.replace("OFI và book imbalance", "dòng lệnh mua/bán")
            text = text.replace("Entry chuyển SETUP/READY", "điểm vào chuyển sang SẴN SÀNG")
            simple_next.append(text)
        if not simple_next:
            simple_next = ["Tiếp tục quan sát; không thay đổi ngưỡng hoặc ép vào lệnh."]

        if traffic == "GREEN":
            headline = f"{traffic_label}: ưu tiên {direction}."
            caution = "Vẫn phải tuân thủ mức dừng lỗ và giới hạn rủi ro của hệ thống."
        elif traffic == "YELLOW":
            headline = f"{traffic_label}: đang nghiêng {direction}, nhưng chưa đủ điều kiện vào lệnh."
            caution = "Không FOMO. Chờ các điều kiện còn thiếu được xác nhận."
        else:
            headline = f"{traffic_label}: chưa nên giao dịch {getattr(analysis, 'symbol', '')}."
            caution = "Bảo toàn vốn quan trọng hơn cố tìm một lệnh giao dịch."

        return PlainLanguageView(
            traffic_light=traffic,
            traffic_label=traffic_label,
            headline=headline,
            direction_text=direction_text,
            risk_text=f"Rủi ro hiện tại: {risk_level} ({risk_score:.0f}/100).",
            reasons=tuple(simple_reasons),
            next_steps=tuple(simple_next),
            caution=caution,
        )
