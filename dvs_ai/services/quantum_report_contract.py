from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class QuantumReportView:
    status: str
    text: str
    safe_to_apply_shadow: bool
    schema_valid: bool
    missing_keys: tuple[str, ...] = ()


_REQUIRED_SUCCESS_KEYS = (
    "base_validation", "optimized_validation", "best_params",
    "train_count", "validation_count",
)


def build_quantum_report_view(report: Any) -> QuantumReportView:
    """Validate and render a Quantum report without allowing UI KeyError crashes.

    The contract is fail-closed: an incomplete/unknown success payload is shown as a
    schema mismatch and can never enable SHADOW apply.
    """
    if not isinstance(report, Mapping):
        return QuantumReportView(
            "INVALID_REPORT",
            "Quantum kết thúc nhưng report không phải dictionary hợp lệ.",
            False, False, ("report_mapping",),
        )
    status = str(report.get("status") or "UNKNOWN").upper()
    if status == "CANCELLED":
        return QuantumReportView(status, str(report.get("message") or "Quantum optimizer đã dừng."), False, True)
    if status in {"INSUFFICIENT_DATA", "INSUFFICIENT_QUALITY_DATA"}:
        eligible = int(report.get("closed") or report.get("eligible") or 0)
        total_closed = int(report.get("total_closed") or eligible)
        required = int(report.get("required") or 0)
        audit = report.get("training_audit") if isinstance(report.get("training_audit"), Mapping) else {}
        reasons = []
        for key, label in (
            ("excluded_missing_snapshot", "thiếu evidence snapshot"),
            ("excluded_invalid_snapshot", "snapshot không hợp lệ"),
            ("excluded_calibration", "calibration chưa VALIDATED"),
            ("excluded_drift", "drift chưa STABLE"),
            ("excluded_order_flow_quality", "order-flow chưa FULL"),
        ):
            value = int(audit.get(key) or 0)
            if value:
                reasons.append(f"• {label}: {value}")
        detail = "\n".join(reasons) if reasons else "• Chưa có PAPER outcome đạt đủ điều kiện chất lượng."
        return QuantumReportView(
            status,
            f"QUANTUM CHƯA SẴN SÀNG\n"
            f"Mẫu đủ chuẩn FULL + VALIDATED + STABLE: {eligible}/{required}\n"
            f"Tổng PAPER đã đóng: {total_closed}\n"
            f"{detail}\n"
            "Hành động: tiếp tục Auto PAPER; không đổi threshold và không Apply SHADOW.",
            False, True,
        )
    missing = tuple(key for key in _REQUIRED_SUCCESS_KEYS if key not in report)
    if missing:
        reason = str(report.get("reason") or report.get("message") or "Quantum report thiếu trường validation bắt buộc")
        return QuantumReportView(
            "SCHEMA_MISMATCH",
            f"Quantum kết thúc nhưng report chưa đầy đủ ({status}).\n"
            f"Thiếu: {', '.join(missing)}\nLý do: {reason}",
            False, False, missing,
        )
    try:
        base = report["base_validation"]
        opt = report["optimized_validation"]
        best = report["best_params"]
        text = "\n".join([
            f"Trạng thái: {status}",
            f"Mẫu train/validation: {int(report['train_count'])}/{int(report['validation_count'])}",
            f"Validation hiện tại: WR {float(base['wr']):.1f}% · AvgR {float(base['avg_r']):+.2f} · PF {float(base['pf']):.2f} · n={int(base['n'])}",
            f"Validation đề xuất: WR {float(opt['wr']):.1f}% · AvgR {float(opt['avg_r']):+.2f} · PF {float(opt['pf']):.2f} · n={int(opt['n'])}",
            f"Shadow đề xuất: Conf {float(best['shadow_confidence']):.1f} · Entry {float(best['shadow_entry']):.1f} · Risk≤{float(best['shadow_risk_max']):.1f} · R:R≥{float(best['shadow_rr_min']):.2f}",
            f"Runtime {float(report.get('runtime_seconds',0.0)):.1f}s · Cache peak {int(report.get('fitness_cache_peak',0))}",
            "MAIN giữ nguyên tuyệt đối.",
        ])
    except (KeyError, TypeError, ValueError) as exc:
        return QuantumReportView(
            "SCHEMA_MISMATCH",
            f"Quantum report có schema validation không hợp lệ: {exc}",
            False, False, (str(exc),),
        )
    safe = bool(report.get("safe_to_apply_shadow"))
    return QuantumReportView(status, text, safe, True)
