from __future__ import annotations

from dataclasses import dataclass

from dvs_ai.services.core_shadow_agreement_service import QualificationEvidenceRecord


@dataclass(frozen=True, slots=True)
class QualificationReplayStep:
    index: int
    key: str
    title: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class QualificationDecisionNode:
    index: int
    key: str
    label: str
    status: str
    contribution: float
    detail: str
    category: str = "SYSTEM"
    source: str = "PERSISTED_EVIDENCE"
    interpretation: str = ""


@dataclass(frozen=True, slots=True)
class QualificationReplaySession:
    request_id: str
    symbol: str
    valid: bool
    integrity_status: str
    steps: tuple[QualificationReplayStep, ...]
    graph_nodes: tuple[QualificationDecisionNode, ...]
    final_verdict: str


class QualificationReplayService:
    """Build a deterministic, read-only replay from persisted qualification evidence."""

    def build(self, record: QualificationEvidenceRecord) -> QualificationReplaySession:
        steps: list[QualificationReplayStep] = []

        def add(key: str, title: str, status: str, detail: str) -> None:
            steps.append(QualificationReplayStep(len(steps) + 1, key, title, status, detail))

        integrity_ok = record.integrity_status == "PASS"
        add(
            "integrity",
            "1. Xác minh Evidence",
            "PASS" if integrity_ok else record.integrity_status,
            (
                "Evidence hash khớp payload đã niêm phong."
                if integrity_ok
                else "Evidence không vượt qua kiểm tra toàn vẹn; replay chỉ hiển thị để điều tra và không được dùng cho Qualification."
            ),
        )
        add(
            "context",
            "2. Khôi phục Market Context",
            "LOADED",
            (
                f"Symbol: {record.symbol}\n"
                f"Timeframe: {record.timeframe}\n"
                f"Regime: {record.regime}\n"
                f"Phase: {record.phase}\n"
                f"Confidence: {record.confidence:.2f}"
            ),
        )
        add(
            "legacy",
            "3. Legacy Decision",
            record.legacy_action,
            (
                "Paper Authority: LEGACY\n"
                f"Decision: {record.legacy_action}\n"
                f"Observation revision: {record.analysis_revision}"
            ),
        )
        add(
            "unified",
            "4. Unified Shadow Decision",
            record.unified_action,
            (
                f"Shadow-only decision: {record.unified_action}\n"
                f"Authorized: {record.authorized}\n"
                f"Quantity exposed: {record.quantity:.4f}"
            ),
        )
        for code in record.reason_codes:
            add("reason", f"Reason Code · {code}", "OBSERVED", code)
        for event in record.event_names:
            add("event", f"Scientific Event · {event}", "REPLAYED", event)
        add(
            "risk",
            "Risk & Ledger Gate",
            "PASS" if record.ledger_verified and not record.authorized and record.quantity == 0 else "REVIEW",
            (
                f"Ledger verified: {record.ledger_verified}\n"
                f"Synthetic lifecycle: {record.synthetic_lifecycle}\n"
                f"Risk allowed: {record.risk_allowed}\n"
                f"Authorized: {record.authorized}\n"
                f"Quantity: {record.quantity:.4f}\n"
                f"Ledger hash: {record.ledger_hash or '-'}"
            ),
        )
        add(
            "agreement",
            "Legacy ↔ Unified Agreement",
            record.agreement,
            (
                f"Legacy: {record.legacy_action}\n"
                f"Unified: {record.unified_action}\n"
                f"Classification: {record.agreement}"
            ),
        )
        graph_nodes: list[QualificationDecisionNode] = []

        def graph_add(
            key: str, label: str, status: str, contribution: float, detail: str,
            *, category: str = "SYSTEM", source: str = "PERSISTED_EVIDENCE",
            interpretation: str = "",
        ) -> None:
            graph_nodes.append(
                QualificationDecisionNode(
                    index=len(graph_nodes) + 1,
                    key=key,
                    label=label,
                    status=status,
                    contribution=float(contribution),
                    detail=detail,
                    category=category,
                    source=source,
                    interpretation=interpretation,
                )
            )

        graph_add(
            "evidence", "Evidence Integrity",
            "PASS" if integrity_ok else record.integrity_status,
            0.0,
            "Niêm phong SHA-256 của Evidence phải hợp lệ trước khi một observation được dùng cho qualification.",
            category="INTEGRITY", interpretation="PASS cho phép dùng evidence trong qualification; trạng thái khác chỉ phục vụ điều tra.",
        )
        graph_add(
            "context", "Market Context", "LOADED", 0.0,
            f"{record.symbol} · {record.timeframe} · regime {record.regime} · phase {record.phase}",
            category="CONTEXT", interpretation="Bối cảnh thị trường được khôi phục nguyên trạng từ evidence đã lưu.",
        )
        # Persisted reason codes and scientific events are the authoritative explainability inputs.
        # Contributions are intentionally descriptive, not trading weights, and always sum to confidence.
        explainability_items = list(record.reason_codes) + list(record.event_names)
        share = (record.confidence / len(explainability_items)) if explainability_items else 0.0
        if not explainability_items and record.confidence != 0:
            graph_add(
                "baseline_confidence", "Baseline Confidence", "DESCRIPTIVE_ONLY",
                record.confidence,
                "Persisted confidence retained because no granular reason code or scientific event was recorded.",
                category="CONFIDENCE", source="PERSISTED_EVIDENCE",
                interpretation=(
                    "Đây là confidence gốc đã lưu, không phải chỉ báo hoặc trọng số giao dịch mới. "
                    "Node này bảo đảm confidence không biến mất khi evidence không có reason/event chi tiết."
                ),
            )
        for item in record.reason_codes:
            prefix = str(item).split("_", 1)[0].upper() if item else "REASON"
            graph_add(
                "reason", item, "OBSERVED", share, f"Persisted reason code: {item}",
                category=prefix, source="REASON_CODE",
                interpretation=self._interpret_reason_code(item),
            )
        for item in record.event_names:
            prefix = str(item).split("_", 1)[0].upper() if item else "EVENT"
            graph_add(
                "event", item, "REPLAYED", share, f"Persisted scientific event: {item}",
                category=prefix, source="SCIENTIFIC_EVENT",
                interpretation=self._interpret_reason_code(item),
            )
        graph_add(
            "risk", "Risk & Ledger Gate",
            "PASS" if record.ledger_verified and not record.authorized and record.quantity == 0 else "REVIEW",
            0.0,
            f"ledger_verified={record.ledger_verified}; authorized={record.authorized}; quantity={record.quantity:.4f}",
            category="RISK", interpretation="Gate an toàn xác nhận replay không có quyền thực thi và quantity luôn bằng 0.",
        )
        graph_add(
            "decision", "Unified Shadow Decision", record.unified_action, 0.0,
            f"Unified={record.unified_action}; Legacy={record.legacy_action}; Agreement={record.agreement}",
            category="DECISION", interpretation="Kết quả Shadow được so sánh với Legacy nhưng không thay thế Paper Authority.",
        )
        graph_add(
            "authority", "Paper Authority", "LEGACY", 0.0,
            "Replay and Decision Graph are read-only. Unified remains shadow-only and exposes quantity 0.",
            category="AUTHORITY", interpretation="Legacy tiếp tục là Paper Authority duy nhất.",
        )

        contribution_total = sum(node.contribution for node in graph_nodes)
        if abs(contribution_total - float(record.confidence)) > 1e-9:
            graph_add(
                "confidence_invariant", "Confidence Conservation",
                "GRAPH_CONFIDENCE_INVARIANT_FAILED", 0.0,
                f"Expected={record.confidence:.12g}; actual={contribution_total:.12g}",
                category="INVARIANT", source="REPLAY_VALIDATION",
                interpretation="Tổng confidence mô tả không khớp confidence gốc; graph không hợp lệ để giải thích.",
            )

        final = (
            "REPLAY VERIFIED · READ ONLY"
            if integrity_ok
            else "REPLAY INVALID · INTEGRITY REVIEW REQUIRED"
        )
        add(
            "final",
            "Replay Verdict",
            "VERIFIED" if integrity_ok else "INVALID",
            (
                f"{final}\n"
                f"Profile hash: {record.profile_hash}\n"
                f"Evidence hash: {record.evidence_hash or '-'}\n"
                "Paper Authority remains LEGACY."
            ),
        )
        return QualificationReplaySession(
            request_id=record.request_id,
            symbol=record.symbol,
            valid=integrity_ok,
            integrity_status=record.integrity_status,
            steps=tuple(steps),
            graph_nodes=tuple(graph_nodes),
            final_verdict=final,
        )
    @staticmethod
    def _interpret_reason_code(value: str) -> str:
        token = str(value or "").upper()
        dictionary = (
            ("CMF", "Dòng tiền Chaikin được ghi nhận trong evidence; xem trạng thái PASS/WAIT/BLOCK trong mã lý do."),
            ("RSI", "Động lượng RSI được ghi nhận trong evidence; không nội suy giá trị chỉ báo khi snapshot không lưu giá trị số."),
            ("OI", "Open Interest được dùng để mô tả mức xác nhận của dòng vị thế phái sinh."),
            ("TREND", "Nút xu hướng mô tả mức đồng thuận hướng đi giữa các khung thời gian."),
            ("LIQUID", "Nút thanh khoản mô tả dấu hiệu hấp thụ, quét thanh khoản hoặc vùng phản ứng."),
            ("SPRING", "Sự kiện Wyckoff Spring được quan sát trong evidence đã lưu."),
            ("UPTHRUST", "Sự kiện Wyckoff Upthrust được quan sát trong evidence đã lưu."),
            ("RISK", "Nút quản trị rủi ro có thể chặn quyết định dù tín hiệu thị trường thuận lợi."),
            ("ENTRY", "Nút điểm vào mô tả trạng thái WAIT/READY của điều kiện kích hoạt."),
            ("PAPER", "Ràng buộc Paper Authority bảo đảm Unified không được thực thi lệnh."),
        )
        for marker, explanation in dictionary:
            if marker in token:
                return explanation
        return "Nút giải thích được dựng trực tiếp từ evidence đã lưu; hệ thống không tính lại chiến lược."

