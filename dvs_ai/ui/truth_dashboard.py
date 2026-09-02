from __future__ import annotations

import json
from pathlib import Path
from dataclasses import asdict, is_dataclass

import time
from typing import Callable, Mapping

from PySide6.QtCore import Qt, QTimer, QObject, QThread, Signal, Slot, QCoreApplication
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dvs_ai.services.candidate_evidence_service import CandidateEvidenceRepository
from dvs_ai.services.truth_trend_store import TruthTrendStore
from dvs_ai.services.operational_validation_service import OperationalValidationPlatform
from dvs_ai.services.testnet_readiness_service import TestnetReadinessAuditService
from dvs_ai.services.operational_journey_service import OperationalJourneyService
from dvs_ai.integration import ScientificBackendBridge, ScientificDashboardPayload


class TruthTrendChart(QWidget):
    """Observe-only line chart sized for long-running historical telemetry."""

    def __init__(self, title: str, series: tuple[str, ...], parent=None):
        super().__init__(parent)
        self.title = title
        self.series = series
        self.rows: list[Mapping] = []
        self.setMinimumHeight(230)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_rows(self, rows) -> None:
        prepared = list(rows or [])
        if prepared == self.rows:
            return
        self.rows = prepared
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0b1220"))
        painter.setPen(QPen(QColor("#263753"), 1))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 8, 8)

        painter.setPen(QPen(QColor("#cbd5e1")))
        painter.drawText(12, 21, self.title)
        left, top, right, bottom = 48, 38, self.width() - 18, self.height() - 30
        if right <= left or bottom <= top:
            return
        painter.setPen(QPen(QColor("#334155")))
        painter.drawRect(left, top, right - left, bottom - top)

        if len(self.rows) < 2:
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(
                left + 12,
                top + 28,
                "Chưa đủ lịch sử · tiếp tục chạy PAPER để tích lũy dữ liệu",
            )
            return

        colors = ("#60a5fa", "#f59e0b", "#ef4444", "#22c55e", "#a78bfa")
        legend_x = left + 8
        for idx, key in enumerate(self.series):
            painter.setPen(QColor(colors[idx % len(colors)]))
            painter.drawText(legend_x, top + 18, key.upper())
            legend_x += max(68, len(key) * 8 + 18)

        for idx, key in enumerate(self.series):
            values: list[float] = []
            for row in self.rows:
                try:
                    value = float(row.get(key, 0.0))
                    values.append(value if value == value and abs(value) != float("inf") else 0.0)
                except Exception:
                    values.append(0.0)
            low, high = min(values), max(values)
            span = max(1e-9, high - low)
            painter.setPen(QPen(QColor(colors[idx % len(colors)]), 2))
            previous = None
            for point_index, value in enumerate(values):
                x = left + (right - left) * point_index / max(1, len(values) - 1)
                y = bottom - (bottom - top) * (value - low) / span
                if previous is not None:
                    painter.drawLine(int(previous[0]), int(previous[1]), int(x), int(y))
                previous = (x, y)


class _TruthCard(QFrame):
    """Commercial status card that cannot collapse below readable height."""

    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("TruthCard")
        self.setMinimumHeight(108)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(5)
        self.title = QLabel(title)
        self.title.setObjectName("TruthCardTitle")
        self.value = QLabel("—")
        self.value.setObjectName("TruthCardValue")
        self.detail = QLabel("Chưa có dữ liệu")
        self.detail.setObjectName("TruthCardDetail")
        self.detail.setWordWrap(True)
        self.detail.setMinimumHeight(30)
        self.detail.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.detail, 1)

    def set_data(self, value: str, detail: str = "", state: str = "neutral") -> None:
        value = value or "—"
        detail = detail or ""
        if self.value.text() != value:
            self.value.setText(value)
        if self.detail.text() != detail:
            self.detail.setText(detail)
        if self.property("state") != state:
            self.setProperty("state", state)
            self.style().unpolish(self)
            self.style().polish(self)


class _TruthDashboardDataWorker(QObject):
    """Load read-only history data without touching any Qt widget."""

    completed = Signal(object)
    failed = Signal(int, str)

    @staticmethod
    def _journey_to_plain(snapshot) -> dict:
        if snapshot is None:
            return {}
        stages = []
        for stage in tuple(getattr(snapshot, "stages", ()) or ()):
            stages.append(
                {
                    "label": str(getattr(stage, "label", "")),
                    "state": str(getattr(stage, "state", "")),
                    "detail": str(getattr(stage, "detail", "")),
                }
            )
        return {
            "stages": stages,
            "health_history": list(
                getattr(snapshot, "health_history", ()) or ()
            ),
            "evidence_history": list(
                getattr(snapshot, "evidence_history", ()) or ()
            ),
        }

    @Slot(object)
    def compute(self, request) -> None:
        generation = int(request.get("generation", 0))
        db_path = str(request.get("db_path", "data/dvs_paper_trades.db"))
        started = time.perf_counter()

        try:
            # Every repository/store is created and consumed in this worker
            # thread. No GUI-owned service or SQLite connection crosses threads.
            trend_store = TruthTrendStore(db_path)
            candidate_repo = CandidateEvidenceRepository()
            journey_service = OperationalJourneyService(db_path)

            drift_rows = list(trend_store.recent("DRIFT", 120) or [])
            reliability_rows = list(
                trend_store.recent("RELIABILITY", 120) or []
            )
            candidate_rows = list(candidate_repo.list_candidates() or [])
            candidate_timeline = list(candidate_repo.timeline() or [])
            historical_rows = list(
                candidate_repo.historical_candidates() or []
            )
            integrity = dict(
                candidate_repo.historical_integrity() or {}
            )
            journey = self._journey_to_plain(
                journey_service.snapshot()
            )

            self.completed.emit(
                {
                    "generation": generation,
                    "worker_duration_ms": round(
                        (time.perf_counter() - started) * 1000.0,
                        3,
                    ),
                    "drift_rows": drift_rows,
                    "reliability_rows": reliability_rows,
                    "candidate_rows": candidate_rows,
                    "candidate_timeline": candidate_timeline,
                    "historical_rows": historical_rows,
                    "integrity": integrity,
                    "journey": journey,
                }
            )
        except Exception as exc:
            self.failed.emit(
                generation,
                f"{type(exc).__name__}: {exc}",
            )


class _TruthOperationalWorker(QObject):
    """Compute operational validation and readiness as plain data only."""

    completed = Signal(object)
    failed = Signal(int, str)

    @staticmethod
    def _plain(value):
        if is_dataclass(value):
            return _TruthOperationalWorker._plain(asdict(value))
        if isinstance(value, Mapping):
            return {
                str(key): _TruthOperationalWorker._plain(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [
                _TruthOperationalWorker._plain(item)
                for item in value
            ]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    @Slot(object)
    def compute(self, request) -> None:
        generation = int(request.get("generation", 0))
        started = time.perf_counter()
        try:
            platform = OperationalValidationPlatform(
                health_weights=request.get("health_weights"),
                regime_modifiers=request.get("regime_modifiers"),
            )
            snapshot = platform.snapshot(
                calibration_state=str(
                    request.get("calibration_state", "NOT_EVALUATED")
                ),
                drift_state=str(
                    request.get("drift_state", "NOT_EVALUATED")
                ),
                reliability_state=str(
                    request.get("reliability_state", "UNKNOWN")
                ),
                runtime_state=str(
                    request.get("runtime_state", "DISABLED")
                ),
                active_regime=str(
                    request.get("active_regime", "UNKNOWN")
                ),
                persist=bool(request.get("persist_health", False)),
            )

            repo = CandidateEvidenceRepository()
            try:
                integrity = dict(repo.historical_integrity() or {})
                candidates = list(repo.historical_candidates() or [])
            except Exception:
                integrity, candidates = {"state": "UNKNOWN"}, []

            candidate = candidates[0] if candidates else {}
            readiness_service = TestnetReadinessAuditService(
                str(request.get("db_path", "data/dvs_paper_trades.db"))
            )
            readiness = readiness_service.evaluate(
                operational=snapshot,
                historical_integrity=integrity,
                candidate_state=str(candidate.get("state", "NONE")),
                candidate_readiness=str(
                    candidate.get("readiness_state", "NOT_EVALUATED")
                ),
                main_immutable=True,
                live_enabled=False,
                testnet_enabled=False,
            )

            self.completed.emit(
                {
                    "generation": generation,
                    "worker_duration_ms": round(
                        (time.perf_counter() - started) * 1000.0,
                        3,
                    ),
                    "persist_health": bool(
                        request.get("persist_health", False)
                    ),
                    "calibration_state": str(
                        request.get(
                            "calibration_state",
                            "NOT_EVALUATED",
                        )
                    ),
                    "runtime_state": str(
                        request.get("runtime_state", "DISABLED")
                    ),
                    "operational": self._plain(snapshot),
                    "readiness": self._plain(readiness),
                }
            )
        except Exception as exc:
            self.failed.emit(
                generation,
                f"{type(exc).__name__}: {exc}",
            )


class _TruthObservationWorker(QObject):
    """Run Shadow Observation diagnostics away from the GUI thread."""

    completed = Signal(object)
    failed = Signal(int, str)

    @Slot(object)
    def compute(self, request) -> None:
        generation = int(request.get("generation", 0))
        provider = request.get("provider")
        started = time.perf_counter()
        try:
            payload = dict(provider() or {}) if callable(provider) else {}
            self.completed.emit({
                "generation": generation,
                "worker_duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
                "observation": payload,
            })
        except Exception as exc:
            self.failed.emit(generation, f"{type(exc).__name__}: {exc}")


class ScientificBackendWorker(QObject):
    """Data-only worker. All scientific backend filesystem I/O stays here."""

    completed = Signal(object)
    failed = Signal(int, str)

    def __init__(self, app_root: Path):
        super().__init__()
        self._bridge = ScientificBackendBridge(app_root=app_root)

    @Slot(object)
    def compute(self, request) -> None:
        generation = int((request or {}).get("generation", 0))
        try:
            payload = self._bridge.build_dashboard_payload(generation)
            self.completed.emit(payload)
        except Exception as exc:
            self.failed.emit(generation, f"{type(exc).__name__}: {exc}")


class TruthDashboard(QWidget):
    """Observe-only commercial monitoring dashboard for truth telemetry."""

    _history_request = Signal(object)
    _operational_request = Signal(object)
    _observation_request = Signal(object)
    _scientific_request = Signal(object)

    FAMILY_NAMES = ("TIMING", "ENTRY", "ORDER_FLOW", "DIRECTION", "MARKET")
    HISTORY_REFRESH_SECONDS = 10.0
    OPERATIONAL_REFRESH_SECONDS = 2.0

    def __init__(
        self,
        parent=None,
        *,
        analysis_provider: Callable[[], object | None] | None = None,
        runtime_provider: Callable[[], Mapping] | None = None,
        observation_provider: Callable[[], Mapping] | None = None,
    ):
        super().__init__(parent)
        self._analysis_provider = analysis_provider or (lambda: None)
        self._runtime_provider = runtime_provider or (lambda: {})
        self._observation_provider = observation_provider or (lambda: {})
        self._observation_generation = 0
        self._observation_running = False
        self._observation_pending = False
        self._observation_cache = {}
        self._observation_applied_generation = 0
        self._last_observation_worker_ms = 0.0
        self._last_analysis = None
        self._last_history_refresh = 0.0
        self._history_request_running = False
        self._history_request_pending = False
        self._history_generation = 0
        self._history_applied_generation = 0
        self._history_shutdown = False
        self._last_history_worker_ms = 0.0
        self._last_history_apply_ms = 0.0
        self._trend_store = TruthTrendStore("data/dvs_paper_trades.db")
        self._candidate_repo = CandidateEvidenceRepository()
        try:
            _op_cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))
        except Exception:
            _op_cfg = {}
        self._operational_health_weights = _op_cfg.get(
            "operational_health_weights"
        )
        self._operational_regime_modifiers = _op_cfg.get(
            "operational_regime_modifiers"
        )
        # Compatibility-only local instance. The normal refresh path uses the
        # data-only worker below.
        self._operational_platform = OperationalValidationPlatform(
            health_weights=self._operational_health_weights,
            regime_modifiers=self._operational_regime_modifiers,
        )
        self._last_operational_snapshot = None
        self._operational_request_running = False
        self._operational_request_pending = False
        self._operational_generation = 0
        self._operational_applied_generation = 0
        self._operational_last_request_monotonic = 0.0
        self._operational_last_signature = None
        self._operational_pending_request = None
        self._last_operational_worker_ms = 0.0
        self._last_operational_apply_ms = 0.0
        self._readiness_service = TestnetReadinessAuditService("data/dvs_paper_trades.db")
        self._last_readiness_snapshot = None
        self._last_health_persist = 0.0
        self._journey_service = OperationalJourneyService("data/dvs_paper_trades.db")
        self._last_journey_snapshot = None
        self._scientific_generation = 0
        self._scientific_applied_generation = 0
        self._scientific_running = False
        self._scientific_pending = False
        self._scientific_payload: ScientificDashboardPayload | None = None
        self._scientific_last_error = ""
        self._history_thread = QThread(self)
        self._history_thread.setObjectName("dvs-truth-data-worker")
        self._history_worker = _TruthDashboardDataWorker()
        self._history_worker.moveToThread(self._history_thread)
        self._history_request.connect(
            self._history_worker.compute,
            Qt.ConnectionType.QueuedConnection,
        )
        self._history_worker.completed.connect(
            self._on_history_data_ready,
            Qt.ConnectionType.QueuedConnection,
        )
        self._history_worker.failed.connect(
            self._on_history_data_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        self._history_thread.finished.connect(
            self._history_worker.deleteLater
        )
        self._history_thread.start()

        self._operational_thread = QThread(self)
        self._operational_thread.setObjectName(
            "dvs-truth-operational-worker"
        )
        self._operational_worker = _TruthOperationalWorker()
        self._operational_worker.moveToThread(
            self._operational_thread
        )
        self._operational_request.connect(
            self._operational_worker.compute,
            Qt.ConnectionType.QueuedConnection,
        )
        self._operational_worker.completed.connect(
            self._on_operational_data_ready,
            Qt.ConnectionType.QueuedConnection,
        )
        self._operational_worker.failed.connect(
            self._on_operational_data_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        self._operational_thread.finished.connect(
            self._operational_worker.deleteLater
        )
        self._operational_thread.start()

        self._observation_thread = QThread(self)
        self._observation_thread.setObjectName("dvs-truth-observation-worker")
        self._observation_worker = _TruthObservationWorker()
        self._observation_worker.moveToThread(self._observation_thread)
        self._observation_request.connect(
            self._observation_worker.compute,
            Qt.ConnectionType.QueuedConnection,
        )
        self._observation_worker.completed.connect(
            self._on_observation_ready,
            Qt.ConnectionType.QueuedConnection,
        )
        self._observation_worker.failed.connect(
            self._on_observation_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        self._observation_thread.finished.connect(
            self._observation_worker.deleteLater
        )
        self._observation_thread.start()

        self._scientific_thread = QThread(self)
        self._scientific_thread.setObjectName("dvs-truth-scientific-worker")
        self._scientific_worker = ScientificBackendWorker(Path.cwd())
        self._scientific_worker.moveToThread(self._scientific_thread)
        self._scientific_request.connect(
            self._scientific_worker.compute,
            Qt.ConnectionType.QueuedConnection,
        )
        self._scientific_worker.completed.connect(
            self._on_scientific_ready,
            Qt.ConnectionType.QueuedConnection,
        )
        self._scientific_worker.failed.connect(
            self._on_scientific_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        self._scientific_thread.finished.connect(self._scientific_worker.deleteLater)
        self._scientific_thread.start()

        application = QCoreApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self.shutdown)

        page = QVBoxLayout(self)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("TruthDashboardScroll")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        page.addWidget(self.scroll_area)

        self.content = QWidget()
        self.content.setObjectName("TruthDashboardContent")
        self.content.setMinimumWidth(760)
        self.content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        root = QVBoxLayout(self.content)
        root.setContentsMargins(14, 12, 14, 18)
        root.setSpacing(14)
        self.scroll_area.setWidget(self.content)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Truth Dashboard · AI Control Center")
        title.setObjectName("TruthDashboardTitle")
        subtitle = QLabel("Sức khỏe dữ liệu, calibration, evidence và vòng đời Candidate")
        subtitle.setObjectName("TruthDashboardNotice")
        self.symbol_label = QLabel("Chưa chọn tín hiệu")
        self.symbol_label.setObjectName("TruthDashboardSymbol")
        self.symbol_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)
        header.addWidget(self.symbol_label)
        root.addLayout(header)

        self.cards_layout = QGridLayout()
        self.cards_layout.setHorizontalSpacing(10)
        self.cards_layout.setVerticalSpacing(10)
        self.scientific_backend_card = _TruthCard("Scientific Backend")
        self.ai_health_card = _TruthCard("AI Health")
        self.calibration_card = _TruthCard("Calibration")
        self.adaptive_card = _TruthCard("Adaptive Probability")
        self.drift_card = _TruthCard("Calibration Drift")
        self.order_flow_card = _TruthCard("Order Flow Quality")
        self.runtime_card = _TruthCard("Order Flow Runtime")
        self.fusion_card = _TruthCard("Evidence Fusion")
        self.observation_card = _TruthCard("Shadow Observation")
        self.history_integrity_card = _TruthCard("Historical Evidence Integrity")
        self.next_action_card = _TruthCard("Next Action")
        self._cards = (
            self.scientific_backend_card,
            self.ai_health_card,
            self.calibration_card,
            self.adaptive_card,
            self.drift_card,
            self.order_flow_card,
            self.runtime_card,
            self.fusion_card,
            self.observation_card,
            self.history_integrity_card,
            self.next_action_card,
        )
        self._card_columns = 0
        self._reflow_cards(4)
        root.addLayout(self.cards_layout)

        journey_group = self._group("AI Journey & Operational History")
        journey_layout = QVBoxLayout(journey_group)
        journey_layout.setContentsMargins(10, 16, 10, 10)
        journey_layout.setSpacing(9)
        self.journey_timeline = QLabel("PAPER → CALIBRATION → RELIABILITY → QUANTUM → SHADOW PROMOTION → MAIN")
        self.journey_timeline.setObjectName("TruthTimeline")
        self.journey_timeline.setWordWrap(True)
        self.journey_timeline.setMinimumHeight(62)
        journey_layout.addWidget(self.journey_timeline)
        self.health_history_chart = TruthTrendChart("AI Health History", ("score",))
        self.evidence_history_chart = TruthTrendChart("Evidence Outcome Accumulation", ("outcomes",))
        journey_layout.addWidget(self.health_history_chart)
        journey_layout.addWidget(self.evidence_history_chart)
        root.addWidget(journey_group)

        reliability_group = self._group("Evidence Reliability")
        reliability_layout = QVBoxLayout(reliability_group)
        reliability_layout.setContentsMargins(10, 16, 10, 10)
        self.reliability_table = QTableWidget(0, 4)
        self._configure_table(self.reliability_table, min_height=190)
        self.reliability_table.setHorizontalHeaderLabels(
            ["Family", "State", "Reliability", "Effective samples"]
        )
        header_view = self.reliability_table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            header_view.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.reliability_empty = QLabel("Chưa có evidence snapshot đủ điều kiện để tính reliability.")
        self.reliability_empty.setObjectName("TruthDashboardNotice")
        self.reliability_empty.setWordWrap(True)
        reliability_layout.addWidget(self.reliability_empty)
        reliability_layout.addWidget(self.reliability_table)
        root.addWidget(reliability_group)

        operational_group = self._group("Operational Validation Center")
        operational_layout = QVBoxLayout(operational_group)
        operational_layout.setContentsMargins(10, 16, 10, 10)
        operational_layout.setSpacing(10)
        operational_summary = QHBoxLayout()
        self.coverage_summary = QLabel("Coverage: chưa có dữ liệu")
        self.confidence_summary = QLabel("Confidence: chưa có dữ liệu")
        self.regime_summary = QLabel("Regime: chưa có dữ liệu")
        for label in (self.coverage_summary, self.confidence_summary, self.regime_summary):
            label.setObjectName("OperationalSummary")
            label.setWordWrap(True)
            label.setMinimumHeight(58)
            operational_summary.addWidget(label, 1)
        operational_layout.addLayout(operational_summary)

        self.coverage_table = QTableWidget(0, 3)
        self._configure_table(self.coverage_table, min_height=160)
        self.coverage_table.setHorizontalHeaderLabels(["Dimension", "Samples", "State"])
        self.coverage_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2):
            self.coverage_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        operational_layout.addWidget(self.coverage_table)

        self.confidence_table = QTableWidget(0, 3)
        self._configure_table(self.confidence_table, min_height=150)
        self.confidence_table.setHorizontalHeaderLabels(["Confidence bucket", "Signals", "Share"])
        self.confidence_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2):
            self.confidence_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        operational_layout.addWidget(self.confidence_table)

        self.regime_table = QTableWidget(0, 5)
        self._configure_table(self.regime_table, min_height=170)
        self.regime_table.setHorizontalHeaderLabels(["Regime", "Samples", "Baseline Exp", "Shadow Exp", "State"])
        self.regime_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3, 4):
            self.regime_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        operational_layout.addWidget(self.regime_table)

        self.alert_table = QTableWidget(0, 4)
        self._configure_table(self.alert_table, min_height=190)
        self.alert_table.setHorizontalHeaderLabels(["Severity", "Alert", "Reason", "Recommended action"])
        self.alert_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.alert_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.alert_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.alert_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        operational_layout.addWidget(self.alert_table)
        root.addWidget(operational_group)

        readiness_group = self._group("Testnet Readiness Audit · Observe Only")
        readiness_layout = QVBoxLayout(readiness_group)
        readiness_layout.setContentsMargins(10, 16, 10, 10)
        readiness_layout.setSpacing(8)
        self.readiness_summary = QLabel("Testnet Readiness: chưa đánh giá")
        self.readiness_summary.setObjectName("OperationalSummary")
        self.readiness_summary.setWordWrap(True)
        self.readiness_summary.setMinimumHeight(64)
        readiness_layout.addWidget(self.readiness_summary)
        self.readiness_table = QTableWidget(0, 5)
        self._configure_table(self.readiness_table, min_height=210)
        self.readiness_table.setHorizontalHeaderLabels(["Dimension", "Rule", "State", "Score", "Recommendation"])
        for column in range(4):
            self.readiness_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.readiness_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        readiness_layout.addWidget(self.readiness_table)
        self.readiness_notice = QLabel("Không có nút Enable Testnet. READY chỉ mở một vòng human review riêng.")
        self.readiness_notice.setObjectName("TruthDashboardNotice")
        self.readiness_notice.setWordWrap(True)
        readiness_layout.addWidget(self.readiness_notice)
        root.addWidget(readiness_group)

        trends = self._group("Historical Truth Trends")
        trends_layout = QVBoxLayout(trends)
        trends_layout.setContentsMargins(10, 16, 10, 10)
        trends_layout.setSpacing(10)
        self.drift_chart = TruthTrendChart(
            "Calibration Drift · Brier/ECE/PSI",
            ("brier_delta", "ece_delta", "psi"),
        )
        self.reliability_chart = TruthTrendChart(
            "Evidence Reliability History",
            ("timing", "entry", "order_flow", "direction", "market"),
        )
        trends_layout.addWidget(self.drift_chart)
        trends_layout.addWidget(self.reliability_chart)
        root.addWidget(trends)

        candidate_group = self._group("Candidate Center")
        candidate_layout = QVBoxLayout(candidate_group)
        candidate_layout.setContentsMargins(10, 16, 10, 10)
        candidate_layout.setSpacing(8)
        self.candidate_table = QTableWidget(0, 6)
        self._configure_table(self.candidate_table, min_height=190)
        self.candidate_table.setHorizontalHeaderLabels(
            ["Candidate", "Backtest", "Comparison", "Score", "Promotion", "Created"]
        )
        candidate_header = self.candidate_table.horizontalHeader()
        candidate_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 6):
            candidate_header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.promotion_timeline = QLabel("Chưa có candidate/promotion history")
        self.promotion_timeline.setObjectName("TruthTimeline")
        self.promotion_timeline.setWordWrap(True)
        self.promotion_timeline.setMinimumHeight(54)
        candidate_layout.addWidget(self.candidate_table)
        candidate_layout.addWidget(self.promotion_timeline)
        root.addWidget(candidate_group)

        history_group = self._group("Historical Candidate Performance")
        history_layout = QVBoxLayout(history_group)
        history_layout.setContentsMargins(10, 16, 10, 10)
        history_layout.setSpacing(9)

        self.history_splitter = QSplitter(Qt.Orientation.Vertical)
        self.history_splitter.setChildrenCollapsible(False)
        self.history_splitter.setHandleWidth(5)

        tables_panel = QWidget()
        tables_layout = QVBoxLayout(tables_panel)
        tables_layout.setContentsMargins(0, 0, 0, 0)
        tables_layout.setSpacing(8)
        self.history_table = QTableWidget(0, 10)
        self._configure_table(self.history_table, min_height=220, select_rows=True)
        self.history_table.setHorizontalHeaderLabels([
            "Candidate", "Lifecycle", "Obs", "Expectancy", "Drawdown",
            "Win rate", "Profit factor", "Brier", "Reliability", "Coverage",
        ])
        self._configure_history_header(self.history_table)
        self.history_table.itemSelectionChanged.connect(self._refresh_candidate_history_chart)
        tables_layout.addWidget(QLabel("Candidate snapshots"))
        tables_layout.addWidget(self.history_table)

        self.history_comparison_table = QTableWidget(0, 8)
        self._configure_table(self.history_comparison_table, min_height=190)
        self.history_comparison_table.setHorizontalHeaderLabels([
            "Rank", "Candidate", "Readiness", "Expectancy", "Drawdown", "Brier", "Coverage", "Snapshots",
        ])
        comparison_header = self.history_comparison_table.horizontalHeader()
        comparison_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        comparison_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for column in (0, 3, 4, 5, 6, 7):
            comparison_header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        tables_layout.addWidget(QLabel("Ranked historical comparison"))
        tables_layout.addWidget(self.history_comparison_table)

        detail_panel = QWidget()
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(8)
        self.candidate_lifecycle_detail = QLabel(
            "Chọn Candidate để xem lifecycle/readiness timeline"
        )
        self.candidate_lifecycle_detail.setObjectName("TruthTimeline")
        self.candidate_lifecycle_detail.setWordWrap(True)
        self.candidate_lifecycle_detail.setMinimumHeight(70)
        self.candidate_history_chart = TruthTrendChart(
            "Candidate Performance · Expectancy / Drawdown / Brier / ECE",
            ("expectancy", "max_drawdown", "brier", "ece"),
        )
        detail_layout.addWidget(self.candidate_lifecycle_detail)
        detail_layout.addWidget(self.candidate_history_chart)

        self.history_splitter.addWidget(tables_panel)
        self.history_splitter.addWidget(detail_panel)
        self.history_splitter.setSizes([470, 320])
        history_layout.addWidget(self.history_splitter)
        root.addWidget(history_group)

        self.notice = QLabel(
            "OBSERVE-ONLY · Dashboard không thay đổi confidence, gate, sizing, SHADOW, MAIN hoặc Execution."
        )
        self.notice.setObjectName("TruthDashboardNotice")
        self.notice.setWordWrap(True)
        root.addWidget(self.notice)

        # RC7.3: hidden diagnostics are quiescent. Worker results may finish,
        # but QWidget mutation is deferred until this workspace is visible.
        self._active = False
        self._pending_history_payload = None
        self._pending_operational_payload = None
        self._pending_scientific_payload = None
        self._pending_history_error = None
        self._pending_operational_error = None
        self._pending_scientific_error = None
        self._refresh_pending_while_hidden = True

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)

    def set_active(self, active: bool) -> None:
        active = bool(active)
        if self._active == active:
            return
        self._active = active
        if not active:
            self.timer.stop()
            self._refresh_pending_while_hidden = True
            return

        if not self.timer.isActive():
            self.timer.start()

        if self._pending_history_payload is not None:
            payload = self._pending_history_payload
            self._pending_history_payload = None
            self._pending_history_error = None
            self._apply_history_data(payload)
        elif self._pending_history_error:
            self.history_integrity_card.set_data(
                "ERROR",
                self._pending_history_error,
                "critical",
            )
            self._pending_history_error = None

        if self._pending_operational_payload is not None:
            payload = self._pending_operational_payload
            self._pending_operational_payload = None
            self._pending_operational_error = None
            self._apply_operational_data(payload)
        elif self._pending_operational_error:
            self.ai_health_card.set_data(
                "ERROR",
                self._pending_operational_error,
                "critical",
            )
            self._pending_operational_error = None

        if self._pending_scientific_payload is not None:
            payload = self._pending_scientific_payload
            self._pending_scientific_payload = None
            self._pending_scientific_error = None
            self._commit_scientific_payload(payload)
        elif self._pending_scientific_error:
            self.scientific_backend_card.set_data(
                "UNAVAILABLE",
                self._pending_scientific_error,
                "critical",
            )
            self._pending_scientific_error = None

        force_history = self._refresh_pending_while_hidden
        self._refresh_pending_while_hidden = False
        QTimer.singleShot(
            0,
            lambda: self.refresh(force_history=force_history),
        )

    def is_active(self) -> bool:
        return bool(self._active)

    def _request_history_data(self) -> None:
        if self._history_shutdown:
            return
        if self._history_request_running:
            self._history_request_pending = True
            return

        self._history_request_running = True
        self._history_request_pending = False
        self._history_generation += 1
        self._history_request.emit(
            {
                "generation": self._history_generation,
                "db_path": "data/dvs_paper_trades.db",
            }
        )

    @Slot(object)
    def _on_history_data_ready(self, payload) -> None:
        self._history_request_running = False
        generation = int(payload.get("generation", 0))

        # A late result must never overwrite a newer requested generation.
        if generation >= self._history_applied_generation:
            self._history_applied_generation = generation
            self._last_history_worker_ms = float(
                payload.get("worker_duration_ms", 0.0) or 0.0
            )
            if self._active:
                self._apply_history_data(payload)
            else:
                self._pending_history_payload = dict(payload)
                self._refresh_pending_while_hidden = True

        if self._history_request_pending and not self._history_shutdown:
            self._history_request_pending = False
            QTimer.singleShot(0, self._request_history_data)

    @Slot(int, str)
    def _on_history_data_failed(
        self,
        generation: int,
        message: str,
    ) -> None:
        self._history_request_running = False
        if generation >= self._history_applied_generation:
            if self._active:
                self.history_integrity_card.set_data(
                    "ERROR",
                    message,
                    "critical",
                )
                self.journey_timeline.setText(
                    f"Operational journey unavailable: {message}"
                )
            else:
                self._pending_history_error = str(message)
                self._refresh_pending_while_hidden = True

        if self._history_request_pending and not self._history_shutdown:
            self._history_request_pending = False
            QTimer.singleShot(0, self._request_history_data)

    def _apply_history_data(self, payload: Mapping) -> None:
        started = time.perf_counter()

        self.drift_chart.set_rows(payload.get("drift_rows", ()))
        self.reliability_chart.set_rows(
            payload.get("reliability_rows", ())
        )
        self._apply_candidate_rows(
            payload.get("candidate_rows", ()),
            payload.get("candidate_timeline", ()),
        )

        historical_rows = list(
            payload.get("historical_rows", ()) or []
        )
        self._apply_historical_rows(historical_rows)
        self._apply_integrity_and_comparison(
            dict(payload.get("integrity", {}) or {}),
            historical_rows,
        )
        self._apply_journey(
            dict(payload.get("journey", {}) or {})
        )

        self._last_history_apply_ms = round(
            (time.perf_counter() - started) * 1000.0,
            3,
        )

    def _apply_candidate_rows(self, rows, timeline) -> None:
        rows = list(rows or [])
        timeline = list(timeline or [])
        self.candidate_table.setUpdatesEnabled(False)
        self.candidate_table.blockSignals(True)
        try:
            self.candidate_table.setRowCount(len(rows))
            for row, payload in enumerate(rows):
                values = (
                    payload.get("candidate_id", "—"),
                    payload.get("backtest_state", "PENDING"),
                    payload.get(
                        "comparison_state",
                        "INSUFFICIENT_DATA",
                    ),
                    f"{float(payload.get('comparison_score', 0.0)):.2f}",
                    payload.get("promotion_state", "PENDING"),
                    payload.get("created_at", ""),
                )
                for col, value in enumerate(values):
                    item = self.candidate_table.item(row, col)
                    if item is None:
                        item = QTableWidgetItem()
                        self.candidate_table.setItem(row, col, item)
                    item.setText(str(value))
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter
                    )
        finally:
            self.candidate_table.blockSignals(False)
            self.candidate_table.setUpdatesEnabled(True)

        self.promotion_timeline.setText(
            "  →  ".join(
                f"{item.get('candidate_id')} · {item.get('state')}"
                for item in timeline[-8:]
            )
            if timeline
            else "Chưa có Candidate. Quantum cần đủ dữ liệu truth-qualified trước khi tạo đề xuất SHADOW."
        )

    def _apply_historical_rows(self, rows) -> None:
        rows = list(rows or [])
        selected = None
        current = self.history_table.currentRow()
        if 0 <= current < self.history_table.rowCount():
            item = self.history_table.item(current, 0)
            selected = item.text() if item else None

        self.history_table.setUpdatesEnabled(False)
        self.history_table.blockSignals(True)
        try:
            self.history_table.setRowCount(len(rows))
            selected_row = -1
            for row, payload in enumerate(rows):
                values = (
                    payload.get("candidate_id", "—"),
                    payload.get("state", "CREATED"),
                    int(payload.get("observations", 0) or 0),
                    f"{float(payload.get('expectancy', 0.0)):+.3f}",
                    f"{float(payload.get('max_drawdown', 0.0)):.3f}",
                    f"{float(payload.get('win_rate', 0.0)) * 100:.1f}%",
                    f"{float(payload.get('profit_factor', 0.0)):.2f}",
                    f"{float(payload.get('brier', 0.0)):.3f}",
                    f"{float(payload.get('reliability', 0.0)) * 100:.1f}%",
                    f"{float(payload.get('coverage', 0.0)) * 100:.1f}%",
                )
                for col, value in enumerate(values):
                    item = self.history_table.item(row, col)
                    if item is None:
                        item = QTableWidgetItem()
                        self.history_table.setItem(row, col, item)
                    item.setText(str(value))
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter
                    )
                if selected and str(values[0]) == selected:
                    selected_row = row
        finally:
            self.history_table.blockSignals(False)
            self.history_table.setUpdatesEnabled(True)

        if selected_row < 0 and rows:
            selected_row = 0
        if selected_row >= 0:
            self.history_table.selectRow(selected_row)
        else:
            self.candidate_history_chart.set_rows([])
            self.candidate_lifecycle_detail.setText(
                "Chưa có historical snapshot. Snapshot sẽ xuất hiện sau khi đủ observation hợp lệ."
            )

    def _apply_integrity_and_comparison(
        self,
        integrity,
        rows,
    ) -> None:
        state = str(integrity.get("state", "UNKNOWN")).upper()
        detail = (
            f"Candidates {integrity.get('candidates', 0)} · "
            f"lifecycle {integrity.get('lifecycle_events', 0)} · "
            f"snapshots {integrity.get('snapshots', 0)} · "
            f"readiness {integrity.get('readiness_events', 0)}"
        )
        issues = tuple(integrity.get("issues", ()) or ())
        if issues:
            detail += " · " + "; ".join(
                str(item) for item in issues[:2]
            )
        self.history_integrity_card.set_data(
            state,
            detail,
            "good"
            if state == "PASS"
            else "critical"
            if state in {"FAIL", "ERROR"}
            else "neutral",
        )

        self.history_comparison_table.setUpdatesEnabled(False)
        self.history_comparison_table.blockSignals(True)
        try:
            self.history_comparison_table.setRowCount(len(rows))
            for row, payload in enumerate(rows):
                values = (
                    row + 1,
                    payload.get("candidate_id", "—"),
                    payload.get(
                        "readiness_state",
                        "NOT_EVALUATED",
                    ),
                    f"{float(payload.get('expectancy', 0.0)):+.3f}",
                    f"{float(payload.get('max_drawdown', 0.0)):.3f}",
                    f"{float(payload.get('brier', 0.0)):.3f}",
                    f"{float(payload.get('coverage', 0.0)) * 100:.1f}%",
                    int(payload.get("snapshots", 0) or 0),
                )
                for col, value in enumerate(values):
                    item = self.history_comparison_table.item(row, col)
                    if item is None:
                        item = QTableWidgetItem()
                        self.history_comparison_table.setItem(
                            row,
                            col,
                            item,
                        )
                    item.setText(str(value))
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter
                    )
        finally:
            self.history_comparison_table.blockSignals(False)
            self.history_comparison_table.setUpdatesEnabled(True)

    def _apply_journey(self, journey: Mapping) -> None:
        stages = list(journey.get("stages", ()) or [])
        parts = []
        for stage in stages:
            state = str(stage.get("state", ""))
            marker = (
                "✓"
                if state in {"COMPLETE", "READY"}
                else "🔒"
                if state in {"LOCKED", "IMMUTABLE"}
                else "●"
            )
            parts.append(
                f"{marker} {stage.get('label', '')}: "
                f"{state} ({stage.get('detail', '')})"
            )
        self.journey_timeline.setText(
            "  →  ".join(parts)
            if parts
            else "Operational journey unavailable"
        )
        self.health_history_chart.set_rows(
            journey.get("health_history", ())
        )
        self.evidence_history_chart.set_rows(
            journey.get("evidence_history", ())
        )

    def _operational_request_payload(
        self,
        analysis,
        runtime_state: str,
    ) -> dict:
        calibration = str(
            getattr(
                analysis,
                "probability_calibration_state",
                "NOT_EVALUATED",
            )
            if analysis
            else "NOT_EVALUATED"
        ).upper()
        drift = str(
            getattr(
                analysis,
                "calibration_drift_state",
                "NOT_EVALUATED",
            )
            if analysis
            else "NOT_EVALUATED"
        ).upper()
        reliability = str(
            getattr(
                analysis,
                "evidence_reliability_state",
                "UNKNOWN",
            )
            if analysis
            else "UNKNOWN"
        ).upper()
        regime = str(
            getattr(
                getattr(analysis, "regime", None),
                "regime",
                "UNKNOWN",
            )
        )
        now = time.monotonic()
        persist_health = (
            now - self._last_health_persist >= 60.0
        )
        return {
            "db_path": "data/dvs_paper_trades.db",
            "calibration_state": calibration,
            "drift_state": drift,
            "reliability_state": reliability,
            "runtime_state": str(runtime_state).upper(),
            "active_regime": regime,
            "persist_health": persist_health,
            "health_weights": self._operational_health_weights,
            "regime_modifiers": self._operational_regime_modifiers,
        }

    def _request_operational_data(
        self,
        analysis,
        runtime_state: str,
        *,
        force: bool = False,
    ) -> None:
        if self._history_shutdown:
            return

        payload = self._operational_request_payload(
            analysis,
            runtime_state,
        )
        signature = (
            payload["calibration_state"],
            payload["drift_state"],
            payload["reliability_state"],
            payload["runtime_state"],
            payload["active_regime"],
            bool(payload["persist_health"]),
        )
        now = time.monotonic()
        if (
            not force
            and signature == self._operational_last_signature
            and now - self._operational_last_request_monotonic
            < self.OPERATIONAL_REFRESH_SECONDS
        ):
            return

        self._operational_last_signature = signature
        self._operational_last_request_monotonic = now
        self._operational_generation += 1
        payload["generation"] = self._operational_generation

        if self._operational_request_running:
            self._operational_request_pending = True
            self._operational_pending_request = payload
            return

        self._operational_request_running = True
        self._operational_request_pending = False
        self._operational_pending_request = None
        self._operational_request.emit(payload)

    @Slot(object)
    def _on_operational_data_ready(self, payload) -> None:
        self._operational_request_running = False
        generation = int(payload.get("generation", 0))
        if generation >= self._operational_applied_generation:
            self._operational_applied_generation = generation
            self._last_operational_worker_ms = float(
                payload.get("worker_duration_ms", 0.0) or 0.0
            )
            if bool(payload.get("persist_health", False)):
                self._last_health_persist = time.monotonic()
            if self._active:
                self._apply_operational_data(payload)
            else:
                self._pending_operational_payload = dict(payload)
                self._refresh_pending_while_hidden = True

        if (
            self._operational_request_pending
            and not self._history_shutdown
        ):
            pending = self._operational_pending_request
            self._operational_request_pending = False
            self._operational_pending_request = None
            if pending is not None:
                self._operational_request_running = True
                self._operational_request.emit(pending)

    @Slot(int, str)
    def _on_operational_data_failed(
        self,
        generation: int,
        message: str,
    ) -> None:
        self._operational_request_running = False
        if generation >= self._operational_applied_generation:
            if self._active:
                self.ai_health_card.set_data(
                    "ERROR",
                    message,
                    "critical",
                )
                self.next_action_card.set_data(
                    "Kiểm tra Operational Validation",
                    message,
                    "critical",
                )
                self.readiness_summary.setText(
                    f"READINESS ERROR · {message}"
                )
            else:
                self._pending_operational_error = str(message)
                self._refresh_pending_while_hidden = True

        if (
            self._operational_request_pending
            and not self._history_shutdown
        ):
            pending = self._operational_pending_request
            self._operational_request_pending = False
            self._operational_pending_request = None
            if pending is not None:
                self._operational_request_running = True
                self._operational_request.emit(pending)

    def _apply_operational_data(self, payload: Mapping) -> None:
        started = time.perf_counter()
        snapshot = dict(payload.get("operational", {}) or {})
        readiness = dict(payload.get("readiness", {}) or {})
        calibration = str(
            payload.get("calibration_state", "NOT_EVALUATED")
        ).upper()
        runtime_state = str(
            payload.get("runtime_state", "DISABLED")
        ).upper()

        health = dict(snapshot.get("health", {}) or {})
        coverage = dict(snapshot.get("coverage", {}) or {})
        confidence = dict(snapshot.get("confidence", {}) or {})
        regimes = dict(snapshot.get("regimes", {}) or {})

        learning_only = (
            int(coverage.get("eligible", 0) or 0) < 30
            and calibration
            in {
                "UNKNOWN",
                "NOT_EVALUATED",
                "INSUFFICIENT_DATA",
            }
            and runtime_state not in {"ERROR", "BLOCKED"}
        )
        health_state_raw = str(
            health.get("state", "UNKNOWN")
        ).upper()
        display_state = (
            "LEARNING" if learning_only else health_state_raw
        )
        health_state = (
            "warning"
            if learning_only
            else "good"
            if health_state_raw in {"HEALTHY", "STABLE"}
            else "warning"
            if health_state_raw == "WATCH"
            else "critical"
        )
        contributors = dict(
            health.get("contributors", {}) or {}
        )
        contributor_text = " · ".join(
            f"{str(key).replace('_', ' ').title()} {float(value):.0f}"
            for key, value in contributors.items()
        )
        if learning_only:
            contributor_text = (
                f"Operational score {float(health.get('score', 0.0)):.0f}/100 · "
                "Chưa đủ outcome để đánh giá sức khỏe mô hình · "
                + contributor_text
            )
        self.ai_health_card.set_data(
            f"{float(health.get('score', 0.0)):.0f}/100 · {display_state}",
            contributor_text,
            health_state,
        )

        alerts = list(health.get("alerts", ()) or [])
        next_action = str(
            health.get("next_action", "Tiếp tục observation")
        )
        self.next_action_card.set_data(
            "ACTION",
            next_action,
            "critical"
            if alerts
            and str(alerts[0].get("severity", "")).upper()
            == "CRITICAL"
            else "warning"
            if alerts
            else "good",
        )

        self.coverage_summary.setText(
            f"Coverage · {coverage.get('state', 'UNKNOWN')}\n"
            f"Eligible {int(coverage.get('eligible', 0) or 0)}/"
            f"{int(coverage.get('total', 0) or 0)} · "
            f"Regime {float(coverage.get('regime_coverage', 0.0))*100:.0f}% · "
            f"Direction {float(coverage.get('direction_coverage', 0.0))*100:.0f}%"
        )
        coverage_rows = [
            (
                f"Regime · {key}",
                value,
                "PASS" if int(value or 0) >= 15 else "LOW",
            )
            for key, value in sorted(
                dict(coverage.get("regimes", {}) or {}).items()
            )
        ]
        coverage_rows += [
            (
                f"Direction · {key}",
                value,
                "PASS" if int(value or 0) >= 20 else "LOW",
            )
            for key, value in sorted(
                dict(coverage.get("directions", {}) or {}).items()
            )
        ]
        coverage_rows += [
            (f"Order Flow · {key}", value, key)
            for key, value in sorted(
                dict(
                    coverage.get(
                        "order_flow_quality",
                        {},
                    )
                    or {}
                ).items()
            )
        ]
        self.coverage_table.setUpdatesEnabled(False)
        try:
            self.coverage_table.setRowCount(len(coverage_rows))
            for row, values in enumerate(coverage_rows):
                for col, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter
                    )
                    self.coverage_table.setItem(row, col, item)
        finally:
            self.coverage_table.setUpdatesEnabled(True)

        samples = int(confidence.get("samples", 0) or 0)
        self.confidence_summary.setText(
            f"Confidence · {confidence.get('state', 'UNKNOWN')}\n"
            f"Samples {samples} · "
            f"Mean {float(confidence.get('mean', 0.0)):.1f} · "
            f"Median {float(confidence.get('median', 0.0)):.1f} · "
            f"P90 {float(confidence.get('p90', 0.0)):.1f} · "
            f"≥70 {float(confidence.get('acceptance_70', 0.0))*100:.2f}%"
        )
        histogram = dict(confidence.get("histogram", {}) or {})
        total = max(1, samples)
        self.confidence_table.setUpdatesEnabled(False)
        try:
            self.confidence_table.setRowCount(len(histogram))
            for row, (bucket, count) in enumerate(
                histogram.items()
            ):
                for col, value in enumerate(
                    (
                        bucket,
                        count,
                        f"{int(count or 0)/total*100:.1f}%",
                    )
                ):
                    item = QTableWidgetItem(str(value))
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter
                    )
                    self.confidence_table.setItem(row, col, item)
        finally:
            self.confidence_table.setUpdatesEnabled(True)

        metrics = list(regimes.get("metrics", ()) or [])
        self.regime_summary.setText(
            f"Regime Validation · {regimes.get('state', 'UNKNOWN')}\n"
            f"Supported regimes {regimes.get('supported_regimes', 0)} · "
            + (
                "; ".join(
                    str(item)
                    for item in list(
                        regimes.get("reasons", ()) or []
                    )[:2]
                )
                or "Tiếp tục observation"
            )
        )
        self.regime_table.setUpdatesEnabled(False)
        try:
            self.regime_table.setRowCount(len(metrics))
            for row, metric in enumerate(metrics):
                values = (
                    metric.get("regime", "UNKNOWN"),
                    metric.get("samples", 0),
                    f"{float(metric.get('baseline_expectancy', 0.0)):+.3f}R",
                    f"{float(metric.get('shadow_expectancy', 0.0)):+.3f}R",
                    metric.get("state", "UNKNOWN"),
                )
                for col, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter
                    )
                    self.regime_table.setItem(row, col, item)
        finally:
            self.regime_table.setUpdatesEnabled(True)

        self.alert_table.setUpdatesEnabled(False)
        try:
            self.alert_table.setRowCount(len(alerts))
            for row, alert in enumerate(alerts):
                values = (
                    alert.get("severity", ""),
                    alert.get("title", ""),
                    alert.get("reason", ""),
                    alert.get("action", ""),
                )
                for col, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if col == 0:
                        severity = str(
                            alert.get("severity", "")
                        ).upper()
                        item.setForeground(
                            QColor(
                                "#ef4444"
                                if severity == "CRITICAL"
                                else "#f59e0b"
                                if severity == "WARNING"
                                else "#60a5fa"
                            )
                        )
                    self.alert_table.setItem(row, col, item)
        finally:
            self.alert_table.setUpdatesEnabled(True)

        self.readiness_summary.setText(
            f"{readiness.get('state', 'UNKNOWN')} · "
            f"{float(readiness.get('score', 0.0)):.1f}/100\n"
            f"{readiness.get('recommendation', '')}"
        )
        rules = list(readiness.get("rules", ()) or [])
        self.readiness_table.setUpdatesEnabled(False)
        try:
            self.readiness_table.setRowCount(len(rules))
            for row, rule in enumerate(rules):
                values = (
                    rule.get("dimension", ""),
                    rule.get("code", ""),
                    rule.get("state", ""),
                    f"{float(rule.get('score', 0.0))*100:.0f}%",
                    rule.get("recommendation", ""),
                )
                for col, value in enumerate(values):
                    item = self.readiness_table.item(row, col)
                    if item is None:
                        item = QTableWidgetItem()
                        self.readiness_table.setItem(
                            row,
                            col,
                            item,
                        )
                    item.setText(str(value))
        finally:
            self.readiness_table.setUpdatesEnabled(True)

        self._last_operational_snapshot = snapshot
        self._last_readiness_snapshot = readiness
        self._last_operational_apply_ms = round(
            (time.perf_counter() - started) * 1000.0,
            3,
        )

    @staticmethod
    def _group(title: str) -> QGroupBox:
        group = QGroupBox(title)
        group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return group

    @staticmethod
    def _configure_table(
        table: QTableWidget,
        *,
        min_height: int,
        select_rows: bool = False,
    ) -> None:
        table.setMinimumHeight(min_height)
        table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(27)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
            if select_rows
            else QAbstractItemView.SelectionBehavior.SelectItems
        )
        table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
            if select_rows
            else QAbstractItemView.SelectionMode.NoSelection
        )
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    @staticmethod
    def _configure_history_header(table: QTableWidget) -> None:
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in range(2, 10):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

    def _reflow_cards(self, columns: int) -> None:
        columns = max(2, min(4, int(columns)))
        if columns == self._card_columns:
            return
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(self.content)
        self._card_columns = columns
        for index, card in enumerate(self._cards):
            self.cards_layout.addWidget(card, index // columns, index % columns)
        for column in range(columns):
            self.cards_layout.setColumnStretch(column, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = event.size().width()
        self._reflow_cards(2 if width < 1050 else 3 if width < 1500 else 4)

    @staticmethod
    def _state_color(state: str) -> str:
        value = str(state or "").upper()
        if value in {"VALIDATED", "STABLE", "FULL", "CONNECTED", "READY", "PASS", "HEALTHY"}:
            return "good"
        if value in {"WATCH", "DEGRADED", "SHRUNK", "CONNECTING", "BACKOFF", "LEARNING", "CONTINUE_OBSERVATION"}:
            return "warning"
        if value in {"DRIFT", "BLOCKED", "ERROR", "REJECTED_VALIDATION", "FAIL", "UNHEALTHY"}:
            return "critical"
        return "neutral"

    @staticmethod
    def _safe_float(value, default=0.0) -> float:
        try:
            number = float(value)
            return number if number == number and abs(number) != float("inf") else default
        except (TypeError, ValueError):
            return default

    def set_analysis(self, analysis) -> None:
        self._last_analysis = analysis
        if self._active:
            self.refresh(force_history=False)
        else:
            self._refresh_pending_while_hidden = True

    def _analysis(self):
        return self._analysis_provider() or self._last_analysis

    def _order_flow_gate(self, analysis) -> tuple[str, str]:
        footprint = getattr(analysis, "footprint", None)
        components = tuple(getattr(footprint, "components", ()) or ())
        for component in components:
            metadata = dict(getattr(component, "metadata", {}) or {})
            gate = metadata.get("order_flow_quality_gate")
            if gate:
                multiplier = self._safe_float(metadata.get("order_flow_confidence_multiplier", 0.0))
                reasons = metadata.get("order_flow_quality_reasons", ()) or ()
                detail = f"Multiplier {multiplier:.2f}"
                if reasons:
                    detail += " · " + ", ".join(str(x) for x in reasons[:2])
                return str(gate).upper(), detail
        gate = str(getattr(analysis, "microstructure_gate", "NOT_AVAILABLE"))
        return gate, "Không có metadata order-flow trực tiếp"

    def _refresh_reliability(self, analysis) -> None:
        parsed = {}
        for raw in tuple(getattr(analysis, "evidence_reliability_summary", ()) or ()):
            parts = str(raw).split(":")
            if len(parts) >= 4:
                parsed[parts[0].upper()] = parts[1:4]
        self.reliability_empty.setVisible(not bool(parsed))
        self.reliability_table.setRowCount(len(self.FAMILY_NAMES))
        for row, family in enumerate(self.FAMILY_NAMES):
            state, reliability, samples = parsed.get(family, ("UNKNOWN", "0.0%", "0.0"))
            values = (family, state, reliability, samples)
            for col, value in enumerate(values):
                item = self.reliability_table.item(row, col)
                if item is None:
                    item = QTableWidgetItem()
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.reliability_table.setItem(row, col, item)
                if item.text() != str(value):
                    item.setText(str(value))
                if col == 1:
                    color = {
                        "VALIDATED": QColor("#4ade80"),
                        "SHRUNK": QColor("#facc15"),
                        "UNKNOWN": QColor("#94a3b8"),
                    }.get(str(state).upper(), QColor("#e2e8f0"))
                    item.setForeground(color)

    def _refresh_trends(self) -> None:
        try:
            self.drift_chart.set_rows(self._trend_store.recent("DRIFT", 120))
            self.reliability_chart.set_rows(self._trend_store.recent("RELIABILITY", 120))
        except Exception:
            self.drift_chart.set_rows([])
            self.reliability_chart.set_rows([])

    def _refresh_candidates(self) -> None:
        try:
            rows = self._candidate_repo.list_candidates()
            timeline = self._candidate_repo.timeline()
        except Exception:
            rows, timeline = [], []
        self.candidate_table.setRowCount(len(rows))
        for row, payload in enumerate(rows):
            values = (
                payload.get("candidate_id", "—"),
                payload.get("backtest_state", "PENDING"),
                payload.get("comparison_state", "INSUFFICIENT_DATA"),
                f"{float(payload.get('comparison_score', 0.0)):.2f}",
                payload.get("promotion_state", "PENDING"),
                payload.get("created_at", ""),
            )
            for col, value in enumerate(values):
                item = self.candidate_table.item(row, col)
                if item is None:
                    item = QTableWidgetItem()
                    self.candidate_table.setItem(row, col, item)
                item.setText(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.promotion_timeline.setText(
            "  →  ".join(f"{x.get('candidate_id')} · {x.get('state')}" for x in timeline[-8:])
            if timeline
            else "Chưa có Candidate. Quantum cần đủ dữ liệu truth-qualified trước khi tạo đề xuất SHADOW."
        )

    def _refresh_candidate_history(self) -> None:
        try:
            rows = self._candidate_repo.historical_candidates()
        except Exception:
            rows = []
        selected = None
        current = self.history_table.currentRow()
        if 0 <= current < self.history_table.rowCount():
            item = self.history_table.item(current, 0)
            selected = item.text() if item else None
        self.history_table.setRowCount(len(rows))
        select_row = -1
        for row, payload in enumerate(rows):
            values = (
                payload.get("candidate_id", "—"),
                payload.get("state", "CREATED"),
                int(payload.get("observations", 0) or 0),
                f"{float(payload.get('expectancy', 0.0)):+.3f}",
                f"{float(payload.get('max_drawdown', 0.0)):.3f}",
                f"{float(payload.get('win_rate', 0.0)) * 100:.1f}%",
                f"{float(payload.get('profit_factor', 0.0)):.2f}",
                f"{float(payload.get('brier', 0.0)):.3f}",
                f"{float(payload.get('reliability', 0.0)) * 100:.1f}%",
                f"{float(payload.get('coverage', 0.0)) * 100:.1f}%",
            )
            for col, value in enumerate(values):
                item = self.history_table.item(row, col)
                if item is None:
                    item = QTableWidgetItem()
                    self.history_table.setItem(row, col, item)
                item.setText(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if selected and str(values[0]) == selected:
                select_row = row
        if select_row < 0 and rows:
            select_row = 0
        if select_row >= 0:
            self.history_table.selectRow(select_row)
        else:
            self.candidate_history_chart.set_rows([])
            self.candidate_lifecycle_detail.setText(
                "Chưa có historical snapshot. Snapshot sẽ xuất hiện sau khi đủ observation hợp lệ."
            )

    def _refresh_candidate_history_chart(self) -> None:
        row = self.history_table.currentRow()
        if row < 0:
            self.candidate_history_chart.set_rows([])
            self.candidate_lifecycle_detail.setText(
                "Chọn Candidate để xem lifecycle/readiness timeline"
            )
            return
        item = self.history_table.item(row, 0)
        if item is None:
            self.candidate_history_chart.set_rows([])
            return
        candidate_id = item.text()
        try:
            rows = self._candidate_repo.candidate_trend(candidate_id)
            dossier = self._candidate_repo.candidate_dossier(candidate_id)
        except Exception:
            rows, dossier = [], {}
        self.candidate_history_chart.set_rows(rows)
        lifecycle = dossier.get("lifecycle", []) or []
        readiness = dossier.get("readiness", []) or []
        life_text = " → ".join(str(x.get("new_state", "?")) for x in lifecycle[-8:]) or "Chưa có lifecycle"
        ready_text = " → ".join(str(x.get("state", "?")) for x in readiness[-6:]) or "Chưa có readiness history"
        self.candidate_lifecycle_detail.setText(
            f"{candidate_id}\nLifecycle: {life_text}\nReadiness: {ready_text}\n"
            f"Snapshots {dossier.get('snapshot_count', 0)} · Events {dossier.get('event_count', 0)}"
        )

    def _refresh_historical_integrity_and_comparison(self) -> None:
        try:
            integrity = dict(self._candidate_repo.historical_integrity() or {})
            rows = list(self._candidate_repo.historical_candidates() or [])
        except Exception as exc:
            integrity = {"state": "ERROR", "issues": (str(exc),)}
            rows = []
        state = str(integrity.get("state", "UNKNOWN")).upper()
        detail = (
            f"Candidates {integrity.get('candidates', 0)} · lifecycle {integrity.get('lifecycle_events', 0)} · "
            f"snapshots {integrity.get('snapshots', 0)} · readiness {integrity.get('readiness_events', 0)}"
        )
        issues = tuple(integrity.get("issues", ()) or ())
        if issues:
            detail += " · " + "; ".join(str(x) for x in issues[:2])
        self.history_integrity_card.set_data(
            state,
            detail,
            "good" if state == "PASS" else "critical" if state in {"FAIL", "ERROR"} else "neutral",
        )
        self.history_comparison_table.setRowCount(len(rows))
        for row, payload in enumerate(rows):
            values = (
                row + 1,
                payload.get("candidate_id", "—"),
                payload.get("readiness_state", "NOT_EVALUATED"),
                f"{float(payload.get('expectancy', 0.0)):+.3f}",
                f"{float(payload.get('max_drawdown', 0.0)):.3f}",
                f"{float(payload.get('brier', 0.0)):.3f}",
                f"{float(payload.get('coverage', 0.0)) * 100:.1f}%",
                int(payload.get("snapshots", 0) or 0),
            )
            for col, value in enumerate(values):
                item = self.history_comparison_table.item(row, col)
                if item is None:
                    item = QTableWidgetItem()
                    self.history_comparison_table.setItem(row, col, item)
                item.setText(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

    def _refresh_operational_validation(self, analysis, runtime_state: str) -> None:
        calibration = str(getattr(analysis, "probability_calibration_state", "NOT_EVALUATED") if analysis else "NOT_EVALUATED").upper()
        drift = str(getattr(analysis, "calibration_drift_state", "NOT_EVALUATED") if analysis else "NOT_EVALUATED").upper()
        reliability = str(getattr(analysis, "evidence_reliability_state", "UNKNOWN") if analysis else "UNKNOWN").upper()
        try:
            now = time.monotonic()
            persist_health = now - self._last_health_persist >= 60.0
            snapshot = self._operational_platform.snapshot(
                calibration_state=calibration, drift_state=drift,
                reliability_state=reliability, runtime_state=runtime_state,
                active_regime=str(getattr(getattr(analysis, "regime", None), "regime", "UNKNOWN")),
                persist=persist_health,
            )
            if persist_health:
                self._last_health_persist = now
        except Exception as exc:
            self.ai_health_card.set_data("ERROR", str(exc), "critical")
            self.next_action_card.set_data("Kiểm tra Operational Validation", str(exc), "critical")
            return
        self._last_operational_snapshot = snapshot
        health = snapshot.health
        learning_only = (
            snapshot.coverage.eligible < 30
            and str(calibration).upper() in {"UNKNOWN", "NOT_EVALUATED", "INSUFFICIENT_DATA"}
            and str(runtime_state).upper() not in {"ERROR", "BLOCKED"}
        )
        display_state = "LEARNING" if learning_only else health.state
        health_state = "warning" if learning_only else ("good" if health.state in {"HEALTHY", "STABLE"} else "warning" if health.state == "WATCH" else "critical")
        contributor_text = " · ".join(f"{key.replace('_',' ').title()} {value:.0f}" for key, value in health.contributors.items())
        if learning_only:
            contributor_text = f"Operational score {health.score:.0f}/100 · Chưa đủ outcome để đánh giá sức khỏe mô hình · " + contributor_text
        self.ai_health_card.set_data(f"{health.score:.0f}/100 · {display_state}", contributor_text, health_state)
        self.next_action_card.set_data("ACTION", health.next_action, "critical" if health.alerts and health.alerts[0].severity == "CRITICAL" else "warning" if health.alerts else "good")

        coverage = snapshot.coverage
        self.coverage_summary.setText(
            f"Coverage · {coverage.state}\nEligible {coverage.eligible}/{coverage.total} · "
            f"Regime {coverage.regime_coverage*100:.0f}% · Direction {coverage.direction_coverage*100:.0f}%"
        )
        coverage_rows = [(f"Regime · {k}", v, "PASS" if v >= 15 else "LOW") for k, v in sorted(coverage.regimes.items())]
        coverage_rows += [(f"Direction · {k}", v, "PASS" if v >= 20 else "LOW") for k, v in sorted(coverage.directions.items())]
        coverage_rows += [(f"Order Flow · {k}", v, k) for k, v in sorted(coverage.order_flow_quality.items())]
        self.coverage_table.setRowCount(len(coverage_rows))
        for row, values in enumerate(coverage_rows):
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value)); item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.coverage_table.setItem(row, col, item)

        confidence = snapshot.confidence
        self.confidence_summary.setText(
            f"Confidence · {confidence.state}\nSamples {confidence.samples} · Mean {confidence.mean:.1f} · "
            f"Median {confidence.median:.1f} · P90 {confidence.p90:.1f} · ≥70 {confidence.acceptance_70*100:.2f}%"
        )
        total = max(1, confidence.samples)
        self.confidence_table.setRowCount(len(confidence.histogram))
        for row, (bucket, count) in enumerate(confidence.histogram.items()):
            for col, value in enumerate((bucket, count, f"{count/total*100:.1f}%")):
                item = QTableWidgetItem(str(value)); item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.confidence_table.setItem(row, col, item)

        regimes = snapshot.regimes
        self.regime_summary.setText(f"Regime Validation · {regimes.state}\nSupported regimes {regimes.supported_regimes} · " + ("; ".join(regimes.reasons[:2]) or "Tiếp tục observation"))
        self.regime_table.setRowCount(len(regimes.metrics))
        for row, metric in enumerate(regimes.metrics):
            values = (metric.regime, metric.samples, f"{metric.baseline_expectancy:+.3f}R", f"{metric.shadow_expectancy:+.3f}R", metric.state)
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value)); item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.regime_table.setItem(row, col, item)

        self.alert_table.setRowCount(len(health.alerts))
        for row, alert in enumerate(health.alerts):
            values = (alert.severity, alert.title, alert.reason, alert.action)
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == 0:
                    item.setForeground(QColor("#ef4444" if alert.severity == "CRITICAL" else "#f59e0b" if alert.severity == "WARNING" else "#60a5fa"))
                self.alert_table.setItem(row, col, item)

    def _refresh_operational_journey(self) -> None:
        try:
            snapshot = self._journey_service.snapshot()
            self._last_journey_snapshot = snapshot
            parts = []
            for stage in snapshot.stages:
                marker = "✓" if stage.state in {"COMPLETE", "READY"} else "🔒" if stage.state in {"LOCKED", "IMMUTABLE"} else "●"
                parts.append(f"{marker} {stage.label}: {stage.state} ({stage.detail})")
            self.journey_timeline.setText("  →  ".join(parts))
            self.health_history_chart.set_rows(snapshot.health_history)
            self.evidence_history_chart.set_rows(snapshot.evidence_history)
        except Exception as exc:
            self.journey_timeline.setText(f"Operational journey unavailable: {exc}")
            self.health_history_chart.set_rows(())
            self.evidence_history_chart.set_rows(())

    def _refresh_testnet_readiness(self) -> None:
        try:
            integrity = dict(self._candidate_repo.historical_integrity() or {})
            candidates = list(self._candidate_repo.historical_candidates() or [])
        except Exception:
            integrity, candidates = {"state": "UNKNOWN"}, []
        candidate = candidates[0] if candidates else {}
        try:
            snapshot = self._readiness_service.evaluate(
                operational=self._last_operational_snapshot,
                historical_integrity=integrity,
                candidate_state=str(candidate.get("state", "NONE")),
                candidate_readiness=str(candidate.get("readiness_state", "NOT_EVALUATED")),
                main_immutable=True, live_enabled=False, testnet_enabled=False,
            )
            self._last_readiness_snapshot = snapshot
            self.readiness_summary.setText(f"{snapshot.state} · {snapshot.score:.1f}/100\n{snapshot.recommendation}")
            self.readiness_table.setRowCount(len(snapshot.rules))
            for row, rule in enumerate(snapshot.rules):
                values=(rule.dimension, rule.code, rule.state, f"{rule.score*100:.0f}%", rule.recommendation)
                for col, value in enumerate(values):
                    item=self.readiness_table.item(row,col)
                    if item is None:
                        item=QTableWidgetItem()
                        self.readiness_table.setItem(row,col,item)
                    item.setText(str(value))
        except Exception as exc:
            self.readiness_summary.setText(f"READINESS ERROR · {exc}")
            self.readiness_table.setRowCount(0)

    def _request_scientific_backend(self) -> None:
        # Generation advances on every submit intent, not on worker start.
        self._scientific_generation += 1
        generation = self._scientific_generation
        if self._scientific_running:
            self._scientific_pending = True
            return
        self._scientific_running = True
        self._scientific_pending = False
        self._scientific_request.emit({"generation": generation})

    @Slot(object)
    def _on_scientific_ready(self, payload) -> None:
        self._scientific_running = False
        generation = int(getattr(payload, "generation", 0))
        if generation == self._scientific_generation:
            self._scientific_payload = payload
            self._scientific_applied_generation = generation
            self._scientific_last_error = ""
            if self._active:
                self._commit_scientific_payload(payload)
            else:
                self._pending_scientific_payload = payload
                self._refresh_pending_while_hidden = True
        # A stale payload is rejected before GUI commit. Latest-wins single-flight.
        if self._scientific_pending and not self._history_shutdown:
            self._scientific_pending = False
            self._scientific_running = True
            self._scientific_request.emit({"generation": self._scientific_generation})

    @Slot(int, str)
    def _on_scientific_failed(self, generation: int, error: str) -> None:
        self._scientific_running = False
        if int(generation) == self._scientific_generation:
            self._scientific_last_error = str(error)
            if self._active:
                self.scientific_backend_card.set_data(
                    "UNAVAILABLE",
                    str(error),
                    "critical",
                )
            else:
                self._pending_scientific_error = str(error)
                self._refresh_pending_while_hidden = True
        if self._scientific_pending and not self._history_shutdown:
            self._scientific_pending = False
            self._scientific_running = True
            self._scientific_request.emit({"generation": self._scientific_generation})

    def _commit_scientific_payload(self, payload: ScientificDashboardPayload) -> None:
        status = payload.status
        summary = payload.summary
        reasons = ", ".join(status.reason_codes[:2]) if status.reason_codes else "all governed checks passed"
        source = status.backend_source.value.replace("_", " ")
        root_note = status.active_root or "no active root"
        readiness_score = (
            f" {summary.readiness.readiness_score:.1f}"
            if summary.readiness.readiness_score is not None else ""
        )
        detail = (
            f"v{status.engine_version} · {status.tests_run} tests · {status.integration_mode}\n"
            f"Source {source} · {root_note}\n"
            f"Validation {summary.validation.validation_status} · Evidence {summary.evidence.evidence_status}\n"
            f"Readiness {summary.readiness.readiness_level}{readiness_score} · "
            f"Certification {summary.certification.certification_status}\n"
            f"Explainability {summary.explainability.status} · "
            f"Decision {summary.explainability.decision_type or 'UNAVAILABLE'} · "
            f"Confidence {summary.explainability.confidence if summary.explainability.confidence is not None else 'N/A'}\n"
            f"Trace {' → '.join(summary.decision_trace.stages) if summary.decision_trace.stages else 'UNAVAILABLE'}\n"
            f"Registry {summary.registry.registry_status} · "
            f"Model {(summary.registry.current_model.model_id + '@' + summary.registry.current_model.version) if summary.registry.current_model else 'UNAVAILABLE'} · "
            f"Maturity {summary.registry.current_model.maturity_level if summary.registry.current_model else 'UNAVAILABLE'}\n"
            f"TESTNET {status.safety.testnet} · LIVE {status.safety.live} · {reasons}"
        )
        state = "good" if status.display_state == "VERIFIED" else "warning" if status.display_state == "DEGRADED" else "critical"
        self.scientific_backend_card.set_data(status.display_state, detail, state)

    def _request_observation_data(self) -> None:
        # Generation advances on submit. While one request is running, retain
        # only the latest request intent (single-flight + latest-wins).
        self._observation_generation += 1
        generation = self._observation_generation
        if self._observation_running:
            self._observation_pending = True
            return
        self._observation_running = True
        self._observation_pending = False
        self._observation_request.emit({
            "generation": generation,
            "provider": self._observation_provider,
        })

    @Slot(object)
    def _on_observation_ready(self, payload) -> None:
        generation = int(payload.get("generation", 0))
        self._observation_running = False
        if generation == self._observation_generation:
            self._observation_cache = dict(payload.get("observation") or {})
            self._observation_applied_generation = generation
            self._last_observation_worker_ms = float(payload.get("worker_duration_ms", 0.0) or 0.0)
        # Stale payloads are intentionally discarded. Submit only the newest
        # generation when requests arrived during execution.
        if self._observation_pending:
            self._observation_pending = False
            self._observation_running = True
            self._observation_request.emit({
                "generation": self._observation_generation,
                "provider": self._observation_provider,
            })

    @Slot(int, str)
    def _on_observation_failed(self, generation: int, error: str) -> None:
        self._observation_running = False
        if int(generation) == self._observation_generation:
            self._observation_cache = {"errors": 1, "last_error": str(error)}
        if self._observation_pending:
            self._observation_pending = False
            self._observation_running = True
            self._observation_request.emit({
                "generation": self._observation_generation,
                "provider": self._observation_provider,
            })

    @Slot()
    def shutdown(self, timeout_ms: int = 5000) -> None:
        from dvs_ai.diagnostics.shutdown_probe import get_shutdown_probe
        from dvs_ai.runtime.qt_shutdown_forensics import (
            record_phase as record_qt_shutdown_phase,
            record_thread_operation,
        )
        _shutdown_probe = get_shutdown_probe()
        if _shutdown_probe is not None:
            _shutdown_probe.mark("truth_dashboard_shutdown_enter", object_id=hex(id(self)), timeout_ms=int(timeout_ms))
        record_qt_shutdown_phase(
            "truth_dashboard_shutdown_enter",
            timeout_ms=int(timeout_ms),
            history_shutdown=bool(self._history_shutdown),
        )
        if self._history_shutdown:
            record_qt_shutdown_phase("truth_dashboard_shutdown_already_done")
            return
        self._history_shutdown = True
        if hasattr(self, "timer"):
            self.timer.stop()
        thread = getattr(self, "_history_thread", None)
        if thread is not None and thread.isRunning():
            record_thread_operation("truth_history_quit_begin", thread)
            thread.quit()
            record_thread_operation("truth_history_wait_begin", thread, timeout_ms=int(timeout_ms))
            _history_stopped = thread.wait(max(0, int(timeout_ms)))
            record_thread_operation("truth_history_wait_end", thread, stopped=bool(_history_stopped))
            if not _history_stopped:
                # Do not terminate() a thread that may be inside SQLite.
                print(
                    "[TRUTH_DASHBOARD] Data worker did not stop "
                    "within the shutdown timeout."
                )
        operational_thread = getattr(
            self,
            "_operational_thread",
            None,
        )
        if (
            operational_thread is not None
            and operational_thread.isRunning()
        ):
            record_thread_operation("truth_operational_quit_begin", operational_thread)
            operational_thread.quit()
            record_thread_operation("truth_operational_wait_begin", operational_thread, timeout_ms=int(timeout_ms))
            _operational_stopped = operational_thread.wait(
                max(0, int(timeout_ms))
            )
            record_thread_operation("truth_operational_wait_end", operational_thread, stopped=bool(_operational_stopped))
            if not _operational_stopped:
                print(
                    "[TRUTH_DASHBOARD] Operational worker did not stop "
                    "within the shutdown timeout."
                )
        observation_thread = getattr(self, "_observation_thread", None)
        if observation_thread is not None and observation_thread.isRunning():
            record_thread_operation("truth_observation_quit_begin", observation_thread)
            observation_thread.quit()
            record_thread_operation("truth_observation_wait_begin", observation_thread, timeout_ms=int(timeout_ms))
            _observation_stopped = observation_thread.wait(max(0, int(timeout_ms)))
            record_thread_operation("truth_observation_wait_end", observation_thread, stopped=bool(_observation_stopped))
            if not _observation_stopped:
                print(
                    "[TRUTH_DASHBOARD] Observation worker did not stop "
                    "within the shutdown timeout."
                )
        scientific_thread = getattr(self, "_scientific_thread", None)
        if scientific_thread is not None and scientific_thread.isRunning():
            if _shutdown_probe is not None:
                _shutdown_probe.mark("truth_scientific_thread_quit_requested", object_id=hex(id(scientific_thread)), object_name=scientific_thread.objectName())
            scientific_thread.quit()
            if _shutdown_probe is not None:
                _shutdown_probe.mark("truth_scientific_thread_wait_begin", object_id=hex(id(scientific_thread)))
            _scientific_stopped = scientific_thread.wait(max(0, int(timeout_ms)))
            if _shutdown_probe is not None:
                _shutdown_probe.mark("truth_scientific_thread_wait_end", object_id=hex(id(scientific_thread)), stopped=bool(_scientific_stopped), is_running=bool(scientific_thread.isRunning()))
            if not _scientific_stopped:
                print(
                    "[TRUTH_DASHBOARD] Scientific worker did not stop "
                    "within the shutdown timeout."
                )

        if _shutdown_probe is not None:
            _shutdown_probe.mark("truth_dashboard_shutdown_exit", object_id=hex(id(self)))
        record_qt_shutdown_phase("truth_dashboard_shutdown_exit")

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)

    def refresh(self, force_history: bool = False) -> None:
        if not self._active:
            self._refresh_pending_while_hidden = (
                self._refresh_pending_while_hidden
                or bool(force_history)
            )
            return
        self._request_scientific_backend()
        now = time.monotonic()
        if force_history or now - self._last_history_refresh >= self.HISTORY_REFRESH_SECONDS:
            self._last_history_refresh = now
            self._request_history_data()

        analysis = self._analysis()
        try:
            runtime = dict(self._runtime_provider() or {})
        except Exception as exc:
            runtime = {"state": "ERROR", "last_error": str(exc)}

        runtime_state = str(runtime.get("state", "DISABLED")).upper()
        age = runtime.get("last_message_age_seconds")
        runtime_detail = f"Messages {int(runtime.get('messages', 0) or 0)}"
        if age is not None:
            runtime_detail += f" · age {self._safe_float(age):.0f}s"
        unresolved = int(runtime.get("gaps_unresolved", 0) or 0)
        if unresolved:
            runtime_detail += f" · gaps {unresolved}"
        self.runtime_card.set_data(runtime_state, runtime_detail, self._state_color(runtime_state))

        self._request_observation_data()
        observation = dict(self._observation_cache or {})
        obs_errors = int(observation.get("errors", 0) or 0)
        quality_state = str(observation.get("quality_state", "BLOCKED")).upper()
        recorded_count = int(observation.get("recorded", 0) or 0)
        closed_count = int(observation.get("closed", 0) or 0)
        eligible_count = int(observation.get("quality_eligible", 0) or 0)
        if obs_errors:
            obs_state = "ERROR"
        elif quality_state == "BLOCKED" and recorded_count > 0 and closed_count == 0:
            obs_state = "COLLECTING EVIDENCE"
        elif quality_state == "BLOCKED" and closed_count > 0 and eligible_count == 0:
            obs_state = "QUALITY GATE WAITING"
        else:
            obs_state = quality_state
        obs_detail = (
            f"recorded {int(observation.get('recorded', 0) or 0)} · "
            f"bound {int(observation.get('bound', 0) or 0)} · "
            f"closed {int(observation.get('closed', 0) or 0)} · "
            f"eligible {int(observation.get('quality_eligible', 0) or 0)}\n"
            f"bind {self._safe_float(observation.get('bind_rate', 0.0)) * 100:.0f}% · "
            f"close {self._safe_float(observation.get('close_rate', 0.0)) * 100:.0f}% · "
            f"candidate {observation.get('candidate_id', '—')}"
        )
        self.observation_card.set_data(
            obs_state,
            obs_detail,
            "critical" if obs_errors else "warning" if obs_state in {"COLLECTING EVIDENCE", "QUALITY GATE WAITING"} else self._state_color(quality_state),
        )

        self._request_operational_data(
            analysis,
            runtime_state,
            force=bool(force_history),
        )

        if analysis is None:
            self.symbol_label.setText("Chưa chọn tín hiệu")
            empty_details = {
                self.calibration_card: "Chọn coin hoặc chạy quét để nhận CoinAnalysis.",
                self.adaptive_card: "Adaptive Probability cần calibration hợp lệ và context đủ mẫu.",
                self.drift_card: "Drift history sẽ xuất hiện sau khi đủ PAPER outcomes.",
                self.order_flow_card: "Order-flow quality cần runtime/feed hợp lệ.",
                self.fusion_card: "Evidence Fusion hiển thị sau khi có kết quả phân tích.",
            }
            for card, detail in empty_details.items():
                card.set_data("INSUFFICIENT DATA", detail, "neutral")
            self.reliability_empty.setVisible(True)
            self.reliability_table.setRowCount(0)
            return

        self._last_analysis = analysis
        symbol = str(getattr(analysis, "symbol", "—"))
        direction = str(getattr(analysis, "direction", "—"))
        self.symbol_label.setText(f"{symbol} · {direction}")

        calibration_state = str(getattr(analysis, "probability_calibration_state", "NOT_EVALUATED")).upper()
        calibrated = self._safe_float(getattr(analysis, "calibrated_probability", 0.0))
        samples = int(getattr(analysis, "probability_calibration_samples", 0) or 0)
        self.calibration_card.set_data(
            f"{calibrated:.1f}%" if calibrated > 0 else calibration_state,
            f"{samples} PAPER samples · minimum 80 determinate trades",
            self._state_color(calibration_state),
        )

        adaptive_state = str(getattr(analysis, "adaptive_confidence_state", "NOT_EVALUATED")).upper()
        adaptive = self._safe_float(getattr(analysis, "adaptive_probability", 0.0))
        adjustment = self._safe_float(getattr(analysis, "adaptive_confidence_adjustment", 0.0))
        context = str(getattr(analysis, "adaptive_confidence_context", "NONE"))
        self.adaptive_card.set_data(
            f"{adaptive:.1f}%" if adaptive > 0 else adaptive_state,
            f"{context} · adjustment {adjustment:+.1f}pp",
            self._state_color(adaptive_state),
        )

        drift_state = str(getattr(analysis, "calibration_drift_state", "NOT_EVALUATED")).upper()
        brier = self._safe_float(getattr(analysis, "calibration_drift_brier_delta", 0.0))
        ece = self._safe_float(getattr(analysis, "calibration_drift_ece_delta", 0.0))
        psi = self._safe_float(getattr(analysis, "calibration_drift_psi", 0.0))
        self.drift_card.set_data(
            drift_state,
            f"Brier Δ {brier:+.3f} · ECE Δ {ece:+.3f} · PSI {psi:.3f}",
            self._state_color(drift_state),
        )

        flow_gate, flow_detail = self._order_flow_gate(analysis)
        self.order_flow_card.set_data(flow_gate, flow_detail, self._state_color(flow_gate))

        fusion_method = str(getattr(analysis, "confidence_fusion_method", "LEGACY"))
        quality = self._safe_float(getattr(analysis, "decision_quality_score", 0.0))
        active_weight = self._safe_float(getattr(analysis, "decision_quality_active_weight", 0.0))
        self.fusion_card.set_data(
            f"{quality:.1f}/100",
            f"{fusion_method}\nactive weight {active_weight:.2f}",
            "good" if quality >= 65 else "warning" if quality >= 50 else "neutral",
        )
        self._refresh_reliability(analysis)
