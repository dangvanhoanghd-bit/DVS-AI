from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from dvs_ai.services.quantum_readiness_service import QuantumReadinessSnapshot


class _ReadinessRow(QWidget):
    def __init__(self, label: str, parent=None) -> None:
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setHorizontalSpacing(8)
        self.label = QLabel(label)
        self.value = QLabel("0 / 0")
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(8)
        layout.addWidget(self.label, 0, 0)
        layout.addWidget(self.value, 0, 1)
        layout.addWidget(self.progress, 1, 0, 1, 2)

    def update_value(self, current: int, required: int, percent: int) -> None:
        self.value.setText(f"{current} / {required}")
        self.progress.setValue(percent)


class QuantumReadinessWidget(QFrame):
    """Compact, observe-only progress dashboard for Quantum training readiness."""

    def __init__(self, title: str = "QUANTUM READINESS", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("QuantumReadinessWidget")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(5)
        header = QHBoxLayout()
        self.title = QLabel(f"<b>{title}</b>")
        self.state = QLabel("CHƯA CÓ DỮ LIỆU")
        self.state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.title)
        header.addStretch()
        header.addWidget(self.state)
        root.addLayout(header)
        self.rows: dict[str, _ReadinessRow] = {}
        for key, label in (
            ("eligible", "FULL · VALIDATED · STABLE"),
            ("long", "LONG"), ("short", "SHORT"),
            ("trend", "TREND"), ("range", "RANGE"),
        ):
            row = _ReadinessRow(label)
            self.rows[key] = row
            root.addWidget(row)
        self.detail = QLabel("Đang chờ PAPER outcomes đủ chuẩn.")
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color:#94a3b8;")
        root.addWidget(self.detail)
        self.setMinimumHeight(190)

    def set_snapshot(self, snapshot: QuantumReadinessSnapshot) -> None:
        by_key = {metric.key: metric for metric in snapshot.metrics}
        for key, row in self.rows.items():
            metric = by_key.get(key)
            if metric is not None:
                row.update_value(metric.current, metric.required, metric.percent)
        if snapshot.state == "READY":
            self.state.setText("READY FOR OPTIMIZATION")
            self.state.setStyleSheet("color:#4ade80;font-weight:700;")
        else:
            self.state.setText("ĐANG TÍCH LŨY")
            self.state.setStyleSheet("color:#facc15;font-weight:700;")
        eta = f"{snapshot.eta_days:.1f} ngày" if snapshot.eta_reliable and snapshot.eta_days is not None else "chưa thể ước tính"
        audit = snapshot.audit
        self.detail.setText(
            f"Closed {snapshot.total_closed} · Eligible {snapshot.eligible}/{snapshot.required} · "
            f"Calibration {snapshot.calibration_state} · Reliability {snapshot.reliability_state}\n"
            f"Loại: missing snapshot {audit.get('excluded_missing_snapshot',0)}, invalid {audit.get('excluded_invalid_snapshot',0)}, "
            f"calibration {audit.get('excluded_calibration',0)}, drift {audit.get('excluded_drift',0)}, "
            f"order-flow {audit.get('excluded_order_flow_quality',0)} · ETA {eta}."
        )
