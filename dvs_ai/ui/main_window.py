from __future__ import annotations

import traceback
import logging
import csv
import functools
from contextlib import nullcontext
from collections import deque
from concurrent.futures import (
    FIRST_COMPLETED,
    ThreadPoolExecutor,
    wait,
)
import json
import math
import os
import time
import threading
import queue
import sqlite3
import uuid
import gc
import faulthandler
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QPointF, QRectF, QTimer, QSettings, QDateTime, QCoreApplication, QEvent, QMetaObject
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QKeySequence, QShortcut
try:
    import shiboken6 as _dvs_shiboken6
except Exception:
    _dvs_shiboken6 = None

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLayout, QLabel, QPushButton,
    QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView, QTextEdit,
    QTabWidget, QSplitter, QFrame, QDialog, QLineEdit, QListWidget,
    QDialogButtonBox, QMessageBox, QAbstractItemView, QFileDialog, QApplication, QComboBox, QCompleter, QGroupBox, QSizePolicy, QScrollArea, QTreeWidget, QTreeWidgetItem, QDial
)

from dvs_ai.education.widget import StaticKnowledgeLibraryWidget
from dvs_ai.domain.models import CoinAnalysis, EntryStatus
from dvs_ai.data.binance_provider import DataProviderError
from dvs_ai.runtime.provider_circuit import (
    GLOBAL_PROVIDER_CIRCUIT, ProviderCircuitShortCircuited,
)
from dvs_ai.services.provider_evidence_telemetry import PROVIDER_EVIDENCE
from dvs_ai.services.universe_loader_telemetry import UNIVERSE_LOADER_TELEMETRY
from dvs_ai.runtime.coin_analysis_token_tracker import COIN_ANALYSIS_TOKENS
from dvs_ai.runtime.payload_footprint_telemetry import PAYLOAD_FOOTPRINT_TELEMETRY
from dvs_ai.runtime.future_lifecycle import (
    FutureIdentity, FutureRuntime, orphan_threshold, classify_result_identity,
)
from dvs_ai.ui.market_chart import MarketChart
from dvs_ai.services.quantum_optimizer import QuantumOptimizer
from dvs_ai.services.quantum_report_contract import build_quantum_report_view
from dvs_ai.services.quantum_candidate_backtest import CandidateBacktestService
from dvs_ai.services.quantum_runtime_guard import QuantumRuntimeAction, QuantumRuntimeGuard
from dvs_ai.services.shadow_promotion_service import ShadowPromotionService
from dvs_ai.ui.ui_geometry_manager import UIGeometryManager
from dvs_ai.ui.ui_performance_profiler import UIPerformanceProfiler
from dvs_ai.ui.frame_paint_scheduler import FramePaintScheduler
from dvs_ai.ui.performance_overlay import PerformanceOverlay
from dvs_ai.ui.gr01_gui_commit_forensics import GR01_GUI_FORENSICS
from dvs_ai.ui.truth_dashboard import TruthDashboard
from dvs_ai.ui.statistical_diagnostics_dashboard import StatisticalDiagnosticsDashboard
from dvs_ai.ui.episode_audit_explorer import EpisodeAuditExplorer
from dvs_ai.ui.episode_integrity_monitor_widget import EpisodeIntegrityMonitorWidget
from dvs_ai.ui.integrity_incident_ledger_widget import IntegrityIncidentLedgerWidget
from dvs_ai.ui.integrity_alert_widget import IntegrityAlertWidget
from dvs_ai.ui.integrity_operations_console_widget import IntegrityOperationsConsoleWidget
from dvs_ai.ui.research_experiment_widget import ResearchExperimentWidget
from dvs_ai.ui.research_comparison_widget import ResearchComparisonWidget
from dvs_ai.ui.research_cohort_widget import ResearchCohortWidget
from dvs_ai.ui.research_cohort_diagnostics_widget import ResearchCohortDiagnosticsWidget
from dvs_ai.ui.research_lineage_provenance_widget import ResearchLineageProvenanceWidget
from dvs_ai.ui.research_review_workflow_widget import ResearchReviewWorkflowWidget
from dvs_ai.ui.research_governance_dashboard_widget import ResearchGovernanceDashboardWidget
from dvs_ai.ui.governance_incident_ledger_widget import GovernanceIncidentLedgerWidget
from dvs_ai.ui.governance_compliance_operations_widget import GovernanceComplianceOperationsWidget
from dvs_ai.ui.research_governance_audit_bundle_widget import ResearchGovernanceAuditBundleWidget
from dvs_ai.ui.audit_bundle_verifier_widget import AuditBundleVerifierWidget
from dvs_ai.ui.quantum_readiness_widget import QuantumReadinessWidget
from dvs_ai.ui.selection_state import SelectionState
from dvs_ai.ui.core_runtime_adapter import (CoreCycleRequest, CoreCycleResultViewModel, CoreCycleFailureViewModel, CoreRuntimeAdapter)
from dvs_ai.services.outcome_infrastructure import OutcomeInfrastructureStore
from dvs_ai.ui.outcome_resolution_coordinator import OutcomeResolutionCoordinator
from dvs_ai.ui.core_qualification_batch_runner import (
    CoreQualificationBatchRunner, QualificationBatch, QualificationBatchItem,
    QualificationBatchProgress, QualificationBatchSummary,
)
from dvs_ai.services.core_shadow_agreement_service import (
    CoreShadowAgreementStore, ShadowAgreementObservation, classify_agreement_result,
)
from dvs_ai.services.qualification_report_service import QualificationReportService
from dvs_ai.services.qualification_replay_service import QualificationReplayService
from dvs_ai.application import UnifiedCycleRequest
from dvs_ai.strategy_intelligence import MarketSnapshot as UnifiedMarketSnapshot
from dvs_ai.services.quantum_readiness_service import QuantumReadinessService
from dvs_ai.services.plain_language_presenter import PlainLanguagePresenter
from dvs_ai.ui.crash_reporting import log_gui_exception
from dvs_ai.ui.runtime_thread_attribution import RuntimeThreadAttributionTracker
from dvs_ai.ui.retention_owner_telemetry import OwnerDescriptor, RetentionOwnerTelemetry
from dvs_ai.version import (
    APP_NAME,
    APP_VERSION,
    APP_EDITION,
    WINDOW_TITLE,
    EXECUTION_STATUS_LABEL,
)


logger = logging.getLogger(__name__)


def _env_truthy(name: str, default: str = "0") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in {
        "1", "true", "yes", "on",
    }


# RC6.19-CLEAN: production-like runtime is the default. The heavy forensic
# stack remains available for targeted diagnosis only:
#   set DVS_FORENSIC_MODE=1
# This keeps causal fixes while removing persistent observer overhead.
_CLEAN_RUNTIME_DEFAULT = not _env_truthy("DVS_FORENSIC_MODE", "0")

_SIGNAL_PATH_WRITE_LOCK = threading.Lock()

_AUTO_PAPER_PIPELINE_LOCK = threading.Lock()

def _write_auto_paper_pipeline_event(event: str, **extra) -> None:
    """RC7.11: low-volume always-on Auto Paper causal telemetry.

    This deliberately does not depend on DVS_FORENSIC_MODE.  The purpose is to
    prove where candidate -> queue -> worker -> PaperTradeService stops while
    leaving Decision Engine, eligibility thresholds and execution semantics
    untouched.
    """
    try:
        payload = {
            "schema_version": "dvs.runtime.auto_paper_pipeline.v1",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "pid": os.getpid(),
            "event": str(event),
            "thread_ident": threading.get_ident(),
            "thread_name": QThread.currentThread().objectName(),
        }
        payload.update(extra)
        path = Path("artifacts/runtime/auto_paper_pipeline.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with _AUTO_PAPER_PIPELINE_LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    except Exception:
        logger.exception("RC7.11 auto-paper pipeline telemetry write failed: %s", event)


def _write_signal_path_worker_event(pipeline: str, event: str, **extra) -> None:
    """Low-volume IR-01A-r1 worker-side forensic event writer.

    Capture happens synchronously at the actual worker entry/emit point so
    sender/receiver/thread identity is not reconstructed later.
    """
    if _CLEAN_RUNTIME_DEFAULT:
        return
    try:
        try:
            from dvs_ai.diagnostics.shutdown_probe import get_shutdown_probe
            _probe = get_shutdown_probe()
            if _probe is not None:
                _probe.record_current_thread_mapping(pipeline, event, source="worker_signal_path")
        except Exception:
            pass
        payload = {
            "schema_version": "dvs.runtime.signal_path_forensics.v1",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="microseconds") + "Z",
            "pid": os.getpid(),
            "pipeline": str(pipeline),
            "event": str(event),
            "thread_ident": threading.get_ident(),
            "thread_name": QThread.currentThread().objectName(),
        }
        payload.update(extra)
        path = Path("artifacts/runtime/signal_path_forensics.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with _SIGNAL_PATH_WRITE_LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
    except Exception:
        logger.exception("IR01A_R1_SIGNAL_PATH_WRITE_FAILED pipeline=%s event=%s", pipeline, event)



def _audit_gui_callback(section: str, *, record_threshold_ms: float = 5.0):
    """RC6.4.7 callback duration and event-loop attribution instrumentation.

    A GUI-thread timer cannot execute *during* a blocking GUI callback, so the
    previous design naturally observed ``active_callback=null`` after the block
    ended. This wrapper now keeps a nested in-memory stack and records the
    completed callback duration. The scheduler probe can then correlate its
    delayed delivery with the most recently completed callback.
    """

    def decorate(func):
        @functools.wraps(func)
        def wrapped(self, *args, **kwargs):
            if _CLEAN_RUNTIME_DEFAULT or bool(
                getattr(self, "_clean_runtime_mode", False)
            ):
                return func(self, *args, **kwargs)
            started_ns = time.monotonic_ns()
            instance_id = uuid.uuid4().hex[:12]
            stack = getattr(self, "_rc647_callback_stack", None)
            if stack is None:
                stack = []
                self._rc647_callback_stack = stack
            context = {
                "section": str(section),
                "callback_instance_id": instance_id,
                "entered_monotonic_ns": started_ns,
                "python_thread_id": threading.get_ident(),
                "nested_depth": len(stack),
                "scan_id": str(getattr(self, "current_scan_id", "")),
                "cycle_index": int(getattr(self, "_scan_cycle_count", 0) or 0),
            }
            stack.append(context)
            self._rc63_active_callback = context
            failure_type = None
            try:
                return func(self, *args, **kwargs)
            except Exception as exc:
                failure_type = type(exc).__name__
                raise
            finally:
                ended_ns = time.monotonic_ns()
                duration_ms = (ended_ns - started_ns) / 1_000_000.0
                if stack and stack[-1] is context:
                    stack.pop()
                else:
                    try:
                        stack.remove(context)
                    except ValueError:
                        pass
                self._rc63_active_callback = stack[-1] if stack else None
                completed = {
                    **context,
                    "ended_monotonic_ns": ended_ns,
                    "duration_ms": round(duration_ms, 3),
                    "failure_type": failure_type,
                }
                self._rc647_last_completed_callback = completed
                if duration_ms >= float(record_threshold_ms) and hasattr(
                    self, "_record_callback_attribution"
                ):
                    self._record_callback_attribution(
                        str(section),
                        duration_ms,
                        callback_instance_id=instance_id,
                        nested_depth=context["nested_depth"],
                        scan_id=context["scan_id"],
                        cycle_index=context["cycle_index"],
                        failure_type=failure_type,
                    )
        return wrapped
    return decorate



class OutcomeUpdateWorker(QObject):
    """Run provider-backed outcome evaluation outside the GUI thread."""

    completed = Signal(object, float)
    failed = Signal(str, float)

    def __init__(self, outcome_tracker, parent=None):
        super().__init__(parent)
        self._outcome_tracker = outcome_tracker

    @Slot(int)
    def run(self, limit: int) -> None:
        started = time.monotonic()
        try:
            stats = self._outcome_tracker.evaluate_pending(limit=int(limit))
            self.completed.emit(
                dict(stats),
                (time.monotonic() - started) * 1000.0,
            )
        except Exception as exc:
            _write_auto_paper_pipeline_event(
                "service_exception",
                capture_key=str(capture_key),
                symbol=str(getattr(analysis, "symbol", "UNKNOWN")),
                error_type=type(exc).__name__,
                error_message=str(exc)[:500],
                duration_ms=round((time.monotonic() - started) * 1000.0, 3),
            )
            self.failed.emit(
                f"{type(exc).__name__}: {exc}",
                (time.monotonic() - started) * 1000.0,
            )


class UniverseLoadWorker(QObject):
    """RC6.4.5: execute all universe network I/O outside the GUI thread."""

    progress = Signal(str, str, int)
    completed = Signal(str, object, float)
    failed = Signal(str, str, float)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service

    @Slot(str, int, float)
    def load(self, universe_load_id: str, limit: int, min_quote_volume: float) -> None:
        started = time.monotonic()
        self.progress.emit(universe_load_id, "requesting", 10)
        try:
            universe = self._service.refresh_universe(limit, min_quote_volume)
            elapsed_ms = (time.monotonic() - started) * 1000.0
            self.progress.emit(universe_load_id, "completed", 100)
            self.completed.emit(universe_load_id, list(universe), elapsed_ms)
        except Exception as exc:
            elapsed_ms = (time.monotonic() - started) * 1000.0
            self.failed.emit(
                universe_load_id,
                f"{type(exc).__name__}: {exc}",
                elapsed_ms,
            )


class ApiHealthCheckWorker(QObject):
    """RC6.4.5b: run /fapi/v1/time outside the GUI MainThread."""

    completed = Signal(str, bool, str, float)

    def __init__(self, provider, parent=None):
        super().__init__(parent)
        self._provider = provider

    @Slot(str)
    def run(self, operation_id: str) -> None:
        started = time.monotonic()
        PROVIDER_EVIDENCE.emit(
            "api_health_check_started", operation_id=operation_id, outcome="started"
        )
        try:
            ok, message = self._provider.health_check()
            elapsed_ms = (time.monotonic() - started) * 1000.0
            PROVIDER_EVIDENCE.emit(
                "api_health_check_finished", operation_id=operation_id,
                outcome="success" if ok else "failed", elapsed_ms=round(elapsed_ms, 3),
            )
            self.completed.emit(operation_id, bool(ok), str(message), elapsed_ms)
        except Exception as exc:
            elapsed_ms = (time.monotonic() - started) * 1000.0
            message = f"{type(exc).__name__}: {exc}"
            PROVIDER_EVIDENCE.emit(
                "api_health_check_failed", operation_id=operation_id,
                outcome="failed", error=message, elapsed_ms=round(elapsed_ms, 3),
            )
            self.completed.emit(operation_id, False, message, elapsed_ms)


class SignalRecordWorker(QObject):
    """Serialize SignalRecorder writes outside the Qt GUI thread."""

    completed = Signal(str, float)
    failed = Signal(str, str, float)

    @Slot(object, object)
    def record(self, analysis, scan_id) -> None:
        started = time.perf_counter()
        symbol = str(getattr(analysis, "symbol", "UNKNOWN"))
        try:
            self._recorder.record(analysis, scan_id)
            self.completed.emit(
                symbol,
                (time.perf_counter() - started) * 1000.0,
            )
        except Exception as exc:
            self.failed.emit(
                symbol,
                f"{type(exc).__name__}: {exc}",
                (time.perf_counter() - started) * 1000.0,
            )

    def __init__(self, recorder, parent=None):
        super().__init__(parent)
        self._recorder = recorder


class AutoPaperWorker(QObject):
    """RC6.4.7C: execute one heavy Auto Paper item off the GUI thread."""

    completed = Signal(object, bool, str, float)
    failed = Signal(object, str, str, float)

    def __init__(self, paper_trade_service, parent=None):
        super().__init__(parent)
        self._service = paper_trade_service

    @Slot(object, object, object, bool)
    def process(
        self,
        analysis,
        capture_key,
        unified_identity,
        shadow_only: bool,
    ) -> None:
        started = time.monotonic()
        _write_auto_paper_pipeline_event(
            "worker_slot_entered",
            capture_key=str(capture_key),
            symbol=str(getattr(analysis, "symbol", "UNKNOWN")),
            shadow_only=bool(shadow_only),
            identity_present=bool(unified_identity is not None),
        )
        _write_signal_path_worker_event(
            "auto_paper", "worker_slot_entered",
            worker_class=type(self).__name__, worker_object_id=hex(id(self)),
            payload_id=str(capture_key),
        )
        # IR-01A-r1: low-impact queued-signal self-test uses the real request
        # and real completion signal path without touching PaperTradeService.
        if isinstance(analysis, dict) and analysis.get("__queued_signal_probe__"):
            token = str(analysis.get("token", capture_key))
            _write_signal_path_worker_event(
                "auto_paper", "worker_result_emit_begin", token=token,
                payload_id=str(capture_key),
            )
            self.completed.emit(
                capture_key, True, f"QUEUED_SIGNAL_PROBE_OK:{token}",
                (time.monotonic() - started) * 1000.0,
            )
            _write_signal_path_worker_event(
                "auto_paper", "worker_result_emit_end", token=token,
                payload_id=str(capture_key),
            )
            return
        try:
            if bool(shadow_only):
                ok, message = self._service.auto_consider_shadow_only(
                    analysis,
                    unified_identity=unified_identity,
                    source="AUTO_SHADOW_RECOVERY",
                )
            else:
                ok, message = self._service.auto_consider(
                    analysis,
                    unified_identity=unified_identity,
                )
            _write_auto_paper_pipeline_event(
                "service_returned",
                capture_key=str(capture_key),
                symbol=str(getattr(analysis, "symbol", "UNKNOWN")),
                ok=bool(ok),
                message=" ".join(str(message).split())[:300],
                duration_ms=round((time.monotonic() - started) * 1000.0, 3),
            )
            _write_signal_path_worker_event(
                "auto_paper", "worker_work_finished", payload_id=str(capture_key),
                ok=bool(ok),
            )
            _write_signal_path_worker_event(
                "auto_paper", "worker_result_emit_begin", payload_id=str(capture_key),
            )
            self.completed.emit(
                capture_key, bool(ok), str(message),
                (time.monotonic() - started) * 1000.0,
            )
            _write_signal_path_worker_event(
                "auto_paper", "worker_result_emit_end", payload_id=str(capture_key),
            )
        except Exception as exc:
            self.failed.emit(
                capture_key, type(exc).__name__, str(exc),
                (time.monotonic() - started) * 1000.0,
            )


class ObjectCensusWorker(QObject):
    """RC6.4.7D: low-frequency, bounded heap census off the GUI thread.

    The worker performs one ``gc.get_objects()`` traversal per sample. It never
    serializes objects, calls ``repr()``, or retains references after the scan.
    """

    snapshot_ready = Signal(object)
    scan_failed = Signal(str)
    stopped = Signal()

    def __init__(self, interval_ms: int = 300_000, parent=None):
        super().__init__(parent)
        self._interval_ms = max(300_000, int(interval_ms))
        self._timer = None
        self._scan_active = False
        self._sequence = 0

    @Slot()
    def start(self) -> None:
        if self._timer is not None:
            return
        self._timer = QTimer(self)
        self._timer.setObjectName("dvs-object-census-timer")
        self._timer.setInterval(self._interval_ms)
        self._timer.timeout.connect(self.scan_once)
        self._timer.start()
        QTimer.singleShot(60_000, self.scan_once)

    @Slot()
    def stop(self) -> None:
        """Stop idempotently on the worker thread before thread shutdown."""
        timer = self._timer
        self._timer = None
        if timer is not None:
            try:
                timer.stop()
            except RuntimeError:
                # The C++ timer may already be gone during late Qt teardown.
                pass
            try:
                timer.deleteLater()
            except RuntimeError:
                pass
        self.stopped.emit()

    @Slot()
    def scan_once(self) -> None:
        if self._scan_active:
            return
        self._scan_active = True
        started = time.monotonic()
        try:
            objects = gc.get_objects()
            exact_names = {
                "AutoPaperWorker", "DataFrame", "Series", "dict", "list",
                "QTableWidgetItem", "QStandardItem", "PaperTrade",
                "DecisionCandidate", "Episode", "CoinAnalysis",
            }
            counts = {name: 0 for name in sorted(exact_names)}
            identity_like = 0
            auto_paper_payload_like = 0
            type_counts = {}
            for obj in objects:
                try:
                    name = type(obj).__name__
                except Exception:
                    continue
                if name in counts:
                    counts[name] += 1
                lower = name.lower()
                if "identity" in lower:
                    identity_like += 1
                if name in {"CoinAnalysis", "UnifiedIdentity", "CaptureIdentity"} or (
                    "analysis" in lower or "capture" in lower
                ):
                    auto_paper_payload_like += 1
                # Bounded per-type census for project-specific/high-value classes.
                if (
                    name in exact_names or "identity" in lower or
                    "analysis" in lower or "episode" in lower or
                    "paper" in lower or "candidate" in lower
                ):
                    type_counts[name] = type_counts.get(name, 0) + 1
            self._sequence += 1
            payload = {
                "schema_version": "dvs.runtime.object_census.v1",
                "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
                "sequence": self._sequence,
                "thread_id": threading.get_ident(),
                "scan_duration_ms": round((time.monotonic() - started) * 1000.0, 3),
                "total_gc_objects": len(objects),
                "counts": counts,
                "identity_like_count": identity_like,
                "auto_paper_payload_like_count": auto_paper_payload_like,
                "selected_type_counts": dict(sorted(type_counts.items())),
            }
            # Drop the heap list before handing off the small aggregate payload.
            del objects
            self.snapshot_ready.emit(payload)
        except Exception as exc:
            self.scan_failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self._scan_active = False


class Worker(QObject):
    result = Signal(object)
    progress = Signal(int, int, str)
    error = Signal(str, str)
    lifecycle = Signal(object)
    finished = Signal()
    finished_with_identity = Signal(int, str, int)

    FUTURE_DEADLINE_SECONDS = 120.0

    def __init__(
        self, service, coins, timeframes, max_workers=6, *,
        runtime_session_id="", scan_id="", cycle_index=0, generation=0,
    ):
        super().__init__()
        self.service = service
        self.runtime_session_id = str(runtime_session_id)
        self.scan_id = str(scan_id)
        self.cycle_index = int(cycle_index)
        self.generation = int(generation)
        self.coins = tuple(coins)
        self.timeframes = tuple(timeframes)
        self.max_workers = min(12, max(2, int(max_workers)))
        self.stop_requested = False
        self._executor = None
        self._executor_generation = 0
        self._current_scan_cycle_id = ""
        self._quarantined_executors = []

    def _execute_future(self, runtime: FutureRuntime):
        dispatch_ms = runtime.mark_started()
        PROVIDER_EVIDENCE.emit(
            "future_started", scan_cycle_id=runtime.identity.scan_cycle_id,
            executor_generation=runtime.identity.executor_generation, symbol=runtime.identity.symbol,
            dispatch_latency_ms=round(dispatch_ms, 3),
        )
        try:
            analysis = self.service.scan_coin(
                runtime.identity.symbol, self.timeframes, runtime.identity.scan_cycle_id
            )
            COIN_ANALYSIS_TOKENS.register_created(
                analysis,
                cycle_index=self.cycle_index,
                mutation_site="Worker._execute_future:scan_coin_return",
                symbol=runtime.identity.symbol,
            )
            return analysis
        finally:
            runtime.mark_finished()

    def _new_executor(self, workers: int) -> ThreadPoolExecutor:
        return ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix=f"dvs-scan-g{self._executor_generation}",
        )

    def _trace_liveness(self, event: str, **details) -> None:
        payload = {
            "schema_version": "dvs.runtime.scan_dispatch_liveness.v1",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "monotonic_ns": time.monotonic_ns(),
            "pid": os.getpid(),
            "runtime_session_id": self.runtime_session_id,
            "scan_id": self.scan_id,
            "cycle_index": self.cycle_index,
            "generation": self.generation,
            "event": str(event),
            "worker_object_id": hex(id(self)),
            "current_worker_object_id": None,
            "thread_object_id": hex(id(QThread.currentThread())),
            "qt_thread_name": QThread.currentThread().objectName(),
            "python_thread_id": threading.get_ident(),
            **details,
        }
        try:
            path = Path("artifacts/runtime/scan_dispatch_liveness.jsonl")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        except Exception:
            logger.exception("SCAN_LIVENESS_WRITE_FAILED event=%s", event)

    @Slot()
    def run(self):
        total = len(self.coins)
        completed = 0
        workers = min(self.max_workers, max(1, total))
        threshold = orphan_threshold(workers)
        self._current_scan_cycle_id = uuid.uuid4().hex
        runtimes = {}
        futures = {}
        pending_symbols = list(self.coins)
        self._executor = self._new_executor(workers)

        def submit_symbols(symbols):
            for symbol in symbols:
                identity = FutureIdentity(self._current_scan_cycle_id, self._executor_generation, symbol)
                runtime = FutureRuntime(identity=identity, submitted_at=time.monotonic())
                future = self._executor.submit(self._execute_future, runtime)
                runtimes[future] = runtime
                futures[future] = identity

        try:
            submit_symbols(pending_symbols)
            pending = set(futures)
            while pending and not self.stop_requested:
                done, pending = wait(pending, timeout=0.20, return_when=FIRST_COMPLETED)
                for future in done:
                    identity = futures[future]
                    runtime = runtimes[future]
                    discard_reason = classify_result_identity(
                        identity,
                        current_scan_cycle_id=self._current_scan_cycle_id,
                        current_executor_generation=self._executor_generation,
                    )
                    if discard_reason:
                        PROVIDER_EVIDENCE.emit(discard_reason, **identity.__dict__)
                        continue
                    completed += 1
                    self.progress.emit(completed, total, identity.symbol)
                    try:
                        self.result.emit(future.result())
                    except DataProviderError as exc:
                        prefix = "SKIP" if exc.skip_only else "RETRYABLE" if exc.retryable else "ERROR"
                        self.error.emit(identity.symbol, f"{prefix} · {exc}")
                    except Exception as exc:
                        classified = self.service.provider.classify_exception(exc)
                        self.error.emit(identity.symbol, f"ERROR · {classified}")

                now = time.monotonic()
                orphan_running = []
                for future in pending:
                    runtime = runtimes[future]
                    with runtime.lock:
                        if runtime.state == "RUNNING" and runtime.started_at is not None and not future.done():
                            age = now - runtime.started_at
                            if age > self.FUTURE_DEADLINE_SECONDS:
                                orphan_running.append((future, runtime, age))
                for _, runtime, age in orphan_running:
                    PROVIDER_EVIDENCE.emit(
                        "future_deadline_exceeded", **runtime.identity.__dict__,
                        future_age_seconds=round(age, 3), state=runtime.state,
                    )

                if len(orphan_running) >= threshold:
                    old_generation = self._executor_generation
                    old_executor = self._executor
                    queued_symbols = []
                    for future in list(pending):
                        runtime = runtimes[future]
                        with runtime.lock:
                            if runtime.state == "QUEUED" and future.cancel():
                                queued_symbols.append(runtime.identity.symbol)
                                pending.discard(future)
                    old_executor.shutdown(wait=False, cancel_futures=True)
                    self._quarantined_executors.append(old_executor)
                    PROVIDER_EVIDENCE.emit(
                        "executor_quarantined", scan_cycle_id=self._current_scan_cycle_id,
                        executor_generation=old_generation, orphan_running=len(orphan_running),
                        orphan_threshold=threshold, max_workers=workers, queued_cancelled=len(queued_symbols),
                    )
                    self._executor_generation += 1
                    self._executor = self._new_executor(workers)
                    if queued_symbols:
                        before = set(futures)
                        submit_symbols(queued_symbols)
                        pending.update(set(futures) - before)
                    # No old-generation future may block this cycle after
                    # quarantine. Running tasks continue only as isolated
                    # process-owned threads and their late results are rejected.
                    for future in list(pending):
                        if futures[future].executor_generation == old_generation:
                            pending.discard(future)
                    if not queued_symbols and not pending:
                        break

            if self.stop_requested:
                for future in pending:
                    future.cancel()
        finally:
            executor = self._executor
            shutdown_started = time.monotonic()
            if executor is not None:
                executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
            self.lifecycle.emit({
                "scan_cycle_id": self._current_scan_cycle_id,
                "executor_generation": self._executor_generation,
                "executor_shutdown_wait": False,
                "executor_shutdown_ms": round((time.monotonic()-shutdown_started)*1000.0, 3),
                "orphan_threshold": threshold,
                "stop_requested": bool(self.stop_requested),
            })
            # Snapshot immutable completion identity before any signal can
            # schedule QObject deletion. Qt copies int/str payload values into
            # the queued event, so cleanup never depends on sender() or on the
            # continued lifetime of this QObject/C++ wrapper.
            finished_generation = int(self.generation)
            finished_scan_id = str(self.scan_id)
            finished_cycle_index = int(self.cycle_index)
            self._trace_liveness(
                "worker_finished_emit_begin",
                scan_cycle_id=self._current_scan_cycle_id,
                executor_generation=self._executor_generation,
                finished_generation=finished_generation,
                finished_scan_id=finished_scan_id,
                finished_cycle_index=finished_cycle_index,
            )
            self.finished_with_identity.emit(
                finished_generation, finished_scan_id, finished_cycle_index
            )
            self.finished.emit()
            self._trace_liveness(
                "worker_finished_emit_end",
                scan_cycle_id=self._current_scan_cycle_id,
                executor_generation=self._executor_generation,
                finished_generation=finished_generation,
                finished_scan_id=finished_scan_id,
                finished_cycle_index=finished_cycle_index,
            )

    def stop(self):
        self.stop_requested = True


class FinalizationWorker(QObject):
    """
    Runs the CPU/data-heavy end-of-scan pipeline outside the Qt GUI thread.

    The worker never touches widgets. It receives a snapshot of scan results
    and emits one immutable result payload back to MainWindow.
    """

    finished = Signal(object)
    error = Signal(str)

    def __init__(
        self,
        service,
        results,
        *,
        confidence_calibration_max_boost,
        opportunity_min_score,
        microstructure_enabled,
        microstructure_top_n,
        microstructure_weight,
        microstructure_confirm_bonus,
        microstructure_conflict_penalty,
    ):
        super().__init__()
        self.service = service
        self.results = dict(results)
        for _analysis in self.results.values():
            COIN_ANALYSIS_TOKENS.owner_enter(
                _analysis, "FinalizationWorker.results",
                cycle_index=0, mutation_site="FinalizationWorker.__init__",
            )
        self.confidence_calibration_max_boost = (
            confidence_calibration_max_boost
        )
        self.opportunity_min_score = opportunity_min_score
        self.microstructure_enabled = bool(microstructure_enabled)
        self.microstructure_top_n = int(microstructure_top_n)
        self.microstructure_weight = float(microstructure_weight)
        self.microstructure_confirm_bonus = float(
            microstructure_confirm_bonus
        )
        self.microstructure_conflict_penalty = float(
            microstructure_conflict_penalty
        )

    @Slot()
    def run(self):
        try:
            brief = self.service.build_market_brief(self.results)
            contextualized = dict(self.results)

            for symbol, analysis in tuple(self.results.items()):
                if symbol == "BTC/USDT:USDT":
                    continue
                gated = self.service.apply_market_bias_gate(
                    analysis,
                    brief,
                )
                calibrated = self.service.calibrate_context_confidence(
                    gated,
                    brief,
                    max_boost=self.confidence_calibration_max_boost,
                )
                contextualized[symbol] = calibrated

            ranked = self.service.rank_opportunities(
                contextualized,
                minimum_score=self.opportunity_min_score,
            )

            if self.microstructure_enabled:
                ranked = self.service.hydrate_microstructure(
                    ranked,
                    max_symbols=self.microstructure_top_n,
                )
                ranked = self.service.refresh_position_footprint(ranked)
                ranked = self.service.apply_microstructure_adjustments(
                    ranked,
                    weight=self.microstructure_weight,
                    confirm_bonus=self.microstructure_confirm_bonus,
                    conflict_penalty=self.microstructure_conflict_penalty,
                )
                ranked = self.service.rank_opportunities(
                    ranked,
                    minimum_score=self.opportunity_min_score,
                )

            ranked = self.service.annotate_calibrated_probabilities(ranked)
            self.finished.emit({
                "results": ranked,
                "brief": brief,
                "worker_finished_monotonic_ns": time.perf_counter_ns(),
            })
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            for _analysis in self.results.values():
                COIN_ANALYSIS_TOKENS.owner_release(
                    _analysis, "FinalizationWorker.results",
                    cycle_index=0, mutation_site="FinalizationWorker.run:finally",
                )
            self.results.clear()


class QuantumWorker(QObject):
    progress = Signal(object)
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, optimizer):
        super().__init__()
        self.optimizer = optimizer
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True

    @Slot()
    def run(self):
        try:
            report = self.optimizer.optimize(
                progress_callback=self.progress.emit,
                cancel_check=lambda: self.stop_requested,
            )
            self.finished.emit(report)
        except Exception as exc:
            self.error.emit(str(exc))


# RC6.11C-r1 (measurement only): Python paint-path attribution, low
# overhead revision.
#
# Native evidence (RC6.11B V21 WinDbg dump) showed the crash at
# Qt6Gui!QRasterPaintEngine::penChanged+0x1c (WRITE access violation,
# rax=0x2D8) reached from a Python call inside a deep recursive repaint
# (QWidgetPrivate::drawWidget / paintSiblingsRecursive), not from
# closeEvent and not from QPropertyAnimation. A source census of this
# file found exactly two custom paint paths that call QPainter.setPen():
# Sparkline.paintEvent and GaugeWidget.paintEvent. This instrumentation
# brackets every setPen() call in both.
#
# r1 changes from the first RC6.11C revision, per review:
# - The breadcrumb file handle is opened once (lazily, unbuffered
#   binary) and kept open; every marker does seek(0)+write+truncate on
#   the already-open handle instead of Path.write_text() (which opens,
#   truncates, writes, and closes the file on every single call).
# - Unbuffered mode (buffering=0) pushes each write to the OS
#   immediately without our own explicit flush()/fsync() call inside
#   paintEvent, so durability against a native crash does not depend on
#   an extra flush per marker.
# - Only ONE marker per setPen() (paint_operation_enter) instead of a
#   begin/end pair: if setPen() itself is what crashes, the enter marker
#   is already the last thing on disk; if it succeeds, the next
#   operation's enter (or paint_path_end) simply overwrites it. This
#   roughly halves the per-repaint write count (Sparkline: 8->4,
#   GaugeWidget: 12->6, counting path_begin/end + one enter per setPen).
# - Every marker now carries paint_instance (GaugeWidget.title, or
#   Sparkline's objectName()) so multiple same-class widgets are
#   distinguishable in the breadcrumb.
# - GUI-thread affinity is checked via
#   QApplication.instance().thread() == QThread.currentThread(), the
#   idiomatic Qt comparison, instead of comparing a threading.get_ident()
#   value captured once at module import time.
#
# Still never calls shiboken6.getCppPointer()/isValid(), never installs
# a QTimer, never calls processEvents(), never introspects the QPainter
# or its device beyond what the surrounding code already does.
_PAINT_BREADCRUMB_PATH = Path("artifacts/runtime/paint_path_breadcrumb.json")
_PAINT_BREADCRUMB_LOCK = threading.Lock()
_PAINT_DEPTH_BY_THREAD: dict = {}
_PAINT_BREADCRUMB_HANDLE = None


def _paint_breadcrumb_handle():
    global _PAINT_BREADCRUMB_HANDLE
    if _PAINT_BREADCRUMB_HANDLE is None:
        try:
            _PAINT_BREADCRUMB_PATH.parent.mkdir(parents=True, exist_ok=True)
            _PAINT_BREADCRUMB_HANDLE = open(
                _PAINT_BREADCRUMB_PATH, "w+b", buffering=0
            )
        except Exception:
            _PAINT_BREADCRUMB_HANDLE = False  # sentinel: give up, do not retry every call
    return _PAINT_BREADCRUMB_HANDLE or None


def _paint_gui_thread_match() -> bool | None:
    try:
        app = QApplication.instance()
        if app is None:
            return None
        return QThread.currentThread() == app.thread()
    except Exception:
        return None


def _paint_breadcrumb_write(**fields) -> None:
    if _CLEAN_RUNTIME_DEFAULT:
        return
    row = {
        "schema_version": "dvs.runtime.paint_path_breadcrumb.v1",
        "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        "thread_ident": threading.get_ident(),
        "gui_thread_match": _paint_gui_thread_match(),
        **fields,
    }
    try:
        payload = json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")
        with _PAINT_BREADCRUMB_LOCK:
            handle = _paint_breadcrumb_handle()
            if handle is None:
                return
            handle.seek(0)
            handle.write(payload)
            handle.truncate(len(payload))
    except Exception:
        pass


# RC6.12C (measurement only): correlate custom paint activity with scheduler drift.
# Both writers and readers run on the GUI thread. No lock, event pumping,
# scheduling change, paint I/O, sleep, debounce, or business-logic change.
_LAST_PAINT_ACTIVITY = {
    "sequence": 0,
    "paint_class": None,
    "paint_instance": None,
    "operation": None,
    "started_ns": None,
    "ended_ns": None,
    "duration_ms": None,
    "in_progress": False,
}


def _paint_path_begin(paint_class: str, paint_instance: str, **extra) -> int:
    ident = threading.get_ident()
    depth = _PAINT_DEPTH_BY_THREAD.get(ident, 0) + 1
    _PAINT_DEPTH_BY_THREAD[ident] = depth

    now_ns = time.monotonic_ns()
    _LAST_PAINT_ACTIVITY["sequence"] = int(_LAST_PAINT_ACTIVITY["sequence"] or 0) + 1
    _LAST_PAINT_ACTIVITY["paint_class"] = str(paint_class)
    _LAST_PAINT_ACTIVITY["paint_instance"] = str(paint_instance)
    _LAST_PAINT_ACTIVITY["operation"] = None
    _LAST_PAINT_ACTIVITY["started_ns"] = now_ns
    _LAST_PAINT_ACTIVITY["ended_ns"] = None
    _LAST_PAINT_ACTIVITY["duration_ms"] = None
    _LAST_PAINT_ACTIVITY["in_progress"] = True

    _paint_breadcrumb_write(
        event="paint_path_begin",
        paint_class=paint_class,
        paint_instance=paint_instance,
        operation=None,
        paint_depth=depth,
        **extra,
    )
    return depth


def _paint_path_end(paint_class: str, paint_instance: str, depth: int, **extra) -> None:
    ident = threading.get_ident()
    _PAINT_DEPTH_BY_THREAD[ident] = max(0, _PAINT_DEPTH_BY_THREAD.get(ident, 1) - 1)

    now_ns = time.monotonic_ns()
    started_ns = int(_LAST_PAINT_ACTIVITY.get("started_ns") or 0)
    _LAST_PAINT_ACTIVITY["ended_ns"] = now_ns
    _LAST_PAINT_ACTIVITY["duration_ms"] = (
        round(max(0.0, (now_ns - started_ns) / 1_000_000.0), 3)
        if started_ns > 0
        else None
    )
    _LAST_PAINT_ACTIVITY["in_progress"] = False

    _paint_breadcrumb_write(
        event="paint_path_end",
        paint_class=paint_class,
        paint_instance=paint_instance,
        operation=None,
        paint_depth=depth,
        **extra,
    )


def _paint_operation_enter(
    paint_class: str, paint_instance: str, operation: str, depth: int, **extra
) -> None:
    _LAST_PAINT_ACTIVITY["operation"] = str(operation)
    _paint_breadcrumb_write(
        event="paint_operation_enter",
        paint_class=paint_class,
        paint_instance=paint_instance,
        operation=operation,
        paint_depth=depth,
        **extra,
    )



# RC6.12B-r2 (measurement only): Selection-to-Paint Frequency Attribution.
#
# Purpose: find out, without changing any scheduling/debounce/repaint
# behavior, whether the GaugeWidget crash (Qt6Gui!QRasterPaintEngine::
# penChanged, RUNTIME VERIFIED across two builds at the same offset) is
# preceded by a burst of show_selected()/_update_pro_panels() activity
# ("paint storm" hypothesis) or occurs independently of it. Never calls
# processEvents()/repaint()/sendPostedEvents()/getCppPointer()/isValid(),
# never adds a new QTimer.singleShot(), never sleeps, never debounces or
# drops an update() call. Purely additive counters and breadcrumb fields.
_SELECTION_FORENSICS_PATH = Path("artifacts/runtime/selection_render_forensics.jsonl")
_PRO_PANEL_FORENSICS_PATH = Path("artifacts/runtime/pro_panel_update_forensics.jsonl")
_FREQ_LOCK = threading.Lock()
_FREQ_SEQUENCE = 0
_SELECTION_REQUEST_TIMES_NS: list = []  # sliding window, pruned to last 1000ms
_SELECTION_BATCH_SEQUENCE = 0
_LAST_PRO_PANEL_BATCH_NS: int | None = None
_PRO_PANEL_BATCH_TIMES_NS: list = []  # sliding window, pruned to last 1000ms


def _freq_next_sequence() -> int:
    global _FREQ_SEQUENCE
    with _FREQ_LOCK:
        _FREQ_SEQUENCE += 1
        return _FREQ_SEQUENCE


def _freq_write(path: Path, event: str, **fields) -> None:
    if _CLEAN_RUNTIME_DEFAULT:
        return
    row = {
        "schema_version": "dvs.runtime.selection_paint_frequency.v1",
        "event": str(event),
        "sequence": _freq_next_sequence(),
        "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        "monotonic_ns": time.monotonic_ns(),
        "pid": os.getpid(),
        "thread_ident": threading.get_ident(),
        **fields,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n"
        with _FREQ_LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
    except Exception:
        pass


def _prune_window(times_ns: list, now_ns: int, window_ms: int) -> int:
    cutoff = now_ns - window_ms * 1_000_000
    while times_ns and times_ns[0] < cutoff:
        times_ns.pop(0)
    return len(times_ns)


def _selection_request_counts(now_ns: int) -> dict:
    with _FREQ_LOCK:
        c100 = sum(1 for t in _SELECTION_REQUEST_TIMES_NS if t >= now_ns - 100_000_000)
        c500 = sum(1 for t in _SELECTION_REQUEST_TIMES_NS if t >= now_ns - 500_000_000)
        c1000 = sum(1 for t in _SELECTION_REQUEST_TIMES_NS if t >= now_ns - 1_000_000_000)
    return {
        "requests_in_last_100ms": c100,
        "requests_in_last_500ms": c500,
        "requests_in_last_1000ms": c1000,
    }


def _selection_request_recorded() -> None:
    now_ns = time.monotonic_ns()
    with _FREQ_LOCK:
        _SELECTION_REQUEST_TIMES_NS.append(now_ns)
        _prune_window(_SELECTION_REQUEST_TIMES_NS, now_ns, 1000)


def _pro_panel_batch_counts_and_record(now_ns: int) -> dict:
    global _LAST_PRO_PANEL_BATCH_NS
    with _FREQ_LOCK:
        since_prev_ms = (
            round((now_ns - _LAST_PRO_PANEL_BATCH_NS) / 1_000_000.0, 3)
            if _LAST_PRO_PANEL_BATCH_NS is not None
            else None
        )
        _LAST_PRO_PANEL_BATCH_NS = now_ns
        _PRO_PANEL_BATCH_TIMES_NS.append(now_ns)
        _prune_window(_PRO_PANEL_BATCH_TIMES_NS, now_ns, 1000)
        b100 = sum(1 for t in _PRO_PANEL_BATCH_TIMES_NS if t >= now_ns - 100_000_000)
        b500 = sum(1 for t in _PRO_PANEL_BATCH_TIMES_NS if t >= now_ns - 500_000_000)
        b1000 = len(_PRO_PANEL_BATCH_TIMES_NS)
    return {
        "time_since_previous_batch_ms": since_prev_ms,
        "batches_in_last_100ms": b100,
        "batches_in_last_500ms": b500,
        "batches_in_last_1000ms": b1000,
    }


def _next_selection_batch_sequence() -> int:
    global _SELECTION_BATCH_SEQUENCE
    with _FREQ_LOCK:
        _SELECTION_BATCH_SEQUENCE += 1
        return _SELECTION_BATCH_SEQUENCE


def _current_selection_batch_sequence() -> int:
    with _FREQ_LOCK:
        return _SELECTION_BATCH_SEQUENCE


class Sparkline(QWidget):
    def __init__(self):
        super().__init__()
        self.values = []
        self.setMinimumHeight(160)

    def set_values(self, values):
        self.values = list(values)[-80:]
        self.update()

    def paintEvent(self, event):
        _paint_instance = self.objectName() or "unnamed"
        _paint_depth = _paint_path_begin("Sparkline", _paint_instance)
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.fillRect(self.rect(), QColor("#0b1220"))
            if len(self.values) < 2:
                _paint_operation_enter("Sparkline", _paint_instance, "setPen.empty_state", _paint_depth)
                p.setPen(QColor("#94a3b8"))
                p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Chưa có dữ liệu")
                return
            lo, hi = min(self.values), max(self.values)
            span = max(hi - lo, 1e-12)
            pts = []
            w, h = self.width(), self.height()
            for i, v in enumerate(self.values):
                x = 12 + i * (w - 24) / (len(self.values) - 1)
                y = h - 18 - (v - lo) / span * (h - 36)
                pts.append(QPointF(x, y))
            _paint_operation_enter("Sparkline", _paint_instance, "setPen.line", _paint_depth)
            p.setPen(QPen(QColor("#22d3ee"), 2.2))
            for a, b in zip(pts, pts[1:]):
                p.drawLine(a, b)
            _paint_operation_enter("Sparkline", _paint_instance, "setPen.labels", _paint_depth)
            p.setPen(QColor("#64748b"))
            p.drawText(12, 18, f"High {hi:.8g}")
            p.drawText(12, h - 6, f"Low {lo:.8g}")
        finally:
            _paint_path_end("Sparkline", _paint_instance, _paint_depth)


class MetricCard(QFrame):
    def __init__(self, title: str, value: str = "-", subtitle: str = ""):
        super().__init__()
        self.setObjectName("MetricCard")
        self.setMinimumHeight(66)
        self.setMaximumHeight(82)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(1)
        self.title = QLabel(title); self.title.setObjectName("MetricTitle")
        self.value = QLabel(value); self.value.setObjectName("MetricValue")
        self.subtitle = QLabel(subtitle); self.subtitle.setObjectName("MetricSubtitle")
        for label in (self.title, self.value, self.subtitle):
            label.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Preferred,
            )
        layout.addWidget(self.title); layout.addWidget(self.value); layout.addWidget(self.subtitle)

    def set_data(self, value: str, subtitle: str = ""):
        self.value.setText(value)
        self.subtitle.setText(subtitle)

    def set_value(self, value, subtitle=None):
        self.value.setText(str(value))
        if subtitle is not None:
            self.subtitle.setText(str(subtitle))

class GaugeWidget(QWidget):
    """Đồng hồ bán nguyệt 0–100 cho Decision/Engine Score."""

    def __init__(self, title: str, inverse: bool = False, compact: bool = False):
        super().__init__()
        self.title = title
        self.value = 0.0
        self.subtitle = "Chưa có dữ liệu"
        self.inverse = inverse
        self.compact = compact
        self.setMinimumWidth(96 if compact else 180)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.setFixedHeight(96 if compact else 142)
        self.setProperty("scoreBand", "neutral")
        # RC6.12B-r2 (measurement only): in-memory counters, no file I/O
        # here since set_value() can be a hot path. Consumed and reset by
        # paintEvent() below, then attached to the existing paint
        # breadcrumb fields.
        self._update_requests_total = 0
        self._updates_since_last_paint = 0
        self._last_update_request_ns: int | None = None
        self._last_paint_end_ns: int | None = None
        self._last_value_color_name: str | None = None

        # RC6.12D causal control for Defect A3:
        # Render title/value/subtitle through standard child QLabel widgets.
        # The custom QPainter path is now limited to background + arcs, so the
        # three text-related QPainter.setPen() calls identified in native crash
        # evidence are removed without changing score calculation or updates.
        self._title_label = QLabel(self.title, self)
        self._value_label = QLabel("0", self)
        self._subtitle_label = QLabel(self.subtitle, self)

        # RC7.5: visual dial uses Qt's native QDial only. No application
        # QPainter/setPen/drawArc path is reintroduced.
        self._dial = QDial(self)
        self._dial.setRange(0, 100)
        self._dial.setValue(0)
        self._dial.setNotchesVisible(True)
        self._dial.setWrapping(False)
        self._dial.setTracking(False)
        self._dial.setEnabled(False)
        self._dial.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._dial.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )
        self._dial.setObjectName(
            "RiskDial" if self.inverse else "ScoreDial"
        )
        self._dial.setStyleSheet(
            "QDial {"
            "background:transparent;"
            "}"
        )
        for label in (self._title_label, self._value_label, self._subtitle_label):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            label.setStyleSheet("background: transparent; border: none;")

        title_font = QFont("Segoe UI", 8 if self.compact else 10)
        title_font.setBold(True)
        self._title_label.setFont(title_font)
        self._title_label.setStyleSheet(
            "background: transparent; border: none; color: #94a3b8;"
        )

        value_font = QFont("Segoe UI", 18 if self.compact else 31)
        value_font.setBold(True)
        self._value_label.setFont(value_font)

        subtitle_font = QFont("Segoe UI", 7 if self.compact else 10)
        subtitle_font.setBold(True)
        self._subtitle_label.setFont(subtitle_font)
        self._subtitle_label.setStyleSheet(
            "background: transparent; border: none; color: #e2e8f0;"
        )
        self._layout_text_labels()
        self._sync_text_labels()

    def _layout_text_labels(self) -> None:
        w, h = self.width(), self.height()
        self._title_label.setGeometry(6, 2, max(0, w - 12), 20)

        dial_size = min(
            52 if self.compact else 70,
            max(40, h - 30),
            max(40, int(w * 0.36)),
        )
        dial_x = 8
        dial_y = max(23, (h - dial_size) // 2 + 5)
        self._dial.setGeometry(
            dial_x,
            dial_y,
            dial_size,
            dial_size,
        )

        text_x = dial_x + dial_size + 2
        text_w = max(0, w - text_x - 6)
        self._value_label.setGeometry(
            text_x,
            max(22, int(h * 0.30)),
            text_w,
            30 if self.compact else 40,
        )
        self._subtitle_label.setGeometry(
            text_x,
            h - 25,
            text_w,
            18,
        )

    def _sync_text_labels(self) -> None:
        title_text = str(self.title)
        value_text = f"{self.value:.0f}"
        subtitle_text = str(self.subtitle)
        if self._title_label.text() != title_text:
            self._title_label.setText(title_text)
        if self._value_label.text() != value_text:
            self._value_label.setText(value_text)
        dial_value = int(round(self.value))
        if self._dial.value() != dial_value:
            self._dial.setValue(dial_value)
        if self._subtitle_label.text() != subtitle_text:
            self._subtitle_label.setText(subtitle_text)
        color_name = self._value_color().name()
        if color_name != self._last_value_color_name:
            self._last_value_color_name = color_name
            self._value_label.setStyleSheet(
                "background: transparent; border: none; "
                f"color: {color_name};"
            )
        score_band = self._score_band()
        if self.property("scoreBand") != score_band:
            self.setProperty("scoreBand", score_band)
            self.style().unpolish(self)
            self.style().polish(self)

    def resizeEvent(self, event):
        self._layout_text_labels()
        super().resizeEvent(event)

    def set_value(self, value: float, subtitle: str = ""):
        next_value = max(0.0, min(100.0, float(value)))
        previous_value = self.value
        previous_subtitle = self.subtitle
        self.value = next_value
        next_subtitle = subtitle or self._level_text()
        if (
            abs(previous_value - next_value) < 1e-9
            and previous_subtitle == next_subtitle
        ):
            return False
        self.subtitle = next_subtitle
        self._sync_text_labels()
        self._update_requests_total += 1
        self._updates_since_last_paint += 1
        self._last_update_request_ns = time.monotonic_ns()
        self.update()
        return True

    def _level_text(self):
        v = self.value
        if self.inverse:
            if v < 35: return "RỦI RO THẤP"
            if v < 55: return "RỦI RO TRUNG BÌNH"
            if v < 75: return "RỦI RO CAO"
            return "RỦI RO RẤT CAO"
        if v < 40: return "STAND ASIDE"
        if v < 60: return "WATCH"
        if v < 75: return "SETUP"
        if v < 88: return "READY"
        return "INSTITUTIONAL"

    def _score_band(self) -> str:
        value = float(self.value)
        if self.inverse:
            if value < 35:
                return "positive"
            if value < 55:
                return "watch"
            if value < 75:
                return "warning"
            return "critical"
        if value < 35:
            return "muted"
        if value < 60:
            return "watch"
        if value < 75:
            return "info"
        if value < 88:
            return "positive"
        return "premium"

    def _value_color(self):
        v = self.value
        if self.inverse:
            if v < 35: return QColor("#22c55e")
            if v < 55: return QColor("#facc15")
            if v < 75: return QColor("#fb923c")
            return QColor("#ef4444")
        if v < 40: return QColor("#64748b")
        if v < 60: return QColor("#facc15")
        if v < 75: return QColor("#38bdf8")
        if v < 88: return QColor("#22c55e")
        return QColor("#a78bfa")

    def paintEvent(self, event):
        # RC7.6-UI-C-r1 — fail-closed paint path.
        #
        # Rendering is standard QWidget rendering only. Forensic telemetry is
        # strictly secondary and must never prevent Qt from completing a paint
        # event. In particular, no undefined helper, file I/O, custom QPainter
        # operation or exception propagation is allowed across the
        # QWidget::paintEvent virtual boundary.
        paint_instance = self.title or self.objectName() or "unnamed"
        now_ns = time.monotonic_ns()
        updates_since_last_paint = int(self._updates_since_last_paint)
        last_update_ns = int(self._last_update_request_ns or 0)
        last_paint_end_ns = int(self._last_paint_end_ns or 0)

        common = {
            "updates_since_last_paint": updates_since_last_paint,
            "time_since_last_update_ms": (
                round(max(0.0, (now_ns - last_update_ns) / 1_000_000.0), 3)
                if last_update_ns > 0 else None
            ),
            "time_since_previous_paint_ms": (
                round(max(0.0, (now_ns - last_paint_end_ns) / 1_000_000.0), 3)
                if last_paint_end_ns > 0 else None
            ),
            "selection_batch_sequence": int(_SELECTION_BATCH_SEQUENCE or 0),
            "selection_requests_last_1000ms": 0,
        }

        # Use the already-defined, lock-protected helper. Any telemetry failure
        # is absorbed locally and cannot cross into Qt/Shiboken.
        try:
            common["selection_requests_last_1000ms"] = int(
                _selection_request_counts(now_ns).get(
                    "requests_in_last_1000ms",
                    0,
                )
            )
        except Exception:
            common["selection_requests_last_1000ms"] = 0

        depth = None
        try:
            try:
                depth = _paint_path_begin(
                    "GaugeWidget",
                    paint_instance,
                    **common,
                )
                _paint_operation_enter(
                    "GaugeWidget",
                    paint_instance,
                    "standard_widget_no_custom_painter",
                    depth,
                    **common,
                )
            except Exception:
                # Forensic instrumentation is best-effort only.
                depth = None

            # This call is unconditional. Qt always receives the standard paint
            # event even when every forensic helper fails.
            super().paintEvent(event)
        finally:
            end_ns = time.monotonic_ns()
            self._updates_since_last_paint = 0
            self._last_paint_end_ns = end_ns

            if depth is not None:
                try:
                    end_common = dict(common)
                    end_common["time_since_last_update_ms"] = (
                        round(
                            max(
                                0.0,
                                (end_ns - last_update_ns) / 1_000_000.0,
                            ),
                            3,
                        )
                        if last_update_ns > 0
                        else None
                    )
                    _paint_path_end(
                        "GaugeWidget",
                        paint_instance,
                        depth,
                        **end_common,
                    )
                except Exception:
                    # Never propagate telemetry errors across paintEvent.
                    pass


class MiniScoreCard(QFrame):
    def __init__(self, title: str, color: str):
        super().__init__()
        self.color = color
        self.setObjectName("MiniScoreCard")
        self.setProperty("scoreBand", "muted")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("MiniScoreTitle")
        self.value = QLabel("0/100")
        self.value.setObjectName("MiniScoreValue")
        self.dial = QDial()
        self.dial.setRange(0, 100)
        self.dial.setValue(0)
        self.dial.setNotchesVisible(True)
        self.dial.setEnabled(False)
        self.dial.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.dial.setFixedSize(46, 46)
        self.dial.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )
        self.dial.setStyleSheet("QDial{background:transparent;}")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setMaximumHeight(7)
        self.bar.setStyleSheet(
            f"QProgressBar{{background:#1e293b;border:0;border-radius:3px;}}"
            f"QProgressBar::chunk{{background:{color};border-radius:3px;}}"
        )
        layout.addWidget(self.title)
        score_row = QHBoxLayout()
        score_row.setContentsMargins(0, 0, 0, 0)
        score_row.setSpacing(6)
        score_row.addWidget(self.dial, 0)
        score_row.addWidget(self.value, 1)
        layout.addLayout(score_row)
        layout.addWidget(self.bar)

    def set_score(self, score: float):
        score = max(0, min(100, int(round(score))))
        self.value.setText(f"{score}/100")
        self.value.setStyleSheet(
            f"color:{self.color};font-size:21px;font-weight:700;"
        )
        self.dial.setValue(score)
        self.bar.setValue(score)
        score_band = (
            "muted" if score < 35
            else "watch" if score < 60
            else "info" if score < 75
            else "positive" if score < 88
            else "premium"
        )
        if self.property("scoreBand") != score_band:
            self.setProperty("scoreBand", score_band)
            self.style().unpolish(self)
            self.style().polish(self)


class CoinManagerDialog(QDialog):
    def __init__(self, coins: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Quản lý danh sách coin")
        self.resize(560, 620)
        layout = QVBoxLayout(self)

        note = QLabel(
            "Chỉ hỗ trợ hợp đồng Binance Futures USDT. "
            "Nhập BTC hoặc BTC/USDT:USDT rồi bấm Thêm."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "🔎 Tìm nhanh trong danh sách, ví dụ BTC, ETH, PEPE..."
        )
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)

        self.list_widget = QListWidget()
        self.list_widget.addItems(coins)
        layout.addWidget(self.list_widget, 1)

        self.count_label = QLabel()
        layout.addWidget(self.count_label)

        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ví dụ: ARB hoặc ARB/USDT:USDT")
        self.input.setClearButtonEnabled(True)
        add_btn = QPushButton("Thêm")
        remove_btn = QPushButton("Xóa mục chọn")
        row.addWidget(self.input, 1)
        row.addWidget(add_btn)
        row.addWidget(remove_btn)
        layout.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.search.textChanged.connect(self.filter_coins)
        self.input.returnPressed.connect(self.add_coin)
        add_btn.clicked.connect(self.add_coin)
        remove_btn.clicked.connect(self.remove_coin)
        self._update_count()

    @staticmethod
    def normalize_symbol(raw: str) -> str:
        symbol = str(raw).strip().upper().replace(" ", "")
        if not symbol:
            return ""
        if "/" not in symbol:
            symbol = f"{symbol}/USDT:USDT"
        elif ":USDT" not in symbol:
            symbol = f"{symbol}:USDT"
        return symbol

    def filter_coins(self, text: str):
        query = text.strip().upper()
        visible = 0
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            matched = not query or query in item.text().upper()
            item.setHidden(not matched)
            visible += int(matched)
        self._update_count(visible)

    def _update_count(self, visible: int | None = None):
        total = self.list_widget.count()
        if visible is None:
            visible = sum(
                not self.list_widget.item(i).isHidden()
                for i in range(total)
            )
        self.count_label.setText(
            f"Đang hiển thị {visible}/{total} coin."
        )

    def add_coin(self):
        symbol = self.normalize_symbol(self.input.text())
        if not symbol:
            return
        existing = {
            self.list_widget.item(i).text()
            for i in range(self.list_widget.count())
        }
        if symbol not in existing:
            self.list_widget.addItem(symbol)
            self.search.clear()
            self.list_widget.scrollToBottom()
        self.input.clear()
        self._update_count()

    def remove_coin(self):
        for item in self.list_widget.selectedItems():
            self.list_widget.takeItem(self.list_widget.row(item))
        self._update_count()

    def coins(self) -> list[str]:
        return [
            self.list_widget.item(i).text()
            for i in range(self.list_widget.count())
        ]


class LearningRefreshWorker(QObject):
    ready = Signal(object)
    failed = Signal(str)
    cancelled = Signal(str)

    def __init__(self, learning_service, quantum_db_path: str, quantum_required: int):
        super().__init__()
        self.learning_service = learning_service
        self.quantum_db_path = str(quantum_db_path)
        self.quantum_required = int(quantum_required)
        # Thread-safe cooperative stop flag. closeEvent() sets it directly from
        # the GUI thread because a queued stop slot cannot run while refresh()
        # itself is occupying the worker thread.
        self._stop_requested = threading.Event()
        self._lifecycle_refresh_cycle = 0
        self._lifecycle_refresh_active = False
        self._lifecycle_active_stage = None
        self._lifecycle_refresh_started_ns = None
        self._lifecycle_stage_started_ns = None
        self._lifecycle_last_completed_stage = None
        self._lifecycle_last_completed_stage_ns = None
        self._lifecycle_stop_requested_ns = None
        setter = getattr(self.learning_service, "set_cancel_check", None)
        if callable(setter):
            setter(self._cancel_requested)
        try:
            from dvs_ai.runtime.learning_refresh_lifecycle import record_learning_refresh_event
            record_learning_refresh_event("worker_created", worker=self)
        except Exception:
            pass

    def request_stop(self) -> None:
        self._lifecycle_stop_requested_ns = time.monotonic_ns()
        self._stop_requested.set()
        try:
            from dvs_ai.runtime.learning_refresh_lifecycle import record_learning_refresh_event
            record_learning_refresh_event("stop_requested", worker=self)
        except Exception:
            pass

    def _cancel_requested(self, stage: str) -> bool:
        cancelled = bool(self._stop_requested.is_set())
        if cancelled:
            try:
                from dvs_ai.runtime.learning_cooperative_return import (
                    record_cooperative_return,
                )
                record_cooperative_return(
                    "worker_cancel_observed",
                    stage=str(stage),
                    refresh_cycle=int(self._lifecycle_refresh_cycle),
                    active_stage=self._lifecycle_active_stage,
                )
            except Exception:
                pass
        return cancelled

    def _return_cancelled(self, stage: str) -> None:
        reason = f"learning_refresh_cancelled:{stage}"
        try:
            from dvs_ai.runtime.learning_refresh_lifecycle import (
                record_learning_refresh_event,
            )
            record_learning_refresh_event(
                "refresh_cancelled",
                worker=self,
                reason=reason,
                cancellation_mode="cooperative_return",
            )
        except Exception:
            pass
        try:
            from dvs_ai.runtime.learning_cooperative_return import (
                record_cooperative_return,
            )
            record_cooperative_return(
                "worker_cooperative_return",
                stage=str(stage),
                reason=reason,
                refresh_cycle=int(self._lifecycle_refresh_cycle),
            )
        except Exception:
            pass
        self.cancelled.emit(reason)

    @Slot()
    def refresh(self) -> None:
        from dvs_ai.runtime.learning_refresh_lifecycle import (
            record_learning_refresh_event,
        )
        self._lifecycle_refresh_cycle += 1
        self._lifecycle_refresh_active = True
        self._lifecycle_refresh_started_ns = time.monotonic_ns()
        self._lifecycle_active_stage = "refresh_entry"
        self._lifecycle_stage_started_ns = self._lifecycle_refresh_started_ns
        record_learning_refresh_event(
            "refresh_enter",
            worker=self,
            cancellation_mode="cooperative_return",
        )
        try:
            if self._cancel_requested("before_readiness"):
                self._return_cancelled("before_readiness")
                return

            self._lifecycle_active_stage = "readiness"
            self._lifecycle_stage_started_ns = time.monotonic_ns()
            record_learning_refresh_event(
                "stage_enter", worker=self, stage="readiness"
            )
            readiness = QuantumReadinessService(
                self.quantum_db_path, required=self.quantum_required
            ).snapshot()
            self._lifecycle_last_completed_stage = "readiness"
            self._lifecycle_last_completed_stage_ns = time.monotonic_ns()
            record_learning_refresh_event(
                "stage_exit", worker=self, stage="readiness"
            )
            if self._cancel_requested("after_readiness"):
                self._return_cancelled("after_readiness")
                return

            payload = {"readiness": readiness}
            stages = (
                ("overview", lambda: self.learning_service.overview()),
                ("main_overview", lambda: self.learning_service.overview("MAIN")),
                ("shadow_overview", lambda: self.learning_service.overview("SHADOW")),
                ("setup_performance", self.learning_service.setup_performance),
                ("confidence_calibration", self.learning_service.confidence_calibration),
                ("rejection_monitor", self.learning_service.rejection_monitor),
                ("threshold_comparison", self.learning_service.threshold_comparison),
                ("execution_diagnostics", self.learning_service.execution_diagnostics),
                ("weight_recommendations", self.learning_service.weight_recommendations),
            )
            for stage, operation in stages:
                if self._cancel_requested(f"before_{stage}"):
                    self._return_cancelled(f"before_{stage}")
                    return

                self._lifecycle_active_stage = stage
                self._lifecycle_stage_started_ns = time.monotonic_ns()
                record_learning_refresh_event(
                    "stage_enter", worker=self, stage=stage
                )
                result = operation()

                if self._cancel_requested(f"during_{stage}_return"):
                    record_learning_refresh_event(
                        "stage_return_discarded",
                        worker=self,
                        stage=stage,
                        cancellation_mode="cooperative_return",
                    )
                    self._return_cancelled(f"during_{stage}_return")
                    return

                payload[stage] = result
                self._lifecycle_last_completed_stage = stage
                self._lifecycle_last_completed_stage_ns = time.monotonic_ns()
                record_learning_refresh_event(
                    "stage_exit", worker=self, stage=stage
                )

            if self._cancel_requested("before_ready_emit"):
                self._return_cancelled("before_ready_emit")
                return

            self._lifecycle_active_stage = "ready_emit"
            self._lifecycle_stage_started_ns = time.monotonic_ns()
            record_learning_refresh_event("ready_emit_begin", worker=self)
            self.ready.emit(payload)
            record_learning_refresh_event("ready_emit_end", worker=self)
        except Exception as exc:
            record_learning_refresh_event(
                "refresh_failed",
                worker=self,
                error_type=type(exc).__name__,
                error=str(exc),
                cancellation_mode="cooperative_return",
            )
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self._lifecycle_refresh_active = False
            self._lifecycle_active_stage = None
            self._lifecycle_stage_started_ns = None
            record_learning_refresh_event(
                "refresh_exit",
                worker=self,
                cancellation_mode="cooperative_return",
            )


class HistoryPrepareWorker(QObject):
    prepared = Signal(int, str, object, object)

    @Slot(int, str, object)
    def prepare(self, generation: int, reason: str, request: object) -> None:
        started = time.perf_counter()
        _write_signal_path_worker_event(
            "history", "worker_slot_entered", generation=int(generation),
            request_reason=str(reason), worker_class=type(self).__name__,
            worker_object_id=hex(id(self)),
        )
        req_probe = dict(request or {})
        if req_probe.get("__queued_signal_probe__"):
            timing={"query_ms":0.0,"transform_ms":0.0,
                    "data_prepare_ms":(time.perf_counter()-started)*1000.0,
                    "thread_name":QThread.currentThread().objectName(),
                    "failure_type":None,"signal_probe":True}
            _write_signal_path_worker_event("history", "worker_result_emit_begin",
                                            generation=int(generation), request_reason=str(reason))
            self.prepared.emit(int(generation), str(reason),
                               {"stats":{},"rows":[],"signal_probe":True}, timing)
            _write_signal_path_worker_event("history", "worker_result_emit_end",
                                            generation=int(generation), request_reason=str(reason))
            return
        query_started = started
        try:
            db_path = str(req_probe.get("db_path", "data/dvs_signals.db"))
            rows = []
            stats = {
                "count": 0, "ready": 0, "avg_confidence": 0.0,
                "resolved": 0, "wins": 0, "losses": 0,
                "ambiguous": 0, "expired": 0, "win_rate": 0.0, "avg_r": 0.0,
            }
            # Connection is intentionally created inside the worker slot.
            if Path(db_path).exists():
                with sqlite3.connect(db_path, timeout=3.0) as con:
                    con.execute("PRAGMA busy_timeout=3000")
                    rows = con.execute("""
                        SELECT generated_at, symbol, direction, entry_status,
                               confidence, long_trend, long_entry, short_trend,
                               short_entry, price, phase, oi_state,
                               COALESCE(outcome,'PENDING'), COALESCE(r_multiple,0),
                               COALESCE(outcome_detail,'')
                        FROM scan_signals ORDER BY id DESC LIMIT 300
                    """).fetchall()
                    row = con.execute("""
                        SELECT COUNT(*),
                          SUM(CASE WHEN entry_status='READY' THEN 1 ELSE 0 END),
                          COALESCE(AVG(confidence),0),
                          SUM(CASE WHEN outcome IN ('TP2','INVALID','PARTIAL_STOP') THEN 1 ELSE 0 END),
                          SUM(CASE WHEN outcome IN ('TP2','INVALID','PARTIAL_STOP') AND COALESCE(r_multiple,0)>0 THEN 1 ELSE 0 END),
                          SUM(CASE WHEN outcome IN ('TP2','INVALID','PARTIAL_STOP') AND COALESCE(r_multiple,0)<=0 THEN 1 ELSE 0 END),
                          SUM(CASE WHEN outcome IN ('AMBIGUOUS','PARTIAL_AMBIGUOUS') THEN 1 ELSE 0 END),
                          SUM(CASE WHEN outcome='EXPIRED' THEN 1 ELSE 0 END),
                          COALESCE(AVG(CASE WHEN outcome IN ('TP2','INVALID','PARTIAL_STOP') THEN r_multiple END),0)
                        FROM scan_signals
                    """).fetchone()
                resolved=int(row[3] or 0); wins=int(row[4] or 0)
                stats={"count":int(row[0] or 0),"ready":int(row[1] or 0),
                       "avg_confidence":float(row[2] or 0.0),"resolved":resolved,
                       "wins":wins,"losses":int(row[5] or 0),"ambiguous":int(row[6] or 0),
                       "expired":int(row[7] or 0),"win_rate":wins/resolved*100.0 if resolved else 0.0,
                       "avg_r":float(row[8] or 0.0)}
            query_ms=(time.perf_counter()-query_started)*1000.0
            transform_started=time.perf_counter()
            display_rows=[]
            for data in rows:
                display_rows.append([
                    data[0], str(data[1]).replace(":USDT",""), data[2], data[3],
                    f"{float(data[4]):.1f}", f"{float(data[5]):.1f}", f"{float(data[6]):.1f}",
                    f"{float(data[7]):.1f}", f"{float(data[8]):.1f}", f"{float(data[9]):.8g}",
                    data[10], data[11], data[12], f"{float(data[13]):+.2f}", data[14]
                ])
            transform_ms=(time.perf_counter()-transform_started)*1000.0
            payload={"stats":stats,"rows":display_rows}
            timing={"query_ms":query_ms,"transform_ms":transform_ms,
                    "data_prepare_ms":(time.perf_counter()-started)*1000.0,
                    "thread_name":QThread.currentThread().objectName(),"failure_type":None}
            _write_signal_path_worker_event("history", "worker_result_emit_begin",
                                            generation=int(generation), request_reason=str(reason))
            self.prepared.emit(int(generation), str(reason), payload, timing)
            _write_signal_path_worker_event("history", "worker_result_emit_end",
                                            generation=int(generation), request_reason=str(reason))
        except Exception as exc:
            timing={"query_ms":0.0,"transform_ms":0.0,
                    "data_prepare_ms":(time.perf_counter()-started)*1000.0,
                    "thread_name":QThread.currentThread().objectName(),"failure_type":type(exc).__name__,
                    "message":str(exc)[:240]}
            self.prepared.emit(int(generation), str(reason), {}, timing)


class PaperTradePrepareWorker(QObject):
    prepared = Signal(int, str, object, object)

    @staticmethod
    def _stats(con, pilot_id: str, lab: str) -> dict:
        row=con.execute("""
          SELECT COUNT(*), SUM(CASE WHEN direction='LONG' THEN 1 ELSE 0 END),
          SUM(CASE WHEN direction='SHORT' THEN 1 ELSE 0 END),
          SUM(CASE WHEN status='CLOSED' THEN 1 ELSE 0 END),
          SUM(CASE WHEN status='CLOSED' AND r_multiple>0 THEN 1 ELSE 0 END),
          SUM(CASE WHEN status='CLOSED' AND r_multiple<0 THEN 1 ELSE 0 END),
          SUM(CASE WHEN status='CLOSED' AND r_multiple=0 THEN 1 ELSE 0 END),
          COALESCE(AVG(CASE WHEN status='CLOSED' THEN r_multiple END),0),
          COALESCE(SUM(CASE WHEN r_multiple>0 THEN r_multiple ELSE 0 END),0),
          ABS(COALESCE(SUM(CASE WHEN r_multiple<0 THEN r_multiple ELSE 0 END),0)),
          SUM(CASE WHEN result IN ('AMBIGUOUS','PARTIAL_AMBIGUOUS') THEN 1 ELSE 0 END),
          SUM(CASE WHEN result='EXPIRED' THEN 1 ELSE 0 END)
          FROM paper_trades WHERE pilot_id=? AND lab=?
        """,(pilot_id,lab)).fetchone()
        closed=int(row[3] or 0); wins=int(row[4] or 0); amb=int(row[10] or 0); exp=int(row[11] or 0)
        determinate=max(0,closed-amb-exp); gw=float(row[8] or 0); gl=float(row[9] or 0)
        pf=float('inf') if gw>0 and gl==0 else (gw/gl if gl>0 else 0.0)
        return {"total":int(row[0] or 0),"longs":int(row[1] or 0),"shorts":int(row[2] or 0),
                "closed":closed,"wins":wins,"losses":int(row[5] or 0),"breakeven":int(row[6] or 0),
                "win_rate":wins/determinate*100.0 if determinate else 0.0,"avg_r":float(row[7] or 0),
                "profit_factor":pf,"ambiguous":amb,"expired":exp,"determinate":determinate}

    @Slot(int, str, object)
    def prepare(self, generation: int, reason: str, request: object) -> None:
        started=time.perf_counter()
        _write_signal_path_worker_event(
            "paper", "worker_slot_entered", generation=int(generation),
            request_reason=str(reason), worker_class=type(self).__name__,
            worker_object_id=hex(id(self)),
        )
        req=dict(request or {})
        if req.get("__queued_signal_probe__"):
            timing={"query_ms":0.0,"transform_ms":0.0,
                    "data_prepare_ms":(time.perf_counter()-started)*1000.0,
                    "thread_name":QThread.currentThread().objectName(),
                    "failure_type":None,"signal_probe":True}
            _write_signal_path_worker_event("paper", "worker_result_emit_begin",
                                            generation=int(generation), request_reason=str(reason))
            self.prepared.emit(int(generation),str(reason),
                               {"main":{},"shadow":{},"diagnostics":{},
                                "rows":[],"raw_rows":[],"signal_probe":True},timing)
            _write_signal_path_worker_event("paper", "worker_result_emit_end",
                                            generation=int(generation), request_reason=str(reason))
            return
        try:
            db_path=str(req.get("db_path","data/dvs_paper_trades.db"))
            query_started=time.perf_counter()
            # Connection is intentionally created inside the worker slot.
            with sqlite3.connect(db_path, timeout=3.0) as con:
                con.execute("PRAGMA busy_timeout=3000")
                main=self._stats(con,str(req.get("main_pilot_id","PILOT_5L_5S_V1")),"MAIN")
                shadow=self._stats(con,str(req.get("shadow_pilot_id","SHADOW_50L_50S_V1")),"SHADOW")
                active=int(con.execute("SELECT COUNT(*) FROM paper_trades WHERE status IN ('PENDING','ACTIVE','TP1_HIT')").fetchone()[0])
                last_created=con.execute("SELECT MAX(created_at) FROM paper_trades").fetchone()[0]
                rows=con.execute("""SELECT id,lab,created_at,symbol,direction,source,status,
                    entry_low,entry_high,fill_price,invalidation,tp1,tp2,confidence,entry_score,risk_score,
                    result,r_multiple,mfe_r,mae_r,outcome_detail,realized_slippage_rate
                    FROM paper_trades ORDER BY id DESC LIMIT 200""").fetchall()
            query_ms=(time.perf_counter()-query_started)*1000.0
            transform_started=time.perf_counter(); display_rows=[]
            for d in rows:
                display_rows.append([str(d[0]),d[1],d[2],str(d[3]).replace(":USDT",""),d[4],d[5],d[6],
                  f"{float(d[7]):.8g}",f"{float(d[8]):.8g}","-" if d[9] is None else f"{float(d[9]):.8g}",
                  f"{float(d[10]):.8g}",f"{float(d[11]):.8g}",f"{float(d[12]):.8g}",f"{float(d[13]):.1f}",
                  f"{float(d[14]):.1f}",f"{float(d[15]):.1f}",d[16],f"{float(d[17]):+.2f}",
                  f"{float(d[18]):+.2f}",f"{float(d[19]):+.2f}",f"{float(d[21] or 0.0)*100.0:.3f}%"])
            transform_ms=(time.perf_counter()-transform_started)*1000.0
            diag={**dict(req.get("diagnostics",{})),"active_trades":active,
                  "last_trade_created_at":last_created,"db_path":str(Path(db_path).resolve())}
            payload={"main":main,"shadow":shadow,"diagnostics":diag,"rows":display_rows,
                     "raw_rows":rows}
            timing={"query_ms":query_ms,"transform_ms":transform_ms,
                    "data_prepare_ms":(time.perf_counter()-started)*1000.0,
                    "thread_name":QThread.currentThread().objectName(),"failure_type":None}
            _write_signal_path_worker_event("paper", "worker_result_emit_begin",
                                            generation=int(generation), request_reason=str(reason))
            self.prepared.emit(int(generation),str(reason),payload,timing)
            _write_signal_path_worker_event("paper", "worker_result_emit_end",
                                            generation=int(generation), request_reason=str(reason))
        except Exception as exc:
            timing={"query_ms":0.0,"transform_ms":0.0,
                    "data_prepare_ms":(time.perf_counter()-started)*1000.0,
                    "thread_name":QThread.currentThread().objectName(),"failure_type":type(exc).__name__,
                    "message":str(exc)[:240]}
            self.prepared.emit(int(generation),str(reason),{},timing)


class QualificationMetricsWorker(QObject):
    """V2.4: fetch qualification metrics outside the GUI thread.

    The worker emits one aggregate result per request. SQLite/query work is
    isolated from the batch-completed GUI callback; latest-generation wins is
    enforced by MainWindow when the payload returns.
    """
    ready = Signal(int, object, object)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self._store = store

    @Slot(int, object)
    def collect(self, generation: int, request_meta: object) -> None:
        started_ns = time.perf_counter_ns()
        payload = None
        error = None
        try:
            metrics = self._store.metrics() if self._store is not None else None
            analytics = self._store.analytics() if self._store is not None else None
            payload = {"metrics": metrics, "analytics": analytics}
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        timing = {
            "execution_ms": round((time.perf_counter_ns() - started_ns) / 1_000_000.0, 3),
            "thread_name": QThread.currentThread().objectName(),
            "error": error,
            "request_meta": dict(request_meta or {}),
        }
        self.ready.emit(int(generation), payload, timing)


class MainWindow(QMainWindow):
    _universe_load_requested = Signal(str, int, float)
    _outcome_update_requested = Signal(int)
    _api_health_check_requested = Signal(str)

    _scan_run_requested = Signal()
    _learning_refresh_requested = Signal()
    _signal_record_requested = Signal(object, object)
    _auto_paper_work_requested = Signal(object, object, object, bool)
    _history_prepare_requested = Signal(int, str, object)
    _paper_prepare_requested = Signal(int, str, object)
    _qualification_metrics_requested = Signal(int, object)

    def __init__(
        self, config, service, recorder, history_service,
        outcome_tracker, paper_trade_service, learning_service, order_flow_runtime=None, shadow_observation_runtime=None, core_runtime_adapter: CoreRuntimeAdapter | None = None, core_shadow_agreement_store: CoreShadowAgreementStore | None = None, core_qualification_batch_runner: CoreQualificationBatchRunner | None = None, live_episode_capture=None
    ):
        super().__init__()
        self._startup_init_started_ns = time.perf_counter_ns()
        self._startup_show_seen = False
        self._startup_first_paint_seen = False
        self._startup_deferred_scheduled = False
        self._after_first_paint_callbacks = []
        # RC6.4.7E-r1: runtime identity must exist before any startup telemetry
        # or worker/thread initialization can read it.  Keeping this assignment
        # immediately after QMainWindow construction prevents partial-startup
        # crashes and orphaned QThreads when early telemetry is emitted.
        self._runtime_session_id = f"{os.getpid()}-{uuid.uuid4().hex[:10]}"
        self._clean_runtime_mode = bool(_CLEAN_RUNTIME_DEFAULT)
        self.paint_scheduler = FramePaintScheduler(self, frame_interval_ms=16, frame_budget_ms=5.0)
        self.config = config
        self.service = service
        self._record_startup_phase("base_window_and_identity", self._startup_init_started_ns)
        _startup_phase_ns = time.perf_counter_ns()
        self.recorder = recorder
        self._signal_record_thread = QThread(self)
        self._signal_record_thread.setObjectName("dvs-signal-recorder")
        self._signal_record_worker = SignalRecordWorker(self.recorder)
        self._signal_record_worker.moveToThread(self._signal_record_thread)
        self._signal_record_requested.connect(
            self._signal_record_worker.record,
            Qt.ConnectionType.QueuedConnection,
        )
        self._signal_record_worker.completed.connect(
            self._on_signal_record_completed,
            Qt.ConnectionType.QueuedConnection,
        )
        self._signal_record_worker.failed.connect(
            self._on_signal_record_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        self._signal_record_thread.finished.connect(
            self._signal_record_worker.deleteLater
        )
        self._signal_record_thread.start()

        # RC7.9 — measured GUI-latency fix.
        # V53 gui_hotspots showed Qt dispatch itself occasionally blocked the
        # GUI thread (recorder enqueue max ~300 ms; live capture submit max
        # ~184 ms). A single bounded Python dispatcher moves only those two
        # submission calls off the GUI thread. Actual recorder/capture work
        # remains on the existing workers and preserves ordering.
        self._result_dispatch_queue = queue.Queue(maxsize=2048)
        self._result_dispatch_stop = threading.Event()
        self._result_dispatch_thread = threading.Thread(
            target=self._result_dispatch_loop,
            name="dvs-result-dispatch",
            daemon=True,
        )
        self._result_dispatch_thread.start()
        self._record_startup_phase("signal_recorder_worker_setup", _startup_phase_ns)
        _startup_phase_ns = time.perf_counter_ns()
        self.history_service = history_service
        self.outcome_tracker = outcome_tracker
        self.paper_trade_service = paper_trade_service
        # Sprint A2 V2: persistent, bounded data-prepare workers. Each worker
        # creates its SQLite connection inside its own thread.
        self._data_prepare_state = {
            "history": {"generation": 0, "running": False, "pending": None},
            "paper": {"generation": 0, "running": False, "pending": None},
        }
        self._history_prepare_thread = QThread(self)
        self._history_prepare_thread.setObjectName("dvs-history-data-worker")
        self._history_prepare_worker = HistoryPrepareWorker()
        self._history_prepare_worker.moveToThread(self._history_prepare_thread)
        self._history_prepare_requested.connect(self._history_prepare_worker.prepare, Qt.ConnectionType.QueuedConnection)
        self._history_prepare_worker.prepared.connect(self._on_history_prepared, Qt.ConnectionType.QueuedConnection)
        self._history_prepare_thread.finished.connect(self._history_prepare_worker.deleteLater)
        self._history_prepare_thread.start()
        self._paper_prepare_thread = QThread(self)
        self._paper_prepare_thread.setObjectName("dvs-paper-data-worker")
        self._paper_prepare_worker = PaperTradePrepareWorker()
        self._paper_prepare_worker.moveToThread(self._paper_prepare_thread)
        self._paper_prepare_requested.connect(self._paper_prepare_worker.prepare, Qt.ConnectionType.QueuedConnection)
        self._paper_prepare_worker.prepared.connect(self._on_paper_prepared, Qt.ConnectionType.QueuedConnection)
        self._paper_prepare_thread.finished.connect(self._paper_prepare_worker.deleteLater)
        self._paper_prepare_thread.start()
        self._history_render_state = None
        self._paper_render_state = None
        self._auto_paper_inflight = False
        self._auto_paper_worker_thread = QThread(self)
        self._auto_paper_worker_thread.setObjectName("dvs-auto-paper-worker")
        self._auto_paper_worker = AutoPaperWorker(self.paper_trade_service)
        self._auto_paper_worker.moveToThread(self._auto_paper_worker_thread)
        self._auto_paper_work_requested.connect(
            self._auto_paper_worker.process, Qt.ConnectionType.QueuedConnection
        )
        self._auto_paper_worker.completed.connect(
            self._on_auto_paper_worker_completed, Qt.ConnectionType.QueuedConnection
        )
        self._auto_paper_worker.failed.connect(
            self._on_auto_paper_worker_failed, Qt.ConnectionType.QueuedConnection
        )
        self._auto_paper_worker_thread.finished.connect(
            self._auto_paper_worker.deleteLater
        )
        self._auto_paper_worker_thread.start()
        # IR-01A-r1 queued-signal fail-fast gate.  This deliberately tests the
        # real MainWindow -> worker -> MainWindow signal paths.  It never
        # reconnects or repairs a failed path; failure disables affected
        # pipelines and is surfaced through telemetry/status.
        self._queued_signal_self_test = {
            "started": False, "finished": False, "passed": False,
            "token": uuid.uuid4().hex, "expected": {"history", "paper", "auto_paper"},
            "received": set(), "deadline_ms": 3500,
        }

        # RC7.12: pipeline-local fail-closed gates.
        # A failure of history or paper UI preparation must never disable the
        # independent Auto Paper worker path.  Each pipeline is enabled only if
        # its own startup round-trip probe succeeds.
        self._queued_signal_pipeline_enabled = {
            "history": True,
            "paper": True,
            "auto_paper": True,
        }
        # Legacy aggregate retained only for diagnostics/backward compatibility.
        self._queued_signal_pipelines_enabled = True
        QTimer.singleShot(0, self._start_queued_signal_self_test)
        self._auto_paper_payload_pending = {}
        self._auto_paper_payload_dispatched_total = 0
        self._auto_paper_payload_released_total = 0
        self._auto_paper_worker_object_id = hex(id(self._auto_paper_worker))
        # RC6.4.7E: full-heap census is diagnostic-only and default disabled.
        # Enable explicitly with DVS_OBJECT_CENSUS_ENABLED=1.  When disabled no
        # worker, QThread, QTimer or gc.get_objects() traversal is created.
        self._record_startup_phase("data_prepare_and_auto_paper_workers", _startup_phase_ns)
        _startup_phase_ns = time.perf_counter_ns()
        self._object_census_enabled = (
            (not self._clean_runtime_mode)
            and str(os.environ.get("DVS_OBJECT_CENSUS_ENABLED", "0"))
            .strip()
            .lower()
            in {"1", "true", "yes", "on"}
        )
        self._object_census_thread = None
        self._object_census_worker = None
        self._append_rc63_jsonl("object_census.jsonl", {
            "schema_version": "dvs.runtime.object_census.control.v1",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "runtime_session_id": self._runtime_session_id,
            "event": "object_census_configuration",
            "census_enabled": bool(self._object_census_enabled),
            "source": "DVS_OBJECT_CENSUS_ENABLED",
        })
        if self._object_census_enabled:
            self._object_census_thread = QThread(self)
            self._object_census_thread.setObjectName("dvs-object-census-worker")
            self._object_census_worker = ObjectCensusWorker(interval_ms=300_000)
            self._object_census_worker.moveToThread(self._object_census_thread)
            self._object_census_thread.started.connect(self._object_census_worker.start)
            self._object_census_worker.snapshot_ready.connect(
                self._on_object_census_snapshot, Qt.ConnectionType.QueuedConnection
            )
            self._object_census_worker.scan_failed.connect(
                self._on_object_census_failed, Qt.ConnectionType.QueuedConnection
            )
            self._object_census_worker.stopped.connect(
                self._object_census_thread.quit, Qt.ConnectionType.QueuedConnection
            )
            self._object_census_thread.finished.connect(self._object_census_worker.deleteLater)
            self._object_census_thread.start()
        self._record_startup_phase("object_census_setup", _startup_phase_ns)
        _startup_phase_ns = time.perf_counter_ns()
        self.learning_service = learning_service
        self.order_flow_runtime = order_flow_runtime
        self.shadow_observation_runtime = shadow_observation_runtime or getattr(paper_trade_service, "observation_runtime", None)
        self.core_runtime_adapter = core_runtime_adapter
        self._selection_render_active = False
        self._selection_render_pending = False
        self._selection_render_started_ns = 0
        self._detail_render_generation = 0
        self._detail_render_iterator = None
        self._detail_render_stage = "idle"
        self.core_shadow_agreement_store = core_shadow_agreement_store
        self.core_qualification_batch_runner = core_qualification_batch_runner
        self._qualification_metrics_generation = 0
        self._qualification_metrics_submitted_ns = {}
        self._qualification_render_cache = {}
        self._qualification_render_generation = 0
        self._auto_paper_prepare_state = None
        self._auto_paper_prepare_budget_ms = 8.0
        self._auto_paper_prepare_max_items_per_turn = 8
        self._qualification_metrics_thread = QThread(self)
        self._qualification_metrics_thread.setObjectName("dvs-qualification-metrics-worker")
        self._qualification_metrics_worker = QualificationMetricsWorker(core_shadow_agreement_store)
        self._qualification_metrics_worker.moveToThread(self._qualification_metrics_thread)
        self._qualification_metrics_requested.connect(
            self._qualification_metrics_worker.collect, Qt.ConnectionType.QueuedConnection
        )
        self._qualification_metrics_worker.ready.connect(
            self._on_qualification_metrics_ready, Qt.ConnectionType.QueuedConnection
        )
        self._qualification_metrics_thread.finished.connect(
            self._qualification_metrics_worker.deleteLater
        )
        self._qualification_metrics_thread.start()
        self.live_episode_capture = live_episode_capture
        if self.live_episode_capture is not None:
            completed_signal = getattr(self.live_episode_capture, "capture_completed", None)
            if completed_signal is not None:
                completed_signal.connect(self._on_live_episode_capture_completed)
            failed_signal = getattr(self.live_episode_capture, "capture_failed", None)
            if failed_signal is not None:
                failed_signal.connect(self._on_live_episode_capture_failed)
            rejected_signal = getattr(self.live_episode_capture, "capture_rejected", None)
            if rejected_signal is not None:
                rejected_signal.connect(self._on_live_episode_capture_rejected)
        self._qualification_batch_last_summary = None
        self._core_shadow_latest_request_id = None
        self._core_shadow_result = None
        self._core_shadow_failure = None
        if self.core_runtime_adapter is not None:
            self.core_runtime_adapter.cycle_completed.connect(self._on_core_shadow_completed)
            self.core_runtime_adapter.cycle_failed.connect(self._on_core_shadow_failed)
            self.core_runtime_adapter.stale_result_discarded.connect(self._on_core_shadow_stale)
        if self.core_qualification_batch_runner is not None:
            self.core_qualification_batch_runner.batch_progress.connect(self._on_qualification_batch_progress)
            self.core_qualification_batch_runner.batch_completed.connect(self._on_qualification_batch_completed)
            self.core_qualification_batch_runner.batch_failed.connect(self._on_qualification_batch_failed)
            self.core_qualification_batch_runner.batch_rejected.connect(self._on_qualification_batch_rejected)
        self._record_startup_phase("qualification_and_runtime_wiring", _startup_phase_ns)
        _startup_phase_ns = time.perf_counter_ns()
        self.quantum_optimizer = QuantumOptimizer(
            db_path=str(learning_service.db_path),
            config_path="config.json",
            validation_ratio=getattr(config, "quantum_validation_ratio", 0.30),
            min_closed=getattr(config, "quantum_min_closed", 80),
        )
        self.quantum_runtime_guard = QuantumRuntimeGuard()
        self.quantum_startup_governance = self.quantum_runtime_guard.startup_self_test()
        self.quantum_last_report = None
        self.quantum_thread: Optional[QThread] = None
        self.quantum_worker: Optional[QuantumWorker] = None
        self.quantum_fitness_history = []
        self._learning_refresh_running = False
        self._learning_refresh_pending = False
        self._learning_dispatch_context = {}
        self._learning_thread = QThread(self)
        self._learning_thread.setObjectName("dvs-learning-refresh")
        self._learning_worker = LearningRefreshWorker(
            self.learning_service,
            str(getattr(self.learning_service, "db_path", "data/dvs_paper_trades.db")),
            int(getattr(self.quantum_optimizer, "min_closed", 80) or 80),
        )
        self._learning_worker.moveToThread(self._learning_thread)
        self._learning_refresh_requested.connect(
            self._learning_worker.refresh, Qt.QueuedConnection
        )
        self._learning_worker.ready.connect(self._on_learning_refresh_ready)
        self._learning_worker.failed.connect(self._on_learning_refresh_failed)
        self._learning_worker.cancelled.connect(self._on_learning_refresh_cancelled)
        self._learning_thread.finished.connect(self._learning_worker.deleteLater)
        try:
            from dvs_ai.runtime.learning_refresh_lifecycle import record_learning_refresh_event
            self._learning_thread.started.connect(
                lambda: record_learning_refresh_event(
                    "qthread_started",
                    worker=self._learning_worker,
                    thread=self._learning_thread,
                )
            )
            self._learning_thread.finished.connect(
                lambda: record_learning_refresh_event(
                    "qthread_finished",
                    worker=self._learning_worker,
                    thread=self._learning_thread,
                )
            )
        except Exception:
            pass
        self._learning_thread.start()
        self._record_startup_phase("quantum_and_learning_worker_setup", _startup_phase_ns)
        _startup_phase_ns = time.perf_counter_ns()
        self.auto_paper_enabled = False
        self.watchlist = list(config.watchlist)
        self.results: dict[str, CoinAnalysis] = {}
        self.failed: dict[str, str] = {}
        # 4.2.5: keep one native Qt scan thread for the application lifetime.
        # Recreating a QThread every cycle causes CPython to retain one
        # _DummyThread bookkeeping wrapper whenever Python executes on that
        # foreign/native thread.  The native threads were already released,
        # but threading.enumerate() appeared to grow by one Dummy-* entry per
        # cycle.  Reusing one QThread preserves scan behavior while bounding
        # the CPython wrapper count.
        self._scan_runtime_thread = QThread(self)
        self._scan_runtime_thread.setObjectName("dvs-scan-runtime")
        self._scan_runtime_thread.start()
        self.thread: Optional[QThread] = None
        self.worker: Optional[Worker] = None
        self._scan_cycle_count = 0
        self._scan_worker_generation = 0
        self._active_scan_worker_generation: Optional[int] = None
        self._active_scan_id = ""
        self._active_scan_cycle_index = 0

        # RC7.7 — GUI-owned scan-worker lifecycle serialization.
        #
        # A Worker wrapper remains strongly referenced here until Qt emits the
        # QObject.destroyed acknowledgement. This prevents CPython/Shiboken
        # wrapper deallocation from racing the worker thread's DeferredDelete.
        self._scan_worker_retained: dict[int, Worker] = {}
        self._scan_worker_delete_scheduled: set[int] = set()
        self._scan_worker_destroyed_observed: set[int] = set()
        self._scan_worker_cleanup_started: set[int] = set()

        # RC7.8 / Defect A4 closure. V52 recorded 160 successful deleteLater
        # schedules but zero destroyed acknowledgements and retained_count=160.
        self._scan_worker_validity_probe_attempts: dict[int, int] = {}
        self._scan_worker_validity_probe_interval_ms = 25
        self._scan_worker_validity_probe_max_attempts = 200

        self._rc63_active_callback = None
        self._rc647_callback_stack = []
        self._rc647_last_completed_callback = None
        self._rc647_identity_deferred_seen = set()
        self._rc647_identity_completed_keys = set()
        # RC6.4.7B: completed identities are retained only in a bounded TTL/LRU
        # window.  The order queue is authoritative for expiry; completion is
        # always recorded before submission state is removed.
        self._rc647_identity_completed_order = deque()
        self._rc647_identity_completed_ttl_seconds = 900.0
        self._rc647_identity_completed_max_entries = 512
        self._analysis_id_by_capture_key = {}
        self._rc647_auto_paper_time_budget_ms = 8.0
        self._rc647_auto_paper_max_items_per_turn = 8
        # RC6.4.7A: explicit submission authority.  A key is not considered
        # identity-pending until the capture pipeline has actually accepted a
        # submission attempt.  This prevents the Auto Paper watchdog from
        # warning on ordinary scan results that never entered capture.
        self._rc647_capture_submitted_keys = set()
        self._rc647_collection_sequence = 0
        self._rc647_jsonl_write_lock = threading.Lock()
        self._rc647_monitor_stop = threading.Event()
        self._rc647_gc_callback = None
        self._rc647_gc_sequence = 0
        self._rc647_monitor_sequence = 0
        self._rc647_dumped_callback_instances = set()
        # RC6.4.7A-r1: GC callbacks and callback monitor are enqueue-only.
        self._rc647_gc_ring = deque(maxlen=20000)
        self._rc647_monitor_ring = deque(maxlen=5000)
        self._paper_commit_forensic_ring = deque(maxlen=5000)
        self._rc647_gc_active_generation = None
        self._rc647_telemetry_stop = threading.Event()
        self._rc647_telemetry_thread = None
        self._scan_result_reconcile_running = False
        self._scan_launch_block_last: dict[str, float] = {}
        self._rc63_scheduler_last_tick_monotonic = time.monotonic()
        self._rc63_scheduler_sequence = 0
        self._finalization_commit_count = 0
        self._burn_in_summary_interval = 10
        self._display_integrity_interval = 50
        self._scan_started_monotonic: Optional[float] = None
        self._scan_runtime_metrics = {
            "cycles_completed": 0,
            "last_duration_ms": 0.0,
            "python_threads": threading.active_count(),
            "dvs_scan_threads": (),
            "executor_drained": True,
            "worker_released": True,
            "qthread_released": True,
            "sleep_resume_events": 0,
        }
        self._last_auto_tick_monotonic = time.monotonic()
        self._sleep_resume_events = 0
        self._thread_attribution = RuntimeThreadAttributionTracker(max_retired=128)
        self._last_thread_attribution = self._thread_attribution.snapshot(0)
        self._last_executor_lifecycle = {}
        self.is_closing=False
        self.current_analysis = None
        self.selection_state = SelectionState()
        self.auto_scan_seconds = config.refresh_seconds
        self.market_universe = list(config.watchlist)
        # RC6.4.5 Async Universe Loader. The persistent worker thread owns all
        # blocking provider calls; MainThread only handles signals and rendering.
        self._universe_load_registry: dict[str, dict] = {}
        self._active_universe_load_id: Optional[str] = None
        self._universe_load_pending_scan = False
        self._universe_thread = QThread(self)
        self._universe_thread.setObjectName("dvs-universe-loader")
        self._universe_worker = UniverseLoadWorker(self.service)
        self._universe_worker.moveToThread(self._universe_thread)
        self._universe_load_requested.connect(
            self._universe_worker.load, Qt.QueuedConnection
        )
        self._universe_worker.progress.connect(self._on_universe_load_progress)
        self._universe_worker.completed.connect(self._on_universe_load_completed)
        self._universe_worker.failed.connect(self._on_universe_load_failed)
        self._universe_thread.finished.connect(self._universe_worker.deleteLater)
        self._universe_thread.start()

        # RC7.4: outcome evaluation performs provider fetches and rate-limit
        # waits. It must never execute on MainThread.
        self._outcome_update_running = False
        self._outcome_thread = QThread(self)
        self._outcome_thread.setObjectName("dvs-outcome-evaluator")
        self._outcome_worker = OutcomeUpdateWorker(self.outcome_tracker)
        self._outcome_worker.moveToThread(self._outcome_thread)
        self._outcome_update_requested.connect(
            self._outcome_worker.run,
            Qt.ConnectionType.QueuedConnection,
        )
        self._outcome_worker.completed.connect(
            self._on_outcome_update_completed,
            Qt.ConnectionType.QueuedConnection,
        )
        self._outcome_worker.failed.connect(
            self._on_outcome_update_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        self._outcome_thread.finished.connect(
            self._outcome_worker.deleteLater
        )
        self._outcome_thread.start()
        # RC6.4.5b: persistent health-check worker; network never runs on MainThread.
        self._active_api_health_check_id: Optional[str] = None
        self._api_health_thread = QThread(self)
        self._api_health_thread.setObjectName("dvs-api-health-check")
        self._api_health_worker = ApiHealthCheckWorker(self.service.provider)
        self._api_health_worker.moveToThread(self._api_health_thread)
        self._api_health_check_requested.connect(
            self._api_health_worker.run, Qt.ConnectionType.QueuedConnection
        )
        self._api_health_worker.completed.connect(
            self._on_api_health_check_completed, Qt.ConnectionType.QueuedConnection
        )
        self._api_health_thread.finished.connect(self._api_health_worker.deleteLater)
        self._api_health_thread.start()
        self.deep_scan_batch = []
        self._scan_view_tab = 0
        self._scan_view_symbol = None
        self._scan_view_timeframe = "15m"
        self._scan_detail_scroll = 0
        self._scan_score_scroll = 0
        self._ui_geometry_initialized = False
        self._last_layout_diagnostic = {}
        self._aggregate_refresh_pending = False
        self._aggregate_refresh_running = False
        # Streaming scan results arrive one symbol at a time. Buffer table-only
        # projection work so sorting/index rebuild happen once per GUI batch,
        # not once per symbol.
        self._stream_table_pending: dict[str, CoinAnalysis] = {}
        self._gr01_stream_submit_ns: dict[str, int] = {}
        self._stream_table_flush_running = False
        # NATIVE2-G2 / RC6.4.3-UI1: keep each table commit bounded and
        # defer Truth Dashboard work until its tab is actually visible.
        self._stream_table_max_rows_per_slice = 8
        self._stream_table_slice_delay_ms = 20
        self._truth_dashboard_pending_analysis = None

        # RC6.5: result signals are ingested in O(1) time. Side effects are
        # cooperatively drained one result per event-loop turn so a burst of
        # worker signals cannot monopolize the GUI thread.
        self._scan_result_side_effect_queue: list[tuple[CoinAnalysis, object]] = []
        self._scan_result_side_effect_running = False
        self._scan_finished_waiting_for_result_drain = False
        self.finalization_thread: Optional[QThread] = None
        self.finalization_worker: Optional[FinalizationWorker] = None
        self._row_by_symbol: dict[str, int] = {}
        # Display fingerprints let finalization commit only rows whose visible
        # projection changed. Streaming results normally populate the table
        # before finalization, so rebuilding every row is unnecessary.
        self._table_fingerprint_by_symbol: dict[str, tuple] = {}
        self._table_diff_metrics = {
            "rows_inserted": 0,
            "rows_unchanged_skipped": 0,
            "cells_checked": 0,
            "cells_changed": 0,
            "items_created": 0,
            "style_changes": 0,
            "palette_base_writes_avoided": 0,
            "last_update_ms": 0.0,
        }
        self._auto_paper_queue = []
        # Stable cross-finalization identity maps. CoinAnalysis is immutable and
        # finalization may replace the Python object while preserving the same
        # scan/symbol business identity, so object id() must never be used.
        self._capture_key_by_analysis_id = {}
        self._capture_identity_by_key = {}
        self._capture_failed_keys = set()
        # RC6: identity delivery is eventually consistent. A delayed Unified
        # identity must never permanently discard an otherwise valid Auto Paper
        # opportunity. The warning threshold is observability-only; queued items
        # remain eligible until capture succeeds or emits an explicit failure.
        self._auto_paper_identity_warning_seconds = 30.0
        self._auto_paper_identity_warned_keys = set()
        self._capture_latency_started_by_key = {}
        self._finalization_restore_row = -1
        self.settings = QSettings("DVS AI", "DVS AI Alpha")
        self.plain_language_presenter = PlainLanguagePresenter()
        self.expert_mode = bool(self.settings.value("ux/expert_mode", False, type=bool))
        self._commercial_shortcuts = []
        self._session_started_at = time.monotonic()

        # RC6.4.7F-r1: corrected telemetry contract. Transient queues are
        # measured at mutation sites; container replacement is recorded at the
        # exact assignment; descriptors name the real owner rather than an
        # inferred domain graph.
        self._retention_owner_telemetry = RetentionOwnerTelemetry(
            root=self,
            runtime_session_id=self._runtime_session_id,
            output_path=Path("artifacts/runtime/retention_owner_counters.jsonl"),
        )
        self._retention_owner_telemetry.register(OwnerDescriptor(
            container_name="scan_results",
            owner_class="MainWindow",
            owner_path="MainWindow.results",
            bounded_limit=None,
            retention_policy="whole_container_replaced_per_finalization",
            resolve_owner=lambda root: root,
            resolve_container=lambda owner: owner.results,
            iter_payloads=lambda container: tuple(container.values()) if isinstance(container, dict) else (),
        ))
        self._retention_owner_telemetry.register(OwnerDescriptor(
            container_name="scan_result_side_effect_queue",
            owner_class="MainWindow",
            owner_path="MainWindow._scan_result_side_effect_queue",
            bounded_limit=None,
            retention_policy="transient_fifo_drained_per_scan",
            resolve_owner=lambda root: root,
            resolve_container=lambda owner: owner._scan_result_side_effect_queue,
            iter_payloads=lambda container: (item[0] for item in tuple(container or ()) if isinstance(item, tuple) and item),
        ))
        self._retention_owner_telemetry.register(OwnerDescriptor(
            container_name="auto_paper_queue",
            owner_class="MainWindow",
            owner_path="MainWindow._auto_paper_queue",
            bounded_limit=None,
            retention_policy="transient_fifo_drained_by_worker",
            resolve_owner=lambda root: root,
            resolve_container=lambda owner: owner._auto_paper_queue,
            iter_payloads=lambda container: (item[0] if isinstance(item, tuple) and item else item for item in tuple(container or ())),
        ))
        self._retention_owner_telemetry.register(OwnerDescriptor(
            container_name="unified_identity",
            owner_class="MainWindow",
            owner_path="MainWindow._capture_identity_by_key",
            bounded_limit=self._rc647_identity_completed_max_entries,
            retention_policy="keyed_transient_identity_map",
            resolve_owner=lambda root: root,
            resolve_container=lambda owner: owner._capture_identity_by_key,
            iter_payloads=lambda container: tuple(container.values()) if isinstance(container, dict) else (),
        ))
        self._retention_owner_telemetry.register(OwnerDescriptor(
            container_name="learning_observations",
            owner_class=type(self.learning_service).__name__,
            owner_path="MainWindow.learning_service._snapshot_cache",
            bounded_limit=None,
            retention_policy="immutable_tuple_rebuilt_on_db_snapshot_change",
            resolve_owner=lambda root: root.learning_service,
            resolve_container=lambda owner: getattr(owner, "_snapshot_cache", None),
            iter_payloads=lambda container: tuple(item for group in (container or ()) for item in (group if isinstance(group, (list, tuple)) else (group,))),
            container_type="tuple_cache",
        ))
        self._retention_owner_telemetry.register(OwnerDescriptor(
            container_name="history_cache",
            owner_class=type(self.service).__name__,
            owner_path="MainWindow.service._frame_cache",
            bounded_limit=int(getattr(self.service, "_frame_cache_max", 0) or 0) or None,
            retention_policy="bounded_frame_cache",
            resolve_owner=lambda root: root.service,
            resolve_container=lambda owner: getattr(owner, "_frame_cache", None),
            iter_payloads=lambda container: tuple(container.values()) if isinstance(container, dict) else (),
        ))
        # Direct CoinAnalysis owners found by source inspection. These names are
        # intentionally literal and do not claim a DecisionCandidate graph.
        self._retention_owner_telemetry.register(OwnerDescriptor(
            container_name="stream_table_pending",
            owner_class="MainWindow",
            owner_path="MainWindow._stream_table_pending",
            bounded_limit=None,
            retention_policy="latest_value_coalescer",
            resolve_owner=lambda root: root,
            resolve_container=lambda owner: owner._stream_table_pending,
            iter_payloads=lambda container: tuple(container.values()) if isinstance(container, dict) else (),
        ))
        self._retention_owner_telemetry.register(OwnerDescriptor(
            container_name="selected_coin_analysis",
            owner_class="MainWindow",
            owner_path="MainWindow.current_analysis",
            bounded_limit=1,
            retention_policy="single_selected_analysis_reference",
            resolve_owner=lambda root: root,
            resolve_container=lambda owner: getattr(owner, "current_analysis", None),
            iter_payloads=lambda container: () if container is None else (container,),
            container_type="single_reference",
        ))
        # LearningService emits replacement events at its exact assignment sites.
        self.learning_service._retention_replacement_callback = self._on_learning_snapshot_cache_replaced
        self._record_startup_phase("runtime_state_and_telemetry_setup", _startup_phase_ns)
        _startup_phase_ns = time.perf_counter_ns()
        self.setWindowTitle(WINDOW_TITLE)
        # Platform-managed geometry avoids DPI-scaled requests wider than screen.

        root = QWidget()
        root.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(5)
        self.setMinimumSize(960, 640)

        header_container = QVBoxLayout()
        header_container.setContentsMargins(0, 0, 0, 0)
        header_container.setSpacing(4)

        header_identity = QHBoxLayout()
        brand = QLabel(
            f"<span style='font-size:20px;font-weight:800'>{APP_NAME}</span>"
            f"<span style='font-size:12px;color:#60a5fa'> Alpha {APP_VERSION}</span>"
            f"<span style='color:#64748b'> · {APP_EDITION}</span>"
        )
        brand.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        self.live_badge = QLabel(EXECUTION_STATUS_LABEL)
        self.live_badge.setObjectName("LiveBadge")
        header_identity.addWidget(brand, 1)
        header_identity.addWidget(self.live_badge)
        header_container.addLayout(header_identity)

        header_actions = QHBoxLayout()
        header_actions.setSpacing(5)
        self.header_symbol = QComboBox()
        self.header_symbol.setEditable(True)
        self.header_symbol.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.header_symbol.setPlaceholderText("🔎 Tìm coin...")
        self.header_symbol.addItems(
            [x.replace(":USDT", "") for x in self.watchlist]
        )
        completer = self.header_symbol.completer()
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.header_symbol.setMinimumWidth(90)
        self.header_symbol.setMaximumWidth(180)
        self.header_symbol.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.header_symbol.currentTextChanged.connect(
            self.select_symbol_from_header
        )
        self.coin_count = QLabel(f"{len(self.watchlist)} coin")
        self.coin_count.setObjectName("Pill")
        self.universe_btn = QPushButton("Nạp Universe")
        self.health_btn = QPushButton("Kiểm tra API")
        self.export_btn = QPushButton("Xuất CSV")
        self.manage_btn = QPushButton("Quản lý coin")
        self.retry_btn = QPushButton("Quét lại lỗi")
        self.retry_btn.setEnabled(False)
        self.start_btn = QPushButton("Quét dữ liệu")
        self.auto_scan_btn = QPushButton("Tự quét 60s")
        self.auto_scan_btn.setCheckable(True)
        self.auto_scan_btn.setMinimumWidth(112)
        self.auto_scan_btn.setMaximumWidth(132)
        self.stop_btn = QPushButton("Dừng")
        self.mode_btn = QPushButton("Chế độ: Chuyên gia" if self.expert_mode else "Chế độ: Dễ hiểu")
        self.mode_btn.setCheckable(True)
        self.mode_btn.setChecked(self.expert_mode)
        self.mode_btn.setToolTip("Dễ hiểu: kết luận và hướng dẫn. Chuyên gia: toàn bộ chỉ số kỹ thuật.")
        self.mode_btn.clicked.connect(self._toggle_expert_mode)
        self.stop_btn.setEnabled(False)

        header_actions.addWidget(QLabel("Binance Futures ·"))
        header_actions.addWidget(self.header_symbol)
        header_actions.addWidget(self.coin_count)
        header_actions.addWidget(self.mode_btn)
        header_actions.addStretch(1)
        for widget in (
            self.universe_btn,
            self.health_btn,
            self.export_btn,
            self.manage_btn,
            self.retry_btn,
            self.start_btn,
            self.auto_scan_btn,
            self.stop_btn,
        ):
            widget.setSizePolicy(
                QSizePolicy.Policy.Preferred,
                QSizePolicy.Policy.Fixed,
            )
            header_actions.addWidget(widget)
        header_container.addLayout(header_actions)
        outer.addLayout(header_container)

        status_row = QHBoxLayout()
        self.status = QLabel("Sẵn sàng")
        self.status.setObjectName("SystemStatus")
        self.status.setMaximumHeight(22)
        self.connection_badge = QLabel("● ENGINE READY")
        self.connection_badge.setObjectName("ConnectionBadge")
        self.worker_badge = QLabel("Workers: idle")
        self.order_flow_badge = QLabel("OF: OFFLINE")
        self.provider_badge = QLabel("Provider: ONLINE")
        self.provider_badge.setObjectName("StatusPill")
        self.provider_badge.setToolTip("Trạng thái kết nối Binance và thời gian backoff toàn cục.")
        self.order_flow_badge.setObjectName("StatusPill")
        self.worker_badge.setObjectName("StatusPill")
        self.clock_label = QLabel("--:--:--")
        self.clock_label.setObjectName("StatusPill")
        self.current_coin_badge = QLabel("CURRENT: —")
        self.current_coin_badge.setObjectName("StatusPill")
        self.current_coin_badge.setToolTip("Coin đang được dùng làm ngữ cảnh chung cho mọi tab.")
        self.scan_info = QLabel("Chưa quét")
        self.scan_info.setObjectName("ScanInfo")
        self.scan_info.setMaximumHeight(22)
        self.scan_info.setAlignment(Qt.AlignmentFlag.AlignRight)
        status_row.addWidget(self.status)
        status_row.addWidget(self.connection_badge)
        status_row.addWidget(self.worker_badge)
        status_row.addWidget(self.order_flow_badge)
        status_row.addWidget(self.provider_badge)
        status_row.addStretch()
        status_row.addWidget(self.current_coin_badge)
        status_row.addWidget(self.clock_label)
        status_row.addWidget(self.scan_info)
        outer.addLayout(status_row)
        self.progress = QProgressBar(); outer.addWidget(self.progress)

        # 4.2.0-UI-r3 — UI 2.0 Sidebar + Workspace shell.
        # QTabWidget remains the stable page registry used by existing builders,
        # while its primary tab bar is replaced by a hierarchical sidebar.
        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.workspace_splitter.setObjectName("WorkspaceSplitter")
        self.workspace_splitter.setChildrenCollapsible(False)

        self.sidebar = QTreeWidget(self.workspace_splitter)
        self.sidebar.setObjectName("MainSidebar")
        self.sidebar.setHeaderHidden(True)
        self.sidebar.setRootIsDecorated(True)
        self.sidebar.setIndentation(12)
        self.sidebar.setUniformRowHeights(True)
        # 4.2.0-UI-r4 — compact navigation rail.  The previous splitter
        # default allowed the tree to consume roughly 300 px on a 1600–1700 px
        # display.  Keep it intentionally narrow so Dashboard remains the
        # dominant workspace while all labels remain readable.
        self.sidebar.setMinimumWidth(145)
        self.sidebar.setMaximumWidth(175)
        self.sidebar.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        self.tabs = QTabWidget(self.workspace_splitter)
        self.tabs.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.tabs.setMovable(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.setDocumentMode(True)
        self.workspace_splitter.addWidget(self.sidebar)
        self.workspace_splitter.addWidget(self.tabs)
        self.workspace_splitter.setStretchFactor(0, 0)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setHandleWidth(3)
        # Explicit initial sizes prevent QSplitter from assigning an oversized
        # share to the sidebar on first launch.
        getattr(self.workspace_splitter, "setSizes")([160, 1440])
        outer.addWidget(self.workspace_splitter, 1)

        # 4.2.0-UI-r2 — Compact Folder Navigation.
        # Only the two highest-priority workspaces remain as direct tabs.
        # All secondary and recently added modules are grouped by operator intent.
        # Sprint A2 V2.3: return from __init__ after constructing only a
        # lightweight usable shell. Heavy workspace folders are built one per
        # event-loop turn after MainWindow.show(), preventing the full tab tree
        # from blocking startup before Windows can process messages.
        self._record_startup_phase("shell_navigation_widgets", _startup_phase_ns)
        _startup_phase_ns = time.perf_counter_ns()
        # V2.4.2: the dashboard/detail workspaces are not part of the first-paint
        # shell.  A tiny placeholder is painted first; the two primary pages are
        # then built on separate event-loop turns.  Scan controls remain disabled
        # until the table/detail contracts exist.
        self._primary_workspace_placeholder = QWidget(self)
        _primary_layout = QVBoxLayout(self._primary_workspace_placeholder)
        _primary_layout.addStretch(1)
        _primary_label = QLabel("Đang khởi tạo Dashboard…")
        _primary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _primary_layout.addWidget(_primary_label)
        _primary_layout.addStretch(1)
        self.tabs.addTab(self._primary_workspace_placeholder, "Dashboard")
        self.start_btn.setEnabled(False)
        self.auto_scan_btn.setEnabled(False)
        self._record_startup_phase("minimal_primary_placeholder", _startup_phase_ns)
        self._deferred_ui_build_queue = deque([
            self._build_dashboard_deferred,
            self._build_detail_deferred,
            self._build_trading_folder_tab,
            self._build_market_analysis_folder_tab,
            self._build_monitoring_folder_tab,
            self._build_research_folder_tab,
            self._build_tools_folder_tab,
            self._build_static_knowledge_library_tab,
        ])
        self._deferred_ui_build_active = False
        self._deferred_ui_build_started_ns = 0
        self._critical_startup_failed = False
        self._critical_startup_error = None
        # RC7.0: heavyweight diagnostic/research child workspaces are shells
        # at startup and are constructed once, on first explicit navigation.
        self._lazy_nested_workspaces = {}
        self._lazy_nested_build_active = set()
        self._startup_shell_ready_ns = time.perf_counter_ns()
        self._append_rc63_jsonl("startup_decongestion.jsonl", {
            "schema_version": "dvs.startup_decongestion.v2",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "runtime_session_id": self._runtime_session_id,
            "event": "lightweight_shell_ready",
            "init_elapsed_ms": round((self._startup_shell_ready_ns - self._startup_init_started_ns) / 1_000_000.0, 3),
            "deferred_builder_count": len(self._deferred_ui_build_queue),
        })

        self._apply_ux_mode()
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.start_btn.clicked.connect(self.start_scan)
        self.stop_btn.clicked.connect(self.stop_scan)
        self.manage_btn.clicked.connect(self.manage_coins)
        self.universe_btn.clicked.connect(self.load_market_universe)
        self.retry_btn.clicked.connect(self.retry_failed)
        self.health_btn.clicked.connect(self.check_api)
        self.export_btn.clicked.connect(self.export_csv)
        self.auto_scan_btn.toggled.connect(self.toggle_auto_scan)
        self.auto_scan_timer = QTimer(self)
        self.auto_scan_timer.setInterval(1000)
        self.auto_scan_timer.timeout.connect(self.auto_scan_tick)

        self.aggregate_refresh_timer = QTimer(self)
        self.aggregate_refresh_timer.setSingleShot(True)
        self.aggregate_refresh_timer.setInterval(400)
        self.aggregate_refresh_timer.timeout.connect(
            self._flush_aggregate_refresh
        )

        self.stream_table_timer = QTimer(self)
        self.stream_table_timer.setSingleShot(True)
        self.stream_table_timer.setInterval(250)
        self.stream_table_timer.timeout.connect(
            self._flush_stream_table_updates
        )

        self.scan_result_side_effect_timer = QTimer(self)
        self.scan_result_side_effect_timer.setSingleShot(True)
        self.scan_result_side_effect_timer.setInterval(5)
        self.scan_result_side_effect_timer.timeout.connect(
            self._drain_scan_result_side_effects
        )

        # Sprint A2 V1: coalesce non-critical dashboard refreshes and execute
        # at most one refresh per event-loop turn. This removes the previous
        # five-refresh synchronous burst after scan finalization while keeping
        # every refresh on its existing GUI-safe code path.
        self._gui_refresh_queue = deque()
        self._gui_refresh_pending = set()
        self._gui_refresh_running = False
        self._gui_refresh_tick_index = 0
        self._gui_refresh_budget_ms = 25.0
        self.gui_refresh_dispatch_timer = QTimer(self)
        self.gui_refresh_dispatch_timer.setSingleShot(True)
        self.gui_refresh_dispatch_timer.setInterval(16)
        self.gui_refresh_dispatch_timer.timeout.connect(
            self._drain_coalesced_gui_refresh
        )

        self.commercial_clock_timer = QTimer(self)
        self.commercial_clock_timer.setInterval(1000)
        self.commercial_clock_timer.timeout.connect(self._refresh_commercial_status)
        self.commercial_clock_timer.start()
        self.provider_status_timer = QTimer(self)
        self.provider_status_timer.setInterval(1000)
        self.provider_status_timer.timeout.connect(self._refresh_provider_circuit_status)
        self.provider_status_timer.start()
        self._refresh_provider_circuit_status()
        # RC6.3 observe-only scheduler drift probe. It runs on the GUI event
        # loop and records delayed delivery together with the last known callback.
        self.rc63_scheduler_probe_timer = QTimer(self)
        self.rc63_scheduler_probe_timer.setInterval(250)
        self.rc63_scheduler_probe_timer.timeout.connect(
            self._rc63_scheduler_probe_tick
        )
        self.rc63_scheduler_probe_timer.start()

        # RC6.15 (measurement only): start the independent GUI hang
        # watchdog once. It runs on its own daemon thread so it keeps
        # working even if this GUI thread stops responding entirely.
        # state_provider is intentionally minimal for now -- limited to
        # attributes already confirmed to exist on self (the same ones
        # _rc63_scheduler_probe_tick already reads above). Additional
        # fields (worker_state, engine_state, scan_phase, provider_last_
        # outcome, etc.) should only be added once a first watchdog
        # capture identifies which live attribute names actually hold
        # that information, per the "don't instrument dozens of points
        # up front" guidance this design was built around.
        try:
            from dvs_ai.runtime.gui_hang_watchdog import install_gui_hang_watchdog

            def _rc615_gui_hang_state_provider(_window=self):
                return {
                    "active_callback": getattr(_window, "_rc63_active_callback", None),
                    "last_completed_callback": getattr(
                        _window, "_rc647_last_completed_callback", None
                    ),
                }

            install_gui_hang_watchdog(
                gui_thread_ident=threading.get_ident(),
                state_provider=_rc615_gui_hang_state_provider,
            )
        except Exception:
            pass

        # RC6.18 causal isolation: this forensic widget/table census probe
        # appeared repeatedly in GUI-hang watchdog stacks (29/206 threshold
        # crossings in the RC6.17 runtime bundle). It is not business logic.
        # Keep the implementation available for targeted audits, but default
        # it OFF in normal burn-in. Explicit opt-in:
        #   DVS_ENABLE_RC647_COLLECTION_PROBE=1
        self._rc647_collection_probe_enabled = (
            (not self._clean_runtime_mode)
            and str(os.environ.get("DVS_ENABLE_RC647_COLLECTION_PROBE", "0"))
            .strip()
            .lower()
            in {"1", "true", "yes", "on"}
        )
        self.rc647_collection_probe_timer = QTimer(self)
        self.rc647_collection_probe_timer.setInterval(20_000)
        self.rc647_collection_probe_timer.timeout.connect(
            self._rc647_collection_probe_tick
        )
        if self._rc647_collection_probe_enabled:
            self.rc647_collection_probe_timer.start()
            self._record_collection_writer_status(
                "collection_snapshot_writer_started"
            )
            QTimer.singleShot(2_000, self._rc647_collection_probe_tick)
        else:
            self._record_collection_writer_status(
                "collection_snapshot_writer_disabled_default"
            )
        if not self._clean_runtime_mode:
            self._install_rc647a_gc_instrumentation()
            self._start_rc647a_callback_monitor()
        self.outcome_infrastructure_store = OutcomeInfrastructureStore(
            getattr(self.paper_trade_service, "db_path", "data/dvs_paper_trades.db")
        )
        self.outcome_resolution_coordinator = OutcomeResolutionCoordinator(
            self.outcome_tracker,
            self.paper_trade_service,
            self.outcome_infrastructure_store,
            parent=self,
        )
        self.outcome_resolution_coordinator.cycle_completed.connect(
            self._on_outcome_resolution_completed
        )
        self.outcome_resolution_coordinator.cycle_failed.connect(
            self._on_outcome_resolution_failed
        )
        self.outcome_resolution_timer = QTimer(self)
        self.outcome_resolution_timer.setInterval(60_000)
        self.outcome_resolution_timer.timeout.connect(
            self.outcome_resolution_coordinator.request_resolution
        )
        self.outcome_resolution_timer.start()
        QTimer.singleShot(0, self.outcome_resolution_coordinator.request_resolution)
        self._install_commercial_shortcuts()

        self.setStyleSheet("""
            QMainWindow,QWidget{background:#080f1d;color:#e5e7eb;font-family:Segoe UI;font-size:11px}
            QFrame#MetricCard{background:#111a2b;border:1px solid #22304a;border-radius:10px}
            QLabel#MetricTitle{color:#94a3b8;font-size:10px}
            QLabel#MetricValue{color:#f8fafc;font-size:17px;font-weight:700}
            QLabel#MetricSubtitle{color:#64748b;font-size:9px}
            QLabel#Pill{background:#172554;color:#bfdbfe;border:1px solid #1d4ed8;padding:4px 8px;border-radius:10px}
            QLabel#LiveBadge{background:#052e1b;color:#4ade80;border:1px solid #14532d;padding:4px 9px;border-radius:7px;font-weight:700}
            QLabel#SystemStatus{color:#cbd5e1;font-weight:600;padding:2px 6px}
            QLabel#ConnectionBadge{background:#052e1b;color:#4ade80;border:1px solid #166534;padding:3px 8px;border-radius:8px;font-size:9px;font-weight:800}
            QLabel#StatusPill{background:#111827;color:#94a3b8;border:1px solid #334155;padding:3px 7px;border-radius:8px;font-size:9px}
            QLabel#ScanInfo{color:#94a3b8;padding:2px 4px}
            QFrame#MiniScoreCard{
                background:#0b1424;
                border:1px solid #263753;
                border-radius:10px;
            }
            QFrame#MiniScoreCard[scoreBand="muted"]{border-color:#334155}
            QFrame#MiniScoreCard[scoreBand="watch"]{border-color:#a16207}
            QFrame#MiniScoreCard[scoreBand="info"]{border-color:#0369a1}
            QFrame#MiniScoreCard[scoreBand="positive"]{border-color:#15803d}
            QFrame#MiniScoreCard[scoreBand="premium"]{border-color:#7e22ce}
            QLabel#MiniScoreTitle{
                color:#94a3b8;
                font-size:9px;
                font-weight:800;
                letter-spacing:0.4px;
            }
            QLabel#MiniScoreValue{font-size:22px;font-weight:800}
            QWidget#DetailStructureStrip{
                background:#09111f;
                border:1px solid #1f2d44;
                border-radius:10px;
            }
            QWidget#DetailDecisionRail{
                background:#080f1d;
                border:1px solid #1f2d44;
                border-radius:12px;
            }
            QWidget#EngineGaugeGrid{
                background:#0a1322;
                border:1px solid #263753;
                border-radius:12px;
                padding:6px;
            }
            GaugeWidget#PrimaryConfidenceGauge{
                background:#0b1628;
                border:1px solid #334a6b;
                border-radius:12px;
            }
            QFrame#TradePlanCard{
                background:#0b1728;
                border:1px solid #245b43;
                border-radius:12px;
            }
            GaugeWidget{
                background:#0d1728;
                border:1px solid #27364f;
                border-radius:10px;
            }
            GaugeWidget[scoreBand="muted"]{border-color:#334155}
            GaugeWidget[scoreBand="watch"]{border-color:#a16207}
            GaugeWidget[scoreBand="warning"]{border-color:#c2410c}
            GaugeWidget[scoreBand="critical"]{border-color:#dc2626}
            GaugeWidget[scoreBand="info"]{border-color:#0284c7}
            GaugeWidget[scoreBand="positive"]{border-color:#16a34a}
            GaugeWidget[scoreBand="premium"]{border-color:#9333ea}
            QTableWidget#OperatorMarketTable{
                background:#09111f;
                alternate-background-color:#0c1728;
                border:1px solid #1f2d44;
                border-radius:8px;
                selection-background-color:#123b63;
                selection-color:#ffffff;
                padding:2px;
            }
            QTableWidget#OperatorMarketTable::item{
                border-bottom:1px solid #17243a;
                padding:5px 5px;
                font-size:11px;
            }
            QTableWidget#OperatorMarketTable::item:selected{
                border-top:1px solid #38bdf8;
                border-bottom:1px solid #38bdf8;
            }
            QTableWidget#OperatorMarketTable QHeaderView::section{
                background:#17243a;
                color:#cbd5e1;
                border:0;
                border-right:1px solid #263753;
                border-bottom:1px solid #334155;
                padding:6px 2px;
                font-size:8px;
                font-weight:800;
            }
            QLabel#RegimeBadge{background:#24164b;color:#c4b5fd;border:1px solid #6d28d9;padding:5px 9px;border-radius:6px;font-weight:700}
            QFrame#DecisionBox{background:#0b1424;border:1px solid #263753;border-radius:8px}
            QLabel#RRBadge{background:#0f3b2b;color:#86efac;border:1px solid #16a34a;padding:8px;border-radius:20px;font-size:16px;font-weight:700}
            QLabel#AIVoice{background:#111c35;color:#dbeafe;border:1px solid #31558a;padding:10px;border-radius:8px;font-size:12px}
            QLabel#FinalResultTitle{
                background:#111827;
                color:#e2e8f0;
                border:1px solid #334155;
                padding:10px;
                border-radius:8px;
                font-size:17px;
                font-weight:800;
            }
            QLabel#FinalResultTitle[decisionState="long"]{
                background:#052e1b;
                color:#86efac;
                border:1px solid #22c55e;
            }
            QLabel#FinalResultTitle[decisionState="short"]{
                background:#450a0a;
                color:#fca5a5;
                border:1px solid #ef4444;
            }
            QLabel#FinalResultTitle[decisionState="neutral"]{
                background:#1e293b;
                color:#cbd5e1;
                border:1px solid #64748b;
            }
            QPushButton#TestLongButton{
                background:#14532d;
                border:1px solid #22c55e;
                color:#dcfce7;
                font-weight:800;
            }
            QPushButton#TestShortButton{
                background:#450a0a;
                border:1px solid #ef4444;
                color:#fee2e2;
                font-weight:800;
            }
            QLabel#PaperSummary{
                background:#0b1424;
                border:1px solid #31558a;
                color:#dbeafe;
                padding:8px 12px;
                border-radius:7px;
                font-size:13px;
                font-weight:700;
            }
            QTableWidget,QTextEdit,QListWidget,QLineEdit{
                background:#0f172a;
                color:#e5e7eb;
                border:1px solid #22304a;
                border-radius:6px;
                gridline-color:#1e293b;
                selection-background-color:#1e3a5f;
                selection-color:#ffffff;
                alternate-background-color:#111c2e;
            }
            QTableWidget::item{
                padding:3px;
                border-bottom:1px solid #162238;
            }
            QTableWidget::item:selected{
                background:#1e3a5f;
                color:#ffffff;
                border:1px solid #38bdf8;
            }
            QTableWidget::item:hover{
                background:#172554;
                color:#ffffff;
            }
            QHeaderView::section{background:#182338;color:#cbd5e1;padding:5px;border:0;border-right:1px solid #24324a;font-weight:600}
            QPushButton{background:#1d4ed8;color:white;padding:5px 10px;border-radius:6px;font-weight:600}
            QPushButton:hover{background:#2563eb}
            QPushButton:checked{
                background:#14532d;
                border:1px solid #22c55e;
                color:#dcfce7;
            }
            QPushButton:disabled{background:#334155;color:#94a3b8}
            QTabWidget::pane{border:1px solid #1e293b;border-radius:8px;top:-1px}
            QTabBar::tab{background:#111827;color:#94a3b8;padding:8px 13px;margin-right:2px;border-top-left-radius:6px;border-top-right-radius:6px}
            QTabBar::tab:hover{background:#172554;color:#dbeafe}
            QTabBar::tab:selected{background:#1d4ed8;color:white}
            QTreeWidget#MainSidebar{
                background:#0b1424;
                color:#cbd5e1;
                border:1px solid #22304a;
                border-radius:8px;
                padding:6px;
                outline:0;
            }
            QTreeWidget#MainSidebar::item{
                min-height:30px;
                padding:3px 6px;
                border-radius:5px;
            }
            QTreeWidget#MainSidebar::item:hover{background:#172554;color:#ffffff}
            QTreeWidget#MainSidebar::item:selected{background:#1d4ed8;color:#ffffff;font-weight:700}
            QSplitter#WorkspaceSplitter::handle{background:#172033;width:2px}

            QFrame#TruthCard{background:#0f172a;border:1px solid #25334a;border-radius:8px;}
            QFrame#TruthCard[state="good"]{border-color:#16a34a;}
            QFrame#TruthCard[state="warning"]{border-color:#f59e0b;}
            QFrame#TruthCard[state="critical"]{border-color:#ef4444;}
            QLabel#TruthCardTitle{color:#94a3b8;font-size:10px;font-weight:700;}
            QLabel#TruthCardValue{color:#f8fafc;font-size:18px;font-weight:800;}
            QLabel#TruthCardDetail{color:#cbd5e1;font-size:10px;}
            QLabel#TruthDashboardTitle{color:#38bdf8;font-size:18px;font-weight:800;}
            QLabel#TruthDashboardSymbol{color:#dbeafe;font-weight:700;}
            QLabel#TruthDashboardNotice{color:#94a3b8;font-style:italic;}
            QLabel#TruthTimeline{
                background:#0b1424;
                color:#cbd5e1;
                border:1px solid #263753;
                border-radius:7px;
                padding:9px;
            }
            QScrollArea#TruthDashboardScroll{background:#080f1d;border:0;}
            QWidget#TruthDashboardContent{background:#080f1d;}
            QGroupBox{
                border:1px solid #24324a;
                border-radius:9px;
                margin-top:9px;
                padding-top:6px;
                font-weight:700;
                color:#cbd5e1;
            }
            QGroupBox::title{
                subcontrol-origin:margin;
                left:10px;
                padding:0 6px;
                color:#cbd5e1;
            }
            QFrame#PerformanceOverlay{
                background:rgba(2,6,23,232);
                border:1px solid #334155;
                border-radius:8px;
            }
            QFrame#PerformanceOverlay[health="warning"]{border:1px solid #f59e0b;}
            QFrame#PerformanceOverlay[health="critical"]{border:1px solid #ef4444;}
            QLabel#PerformanceOverlayTitle{color:#38bdf8;font-weight:800;font-size:11px;}
            QLabel#PerformanceOverlayBody{color:#dbeafe;font-family:Consolas,monospace;font-size:10px;}
            QToolTip{background:#0f172a;color:#f8fafc;border:1px solid #38bdf8;padding:5px}
            QScrollBar:vertical{background:#0b1220;width:10px;margin:0}
            QScrollBar::handle:vertical{background:#334155;min-height:24px;border-radius:5px}
            QScrollBar::handle:vertical:hover{background:#475569}
            QProgressBar{background:#111827;border:1px solid #22304a;border-radius:6px;text-align:center;height:12px}
            QProgressBar::chunk{background:#16a34a;border-radius:5px}
        """)
        self.ui_geometry = UIGeometryManager(self)
        self.ui_profiler = UIPerformanceProfiler(self)
        self.ui_profiler.start()
        self.performance_overlay = PerformanceOverlay(
            self.centralWidget(),
            profiler_provider=lambda: self.ui_profiler.build_report(),
            scheduler_provider=self.paint_scheduler_diagnostics,
            table_provider=self.table_diff_diagnostics,
            worker_provider=self._performance_worker_state,
        )
        self._restore_commercial_session()
        overlay_visible = self.settings.value("commercial/performance_overlay", False, bool)
        if self._clean_runtime_mode:
            self.performance_overlay.close_overlay()
            self.performance_overlay.set_overlay_visible(False)
        else:
            self.performance_overlay.set_overlay_visible(overlay_visible)
        self._refresh_commercial_status()
        QTimer.singleShot(0, self.ui_geometry.initialize_once)

    @_audit_gui_callback("order_flow_status_refresh")
    def _refresh_order_flow_status(self):
        runtime = self.order_flow_runtime
        if runtime is None:
            self.order_flow_badge.setText("OF: DISABLED")
            self.order_flow_badge.setToolTip("Order-flow runtime không được cấu hình.")
            return
        try:
            diag = dict(runtime.diagnostics() or {})
        except Exception as exc:
            diag = {"state": "ERROR", "running": False, "last_error": str(exc)}
        state = str(diag.get("state", "UNKNOWN")).upper()
        age = diag.get("last_message_age_seconds")
        unresolved = int(diag.get("gaps_unresolved", 0) or 0)
        liq_warn = int(diag.get("liquidation_gap_warnings", 0) or 0)
        suffix = "" if age is None else f" {float(age):.0f}s"
        self.order_flow_badge.setText(f"OF: {state}{suffix}")
        self.order_flow_badge.setToolTip(
            "Order Flow Runtime\n"
            f"State: {state}\n"
            f"Running: {bool(diag.get('running', False))}\n"
            f"Messages: {int(diag.get('messages', 0) or 0)}\n"
            f"Unresolved gaps: {unresolved}\n"
            f"Liquidation warnings: {liq_warn}\n"
            f"Last error: {diag.get('last_error', '') or '-'}"
        )

    def _install_commercial_shortcuts(self):
        shortcuts = (
            ("Ctrl+R", self.start_scan),
            ("Ctrl+Shift+R", self.retry_failed),
            ("Ctrl+E", self.export_csv),
            ("Ctrl+L", lambda: self.header_symbol.setFocus()),
            ("Escape", self.stop_scan),
            ("Ctrl+Shift+P", self.toggle_performance_overlay),
        )
        for sequence, callback in shortcuts:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
            self._commercial_shortcuts.append(shortcut)
        self.start_btn.setToolTip("Quét dữ liệu (Ctrl+R)")
        self.retry_btn.setToolTip("Quét lại lỗi (Ctrl+Shift+R)")
        self.export_btn.setToolTip("Xuất CSV (Ctrl+E)")
        self.header_symbol.setToolTip("Tìm symbol (Ctrl+L)")
        self.stop_btn.setToolTip("Dừng tác vụ (Esc)")


    def _record_scan_liveness(self, event: str, **details) -> None:
        # RC7.7-r1 forensic validation hardening:
        #
        # Clean runtime still suppresses high-volume scan forensic chatter, but
        # the ownership-serialization proof markers are low-volume and are
        # required to validate the exact RC7.7 causal mechanism. This changes
        # observability only; worker ownership/deletion logic is untouched.
        clean_runtime_lifecycle_allowlist = {
            "worker_ownership_registered",
            "worker_cleanup_deferred",
            "worker_signals_disconnected",
            "worker_delete_later_scheduled",
            "worker_destroyed_observed",
            "duplicate_cleanup_blocked",
            "duplicate_delete_blocked",
            "duplicate_destroyed_ack_blocked",
            "worker_delete_later_failed_retained",
        }
        if (
            bool(getattr(self, "_clean_runtime_mode", False))
            and str(event) not in clean_runtime_lifecycle_allowlist
        ):
            return
        current_worker = getattr(self, "worker", None)
        payload = {
            "schema_version": "dvs.runtime.scan_dispatch_liveness.v1",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "monotonic_ns": time.monotonic_ns(),
            "runtime_session_id": self._runtime_session_id,
            "pid": os.getpid(),
            "event": str(event),
            "scan_id": str(getattr(self, "current_scan_id", "")),
            "cycle_index": int(getattr(self, "_scan_cycle_count", 0)),
            "worker_object_id": details.pop("worker_object_id", None),
            "current_worker_object_id": (
                hex(id(current_worker)) if current_worker is not None else None
            ),
            "thread_object_id": (
                hex(id(getattr(self, "thread", None)))
                if getattr(self, "thread", None) is not None else None
            ),
            "qt_thread_name": QThread.currentThread().objectName(),
            "python_thread_id": threading.get_ident(),
            **details,
        }
        self._append_rc63_jsonl("scan_dispatch_liveness.jsonl", payload)

    def _record_scan_launch_decision(
        self, reason: str, *, rate_limit_seconds: float = 0.0, **details
    ) -> None:
        now = time.monotonic()
        if rate_limit_seconds > 0.0:
            last = self._scan_launch_block_last.get(reason, 0.0)
            if now - last < rate_limit_seconds:
                return
            self._scan_launch_block_last[reason] = now
        self._record_scan_liveness(reason, **details)

    def _append_rc63_jsonl(self, filename: str, payload: dict) -> None:
        # RC7.7-r2 — ownership evidence closure.
        #
        # RC7.7-r1 allowlisted ownership events in _record_scan_liveness(),
        # but this lower writer layer still returned for *every* clean-runtime
        # JSONL record. Allow only the low-volume lifecycle proof/anomaly events
        # for scan_dispatch_liveness.jsonl. All other clean-runtime forensic
        # writes remain suppressed exactly as before.
        if bool(getattr(self, "_clean_runtime_mode", False)):
            ownership_events = {
                "worker_ownership_registered",
                "worker_cleanup_deferred",
                "worker_signals_disconnected",
                "worker_delete_later_scheduled",
                "worker_destroyed_observed",
                "duplicate_cleanup_blocked",
                "duplicate_delete_blocked",
                "duplicate_destroyed_ack_blocked",
                "worker_delete_later_failed_retained",
                "worker_validity_probe_started",
                "worker_validity_probe_invalid",
                "worker_validity_probe_timeout_retained",
                "worker_validity_probe_unavailable",
                "worker_ownership_released",
            }
            is_ownership_evidence = (
                str(filename) == "scan_dispatch_liveness.jsonl"
                and str(payload.get("event", "")) in ownership_events
            )
            p89_observability_events = {
                "p89_scan_error_callback_observed",
                "p89_history_lifecycle_consumed",
            }
            is_p89_observability_evidence = (
                str(filename) == "p89_gui_negative_control_forensics.jsonl"
                and str(payload.get("event", "")) in p89_observability_events
            )
            if not (
                is_ownership_evidence
                or is_p89_observability_evidence
            ):
                return
        # RC6.16 (causal fix for GUI-thread disk I/O stalls): RC6.15's
        # independent watchdog directly caught the GUI thread's Python
        # stack sitting inside this method's synchronous open/write/flush
        # in ~13% of observed stall events. Enqueue instead of writing
        # inline -- a dedicated background thread performs the actual
        # disk I/O, so this call can never block the caller on disk
        # latency (antivirus scanning, filesystem contention, etc.).
        # On-disk output format is unchanged: same path, same append
        # mode, same JSON encoding, same newline-per-record. The old
        # per-call _rc647_jsonl_write_lock is no longer needed since the
        # single background writer thread already serializes all writes
        # to every file by itself.
        try:
            from dvs_ai.runtime.async_jsonl_writer import enqueue_jsonl_write
            path = Path("artifacts/runtime") / filename
            enqueue_jsonl_write(path, payload)
        except Exception:
            logger.exception("RC6_3_EVIDENCE_WRITE_FAILED file=%s", filename)

    def _record_collection_writer_status(self, event: str, **details) -> None:
        self._append_rc63_jsonl(
            "collection_snapshots.jsonl",
            {
                "schema_version": "dvs.runtime.collection_snapshot.v2",
                "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
                "runtime_session_id": self._runtime_session_id,
                "pid": os.getpid(),
                "event": str(event),
                "path": str(Path("artifacts/runtime/collection_snapshots.jsonl")),
                "interval_seconds": 20.0,
                **details,
            },
        )

    def _install_rc647a_gc_instrumentation(self) -> None:
        """Install allocation-safe GC observation.

        The callback never formats JSON, touches Qt, logs, or writes files.
        It only appends a fixed tuple to a bounded in-memory deque.
        """
        if self._rc647_gc_callback is not None:
            return

        def gc_observer(phase, info):
            try:
                generation = int(info.get("generation", -1))
                self._rc647_gc_active_generation = generation if phase == "start" else None
                self._rc647_gc_ring.append((
                    1 if phase == "start" else 0,
                    generation,
                    time.monotonic_ns(),
                    int(sys.getallocatedblocks()),
                    int(info.get("collected", 0) or 0),
                    int(info.get("uncollectable", 0) or 0),
                ))
            except Exception:
                # Never recurse into logging or telemetry from a GC callback.
                pass

        self._rc647_gc_callback = gc_observer
        gc.callbacks.append(gc_observer)
        self._start_rc647a_telemetry_writer()
        self._append_rc63_jsonl("gc_events.jsonl", {
            "schema_version": "dvs.runtime.gc_event.v2",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "runtime_session_id": self._runtime_session_id,
            "pid": os.getpid(),
            "event": "gc_callback_installed_enqueue_only",
            "thresholds": list(gc.get_threshold()),
            "ring_capacity": 20000,
        })

    def _start_rc647a_telemetry_writer(self) -> None:
        if self._rc647_telemetry_thread is not None:
            return

        def writer_loop():
            starts = {0: [], 1: [], 2: []}
            while not self._rc647_telemetry_stop.wait(1.0):
                gc_items = []
                monitor_items = []
                paper_commit_items = []
                while self._rc647_gc_ring:
                    gc_items.append(self._rc647_gc_ring.popleft())
                while self._rc647_monitor_ring:
                    monitor_items.append(self._rc647_monitor_ring.popleft())
                while self._paper_commit_forensic_ring:
                    paper_commit_items.append(self._paper_commit_forensic_ring.popleft())

                summary = {g: {"count": 0, "total_pause_ms": 0.0, "max_pause_ms": 0.0,
                               "collected": 0, "uncollectable": 0} for g in (0,1,2)}
                slow = []
                for is_start, generation, mono_ns, blocks, collected, uncollectable in gc_items:
                    if generation not in starts:
                        continue
                    if is_start:
                        starts[generation].append((mono_ns, blocks))
                    elif starts[generation]:
                        start_ns, start_blocks = starts[generation].pop()
                        pause_ms = max(0.0, (mono_ns-start_ns)/1_000_000.0)
                        s=summary[generation]
                        s["count"] += 1; s["total_pause_ms"] += pause_ms
                        s["max_pause_ms"] = max(s["max_pause_ms"], pause_ms)
                        s["collected"] += collected; s["uncollectable"] += uncollectable
                        if generation == 2 or pause_ms >= 100.0:
                            slow.append({"generation": generation, "pause_ms": round(pause_ms,3),
                                         "allocated_blocks_delta": blocks-start_blocks,
                                         "collected": collected, "uncollectable": uncollectable})
                if gc_items:
                    self._append_rc63_jsonl("gc_events.jsonl", {
                        "schema_version":"dvs.runtime.gc_aggregate.v2",
                        "timestamp_utc":datetime.utcnow().isoformat(timespec="milliseconds")+"Z",
                        "runtime_session_id":self._runtime_session_id,"pid":os.getpid(),
                        "event":"gc_aggregate_1s","events_drained":len(gc_items),
                        "ring_remaining":len(self._rc647_gc_ring),"by_generation":summary,
                        "slow_or_gen2":slow,"allocated_blocks":int(sys.getallocatedblocks()),
                    })
                for sample in monitor_items:
                    self._append_rc63_jsonl("active_callback_samples.jsonl", sample)
                for record in paper_commit_items:
                    io_started_ns = time.perf_counter_ns()
                    self._append_rc63_jsonl("paper_commit_forensics.jsonl", record)
                    writer_io_ms = (time.perf_counter_ns() - io_started_ns) / 1_000_000.0
                    if writer_io_ms > 25.0:
                        self._append_rc63_jsonl("paper_commit_forensics.jsonl", {
                            "schema_version":"dvs.runtime.paper_commit_forensics.v1",
                            "timestamp_utc":datetime.utcnow().isoformat(timespec="milliseconds")+"Z",
                            "runtime_session_id":self._runtime_session_id,"pid":os.getpid(),
                            "event":"paper_commit_writer_io_slow",
                            "generation":record.get("generation"),
                            "chunk_index":record.get("chunk_index"),
                            "writer_io_ms":round(writer_io_ms,3),
                            "thread_name":threading.current_thread().name,
                        })

        self._rc647_telemetry_thread = threading.Thread(target=writer_loop,
            name="dvs-rc647a-telemetry-writer", daemon=True)
        self._rc647_telemetry_thread.start()

    def _dump_python_threads_for_hang(self, active: dict, elapsed_ms: float) -> None:
        """Dump all Python stacks once per callback instance after 5 seconds.

        Runs only in the monitor thread and never invokes Qt.  Failure is
        fail-open and cannot block the GUI pipeline.
        """
        callback_id = str(active.get("callback_instance_id") or "unknown")
        if callback_id in self._rc647_dumped_callback_instances:
            return
        self._rc647_dumped_callback_instances.add(callback_id)
        path = Path("artifacts/runtime/freeze_thread_dumps.log")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(
                    "\n=== DVS RC6.4.7G-r1 CALLBACK HANG DUMP "
                    + datetime.utcnow().isoformat(timespec="milliseconds") + "Z "
                    + f"callback_instance_id={callback_id} section={active.get('section')} "
                    + f"elapsed_ms={elapsed_ms:.3f} ===\n"
                )
                handle.flush()
                faulthandler.dump_traceback(file=handle, all_threads=True)
                handle.write("=== END DUMP ===\n")
                handle.flush()
            self._rc647_monitor_ring.append({
                "schema_version":"dvs.runtime.freeze_thread_dump.v1",
                "timestamp_utc":datetime.utcnow().isoformat(timespec="milliseconds")+"Z",
                "runtime_session_id":self._runtime_session_id,
                "pid":os.getpid(),
                "event":"python_thread_dump_written",
                "callback_instance_id":callback_id,
                "section":active.get("section"),
                "elapsed_so_far_ms":round(float(elapsed_ms),3),
                "path":str(path),
            })
        except Exception as exc:
            self._rc647_monitor_ring.append({
                "schema_version":"dvs.runtime.freeze_thread_dump.v1",
                "timestamp_utc":datetime.utcnow().isoformat(timespec="milliseconds")+"Z",
                "runtime_session_id":self._runtime_session_id,
                "pid":os.getpid(),
                "event":"python_thread_dump_failed",
                "callback_instance_id":callback_id,
                "error_type":type(exc).__name__,
            })

    def _start_rc647a_callback_monitor(self) -> None:
        if getattr(self, "_rc647_monitor_thread", None) is not None:
            return

        def monitor_loop():
            while not self._rc647_monitor_stop.wait(0.25):
                active = getattr(self, "_rc63_active_callback", None)
                if not isinstance(active, dict):
                    continue
                now_ns = time.monotonic_ns()
                entered_ns = int(active.get("entered_monotonic_ns", now_ns) or now_ns)
                elapsed_ms = max(0.0, (now_ns-entered_ns)/1_000_000.0)
                if elapsed_ms < 100.0:
                    continue
                if elapsed_ms >= 5000.0:
                    self._dump_python_threads_for_hang(active, elapsed_ms)
                self._rc647_monitor_sequence += 1
                self._rc647_monitor_ring.append({
                    "schema_version":"dvs.runtime.active_callback_sample.v2",
                    "timestamp_utc":datetime.utcnow().isoformat(timespec="milliseconds")+"Z",
                    "monotonic_ns":now_ns,"runtime_session_id":self._runtime_session_id,
                    "pid":os.getpid(),"sequence":self._rc647_monitor_sequence,
                    "sample_thread_id":threading.get_ident(),"active_callback":dict(active),
                    "elapsed_so_far_ms":round(elapsed_ms,3),
                    "allocated_blocks":int(sys.getallocatedblocks()),
                })

        self._rc647_monitor_thread = threading.Thread(target=monitor_loop,
            name="dvs-rc647a-callback-monitor", daemon=True)
        self._rc647_monitor_thread.start()
        self._append_rc63_jsonl("active_callback_samples.jsonl", {
            "schema_version":"dvs.runtime.active_callback_sample.v2",
            "timestamp_utc":datetime.utcnow().isoformat(timespec="milliseconds")+"Z",
            "runtime_session_id":self._runtime_session_id,"pid":os.getpid(),
            "event":"active_callback_monitor_started_enqueue_only",
            "interval_ms":250,"threshold_ms":100,
        })

    def _record_callback_attribution(
        self,
        section: str,
        duration_ms: float,
        **details,
    ) -> None:
        if bool(getattr(self, "_clean_runtime_mode", False)):
            return
        payload = {
            "schema_version": "dvs.runtime.callback_attribution.v1",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "runtime_session_id": self._runtime_session_id,
            "pid": os.getpid(),
            "thread_id": threading.get_ident(),
            "section": str(section),
            "duration_ms": round(float(duration_ms), 3),
            "worker_state": self._performance_worker_state(),
            "result_count": len(getattr(self, "results", {})),
            "failed_count": len(getattr(self, "failed", {})),
            **details,
        }
        self._append_rc63_jsonl("callback_attribution.jsonl", payload)

    def _rc63_scheduler_probe_tick(self) -> None:
        # RC6.15 (measurement only): cheap in-memory GUI heartbeat, read by
        # the independent gui_hang_watchdog daemon thread. Updated on every
        # tick regardless of drift, so the watchdog always has a fresh
        # "last time the GUI thread definitely ran Python code" timestamp.
        try:
            from dvs_ai.runtime.gui_hang_watchdog import record_gui_tick
            record_gui_tick("rc63_scheduler_probe_tick")
        except Exception:
            pass

        if bool(getattr(self, "_clean_runtime_mode", False)):
            return

        now = time.monotonic()
        expected_seconds = 0.250
        elapsed_seconds = now - self._rc63_scheduler_last_tick_monotonic
        self._rc63_scheduler_last_tick_monotonic = now
        self._rc63_scheduler_sequence += 1
        drift_ms = max(0.0, (elapsed_seconds - expected_seconds) * 1000.0)

        # Record only material drift to keep burn-in evidence bounded.
        if drift_ms < 100.0:
            return

        active = getattr(self, "_rc63_active_callback", None)
        last_completed = getattr(self, "_rc647_last_completed_callback", None)
        correlation_gap_ms = None
        scheduler_now_ns = time.monotonic_ns()
        if isinstance(last_completed, dict):
            ended_ns = int(last_completed.get("ended_monotonic_ns", 0) or 0)
            if ended_ns > 0:
                correlation_gap_ms = round(
                    max(0.0, (scheduler_now_ns - ended_ns) / 1_000_000.0),
                    3,
                )

        # Copy once so all fields describe one coherent paint snapshot.
        paint_activity = dict(_LAST_PAINT_ACTIVITY)
        paint_started_ns = int(paint_activity.get("started_ns") or 0)
        paint_ended_ns = int(paint_activity.get("ended_ns") or 0)
        time_since_paint_start_ms = (
            round(max(0.0, (scheduler_now_ns - paint_started_ns) / 1_000_000.0), 3)
            if paint_started_ns > 0
            else None
        )
        time_since_paint_end_ms = (
            round(max(0.0, (scheduler_now_ns - paint_ended_ns) / 1_000_000.0), 3)
            if paint_ended_ns > 0
            else None
        )
        payload = {
            "schema_version": "dvs.runtime.scheduler_drift.v1",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "runtime_session_id": self._runtime_session_id,
            "pid": os.getpid(),
            "thread_id": threading.get_ident(),
            "sequence": self._rc63_scheduler_sequence,
            "expected_interval_ms": 250.0,
            "elapsed_ms": round(elapsed_seconds * 1000.0, 3),
            "drift_ms": round(drift_ms, 3),
            "active_callback": dict(active) if isinstance(active, dict) else None,
            "last_completed_callback": (
                dict(last_completed) if isinstance(last_completed, dict) else None
            ),
            "last_completed_callback_gap_ms": correlation_gap_ms,
            "last_paint_sequence": int(paint_activity.get("sequence") or 0),
            "last_paint_class": paint_activity.get("paint_class"),
            "last_paint_instance": paint_activity.get("paint_instance"),
            "last_paint_operation": paint_activity.get("operation"),
            "last_paint_started_monotonic_ns": (
                paint_started_ns if paint_started_ns > 0 else None
            ),
            "last_paint_ended_monotonic_ns": (
                paint_ended_ns if paint_ended_ns > 0 else None
            ),
            "last_paint_duration_ms": paint_activity.get("duration_ms"),
            "time_since_last_paint_start_ms": time_since_paint_start_ms,
            "time_since_last_paint_end_ms": time_since_paint_end_ms,
            "paint_in_progress": bool(paint_activity.get("in_progress", False)),
            "worker_state": self._performance_worker_state(),
            "current_tab": int(self.tabs.currentIndex()) if hasattr(self, "tabs") else None,
            "result_count": len(getattr(self, "results", {})),
            "failed_count": len(getattr(self, "failed", {})),
        }
        self._append_rc63_jsonl("scheduler_drift.jsonl", payload)

    def _record_identity_diagnostic(self, event: str, capture_key=None, **details) -> None:
        if bool(getattr(self, "_clean_runtime_mode", False)):
            return
        key_scan_id = ""
        key_symbol = ""
        if isinstance(capture_key, (tuple, list)) and len(capture_key) >= 2:
            key_scan_id = str(capture_key[0])
            key_symbol = str(capture_key[1])
        payload = {
            "schema_version": "dvs.runtime.identity_diagnostic.v1",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "runtime_session_id": self._runtime_session_id,
            "pid": os.getpid(),
            "event": str(event),
            "scan_id": key_scan_id or str(getattr(self, "current_scan_id", "")),
            "cycle_index": int(getattr(self, "_scan_cycle_count", 0) or 0),
            "symbol": key_symbol,
            "identity_key": list(capture_key) if isinstance(capture_key, tuple) else capture_key,
            "pending_map_contains_key": capture_key in getattr(self, "_capture_latency_started_by_key", {}),
            "identity_map_contains_key": capture_key in getattr(self, "_capture_identity_by_key", {}),
            "failed_set_contains_key": capture_key in getattr(self, "_capture_failed_keys", set()),
            "warned_set_contains_key": capture_key in getattr(self, "_auto_paper_identity_warned_keys", set()),
            "pending_map_size": len(getattr(self, "_capture_latency_started_by_key", {})),
            "identity_map_size": len(getattr(self, "_capture_identity_by_key", {})),
            "auto_paper_queue_size": len(getattr(self, "_auto_paper_queue", [])),
            "auto_paper_worker_object_id": getattr(self, "_auto_paper_worker_object_id", None),
            "auto_paper_payload_pending_count": len(getattr(self, "_auto_paper_payload_pending", {})),
            "auto_paper_payload_dispatched_total": int(getattr(self, "_auto_paper_payload_dispatched_total", 0)),
            "auto_paper_payload_released_total": int(getattr(self, "_auto_paper_payload_released_total", 0)),
            "capture_service_pending_count": getattr(
                getattr(self, "live_episode_capture", None), "pending_count", None
            ),
            **details,
        }
        self._append_rc63_jsonl("identity_diagnostics.jsonl", payload)

    def _rc647_collection_probe_tick(self) -> None:
        if not bool(getattr(self, "_rc647_collection_probe_enabled", False)):
            return
        if getattr(self, "is_closing", False):
            return
        self._rc647_collection_sequence += 1
        table_rows = {}
        table_items = 0
        try:
            for table in self.findChildren(QTableWidget):
                object_name = table.objectName() or ""
                name = object_name or f"QTableWidget@{hex(id(table))}"
                rows = int(table.rowCount())
                cols = int(table.columnCount())
                parent = table.parentWidget()
                parent_name = ""
                parent_class = ""
                if parent is not None:
                    parent_name = parent.objectName() or ""
                    parent_class = type(parent).__name__
                headers = []
                for column in range(min(cols, 12)):
                    header = table.horizontalHeaderItem(column)
                    headers.append("" if header is None else header.text())
                table_rows[name] = {
                    "object_id": hex(id(table)),
                    "object_name": object_name,
                    "parent_object_name": parent_name,
                    "parent_class": parent_class,
                    "rows": rows,
                    "columns": cols,
                    "visible": bool(table.isVisible()),
                    "headers": headers,
                    "estimated_cell_capacity": rows * cols,
                }
                table_items += rows * cols
        except Exception:
            logger.exception("RC6_4_7_TABLE_COLLECTION_PROBE_FAILED")
        payload = {
            "schema_version": "dvs.runtime.collection_snapshot.v1",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "runtime_session_id": self._runtime_session_id,
            "pid": os.getpid(),
            "sequence": self._rc647_collection_sequence,
            "scan_id": str(getattr(self, "current_scan_id", "")),
            "cycle_index": int(getattr(self, "_scan_cycle_count", 0) or 0),
            "results_size": len(getattr(self, "results", {})),
            "failed_size": len(getattr(self, "failed", {})),
            "stream_table_pending_size": len(getattr(self, "_stream_table_pending", {})),
            "scan_result_side_effect_queue_size": len(getattr(self, "_scan_result_side_effect_queue", [])),
            "auto_paper_queue_size": len(getattr(self, "_auto_paper_queue", [])),
            "capture_key_by_analysis_size": len(getattr(self, "_capture_key_by_analysis_id", {})),
            "capture_identity_map_size": len(getattr(self, "_capture_identity_by_key", {})),
            "capture_failed_set_size": len(getattr(self, "_capture_failed_keys", set())),
            "capture_pending_age_map_size": len(getattr(self, "_capture_latency_started_by_key", {})),
            "capture_submitted_set_size": len(getattr(self, "_rc647_capture_submitted_keys", set())),
            "allocated_blocks": int(sys.getallocatedblocks()),
            "gc_count": list(gc.get_count()),
            "identity_warned_set_size": len(getattr(self, "_auto_paper_identity_warned_keys", set())),
            "identity_deferred_seen_size": len(getattr(self, "_rc647_identity_deferred_seen", set())),
            "identity_completed_keys_size": len(getattr(self, "_rc647_identity_completed_keys", set())),
            "identity_completed_order_size": len(getattr(self, "_rc647_identity_completed_order", [])),
            "analysis_id_by_capture_key_size": len(getattr(self, "_analysis_id_by_capture_key", {})),
            "callback_stack_depth": len(getattr(self, "_rc647_callback_stack", [])),
            "qtimer_child_count": len(self.findChildren(QTimer)),
            "qthread_child_count": len(self.findChildren(QThread)),
            "table_total_cell_capacity": table_items,
            "table_rows": table_rows,
        }
        self._append_rc63_jsonl("collection_snapshots.jsonl", payload)

    @Slot(object)
    def _on_object_census_snapshot(self, payload) -> None:
        record = dict(payload or {})
        record.update({
            "runtime_session_id": self._runtime_session_id,
            "pid": os.getpid(),
            "gui_thread_id": threading.get_ident(),
            "auto_paper_worker_object_id": self._auto_paper_worker_object_id,
            "auto_paper_worker_thread_running": bool(self._auto_paper_worker_thread.isRunning()),
            "auto_paper_payload_pending_count": len(self._auto_paper_payload_pending),
            "auto_paper_payload_dispatched_total": self._auto_paper_payload_dispatched_total,
            "auto_paper_payload_released_total": self._auto_paper_payload_released_total,
            "auto_paper_inflight": bool(self._auto_paper_inflight),
            "auto_paper_queue_size": len(getattr(self, "_auto_paper_queue", [])),
        })
        counts = record.get("counts") or {}
        record["auto_paper_worker_instance_invariant"] = int(counts.get("AutoPaperWorker", 0)) == 1
        self._append_rc63_jsonl("object_census.jsonl", record)

    @Slot(str)
    def _on_object_census_failed(self, message: str) -> None:
        self._append_rc63_jsonl("object_census.jsonl", {
            "schema_version": "dvs.runtime.object_census.v1",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "runtime_session_id": self._runtime_session_id,
            "pid": os.getpid(),
            "event": "object_census_failed",
            "message": str(message)[:240],
        })

    def _record_gui_hotspot(
        self,
        section: str,
        duration_ms: float,
        **details,
    ) -> None:
        """Append one bounded GUI hot-path measurement for RC6.2 audit.

        This is observe-only instrumentation. It does not change Decision Engine,
        scan scheduling, identity handling, Paper Trade rules, or execution state.
        """
        payload = {
            "schema_version": "dvs.runtime.gui_hotspot.v1",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "runtime_session_id": self._runtime_session_id,
            "pid": os.getpid(),
            "thread_id": threading.get_ident(),
            "section": str(section),
            "duration_ms": round(float(duration_ms), 3),
            **details,
        }
        try:
            path = Path("artifacts/runtime/gui_hotspots.jsonl")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
                )
                handle.flush()
        except Exception:
            logger.exception("GUI_HOTSPOT_WRITE_FAILED section=%s", section)

        # Keep the existing profiler as the canonical in-process source.
        if hasattr(self, "ui_profiler"):
            try:
                self.ui_profiler.record(str(section), float(duration_ms))
            except Exception:
                logger.exception("GUI_HOTSPOT_PROFILE_FAILED section=%s", section)

    def _performance_worker_state(self) -> str:
        if self.thread is not None and self.thread.isRunning():
            return "scanning"
        if self.finalization_thread is not None and self.finalization_thread.isRunning():
            return "finalizing"
        return "idle"

    def toggle_performance_overlay(self):
        visible = self.performance_overlay.toggle()
        self.settings.setValue("commercial/performance_overlay", visible)
        self.settings.sync()
        if hasattr(self, "status"):
            self.status.setText(
                "Performance Overlay: ON" if visible else "Performance Overlay: OFF"
            )

    def performance_overlay_diagnostics(self) -> dict:
        return self.performance_overlay.refresh_metrics()

    @_audit_gui_callback("commercial_status_tick")
    def _refresh_commercial_status(self):
        now = QDateTime.currentDateTime()
        if hasattr(self, "clock_label"):
            self.clock_label.setText(now.toString("dd/MM/yyyy  HH:mm:ss"))
        active_scan = self.thread is not None and self.thread.isRunning()
        active_finalize = (
            self.finalization_thread is not None
            and self.finalization_thread.isRunning()
        )
        if active_scan:
            state = "Workers: scanning"
        elif active_finalize:
            state = "Workers: finalizing"
        else:
            state = "Workers: idle"
        if hasattr(self, "worker_badge"):
            self.worker_badge.setText(state)
        if hasattr(self, "connection_badge"):
            self.connection_badge.setText(
                "● ENGINE BUSY" if (active_scan or active_finalize)
                else "● ENGINE READY"
            )
        if hasattr(self, "order_flow_badge"):
            self._refresh_order_flow_status()

    def _restore_commercial_session(self):
        geometry = self.settings.value("commercial/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        tab_index = self.settings.value("commercial/tab_index", 0, int)
        if 0 <= tab_index < self.tabs.count():
            self.tabs.setCurrentIndex(tab_index)
        auto_scan = self.settings.value("commercial/auto_scan", False, bool)
        if auto_scan:
            self.auto_scan_btn.setChecked(True)


    def _capture_key(self, analysis, scan_id=None):
        return (
            str(scan_id or getattr(self, "current_scan_id", "")),
            str(getattr(analysis, "symbol", "")),
        )

    @Slot(object, object, object)
    def _on_live_episode_capture_completed(self, analysis, episode_id, identity) -> None:
        key = self._capture_key_by_analysis_id.get(id(analysis))
        if key is None:
            key = self._capture_key(analysis)
        self._capture_identity_by_key[key] = identity
        self._capture_failed_keys.discard(key)
        started = self._capture_latency_started_by_key.pop(key, None)
        self._record_identity_diagnostic(
            "identity_published",
            key,
            latency_ms=(
                round((time.monotonic() - started) * 1000.0, 3)
                if started is not None else None
            ),
            analysis_object_id=hex(id(analysis)),
        )
        if started is not None:
            logger.info(
                "UNIFIED_IDENTITY_PUBLISHED symbol=%s key=%s latency_ms=%.1f pending=%s",
                getattr(analysis, "symbol", "UNKNOWN"),
                key,
                (time.monotonic() - started) * 1000.0,
                getattr(self.live_episode_capture, "pending_count", -1),
            )
        # Wake the Auto Paper queue so it can create a directly-bound trade.
        if not self.is_closing and getattr(self, "_auto_paper_queue", None):
            QTimer.singleShot(0, self._process_auto_paper_batch)

    @Slot(object, str)
    def _on_live_episode_capture_failed(self, analysis, message: str) -> None:
        key = self._capture_key_by_analysis_id.get(id(analysis))
        if key is None:
            key = self._capture_key(analysis)
        self._capture_failed_keys.add(key)
        self._capture_latency_started_by_key.pop(key, None)
        self._rc647_capture_submitted_keys.discard(key)
        self._record_identity_diagnostic(
            "identity_capture_failed", key, failure_message=str(message)
        )
        logger.error(
            "Live episode capture failed for %s key=%s: %s",
            getattr(analysis, "symbol", "UNKNOWN"),
            key,
            message,
        )

    @Slot(object, str)
    def _on_live_episode_capture_rejected(self, analysis, reason: str) -> None:
        logger.error(
            "Live episode capture rejected for %s: %s",
            getattr(analysis, "symbol", "UNKNOWN"),
            reason,
        )

    def _save_commercial_session(self):
        self.settings.setValue("commercial/geometry", self.saveGeometry())
        self.settings.setValue("commercial/tab_index", self.tabs.currentIndex())
        self.settings.setValue("commercial/auto_scan", self.auto_scan_btn.isChecked())
        if hasattr(self, "performance_overlay"):
            self.settings.setValue("commercial/performance_overlay", self.performance_overlay.isVisible())
        self.settings.sync()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "performance_overlay"):
            self.performance_overlay.reposition()
        if hasattr(self, "ui_geometry"):
            self.ui_geometry.observe_resize(
                event.size().width(),
                event.size().height(),
            )

    def paint_scheduler_diagnostics(self) -> dict:
        return self.paint_scheduler.diagnostics()

    def _shutdown_ux_write(self, event_name: str, **fields) -> None:
        """Emit bounded shutdown-UX telemetry without raising into the GUI."""
        try:
            from dvs_ai.runtime.qthread_lifecycle_registry import REGISTRY as registry
            registry._write(event_name, **fields)
        except Exception:
            logger.debug("Shutdown UX telemetry write failed", exc_info=True)

    def _show_shutdown_wait_dialog(self, survivor_count: int) -> None:
        dialog = getattr(self, "_shutdown_wait_dialog", None)
        if dialog is None:
            dialog = QDialog(self)
            dialog.setWindowTitle("DVS AI đang đóng an toàn")
            dialog.setModal(False)
            dialog.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
            layout = QVBoxLayout(dialog)
            label = QLabel(dialog)
            label.setWordWrap(True)
            layout.addWidget(label)
            progress = QProgressBar(dialog)
            progress.setRange(0, 0)
            layout.addWidget(progress)
            hide_button = QPushButton("Ẩn thông báo", dialog)
            hide_button.clicked.connect(dialog.hide)
            layout.addWidget(hide_button)
            dialog._shutdown_label = label
            self._shutdown_wait_dialog = dialog
        dialog._shutdown_label.setText(
            "Đang chờ %d tác vụ nền dừng an toàn. Ứng dụng sẽ tự đóng; "
            "không sử dụng terminate()." % max(0, int(survivor_count))
        )
        dialog.show()
        dialog.raise_()

    def _begin_shutdown_registry_poll(self, survivors: list[dict]) -> None:
        """Poll registry cheaply; never wait or terminate from the GUI timer."""
        from dvs_ai.runtime.shutdown_blocker_registry import ShutdownBlockerObserver
        observer = getattr(self, "_shutdown_blocker_observer", None)
        if observer is None:
            observer = ShutdownBlockerObserver(
                out_path="artifacts/runtime/shutdown_blockers.jsonl",
                slow_threshold_s=5.0,
            )
            self._shutdown_blocker_observer = observer
        observer.update(
            survivors,
            phase="registry_poll_begin",
            source="qthread_registry",
        )
        self._shutdown_registry_waiting = True
        self._shutdown_registry_poll_started_ns = time.monotonic_ns()
        self._shutdown_registry_poll_ticks = 0
        self._show_shutdown_wait_dialog(len(survivors))
        timer = getattr(self, "_shutdown_registry_poll_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setObjectName("shutdown-registry-poll")
            timer.setInterval(250)
            timer.setSingleShot(False)
            timer.timeout.connect(self._poll_shutdown_registry)
            self._shutdown_registry_poll_timer = timer
        if not timer.isActive():
            timer.start()
        self._shutdown_ux_write(
            "shutdown_ux_poll_started",
            interval_ms=250,
            initial_survivor_count=len(survivors),
            survivor_names=[row.get("object_name", "") for row in survivors],
        )

    def _poll_shutdown_registry(self) -> None:
        """One bounded GUI tick: snapshot only, with explicit timing telemetry."""
        tick_started_ns = time.monotonic_ns()
        budget_ms = 25.0
        try:
            from dvs_ai.runtime.qthread_lifecycle_registry import REGISTRY as registry
            rows = registry.snapshot("shutdown_ux_poll")
            survivors = [row for row in rows if row.get("is_running") is True]
        except Exception as exc:
            survivors = [{"object_name": "registry-error"}]
            logger.exception("Shutdown registry poll failed")
            self._shutdown_ux_write(
                "shutdown_ux_poll_failed", error_type=type(exc).__name__, error=str(exc)
            )
        measurement_ms = round((time.monotonic_ns() - tick_started_ns) / 1_000_000.0, 3)
        observer = getattr(self, "_shutdown_blocker_observer", None)
        normalized_survivors = survivors
        if observer is not None:
            normalized_survivors = observer.update(
                survivors,
                phase="registry_poll_tick",
                source="qthread_registry",
            )
        blocker_labels = (
            [row.get("blocker_label", "") for row in normalized_survivors]
            if normalized_survivors is not None
            else []
        )
        self._shutdown_registry_poll_ticks = int(getattr(self, "_shutdown_registry_poll_ticks", 0)) + 1
        self._shutdown_ux_write(
            "shutdown_ux_poll_tick",
            tick_index=self._shutdown_registry_poll_ticks,
            survivor_count=len(survivors),
            measurement_ms=measurement_ms,
            budget_ms=budget_ms,
            budget_exceeded=measurement_ms > budget_ms,
        )
        try:
            from dvs_ai.runtime.shutdown_blocker_registry import format_shutdown_wait_text
            self.status.setText(
                format_shutdown_wait_text(
                    len(survivors),
                    blocker_labels,
                    compact=True,
                )
            )
        except Exception:
            pass
        dialog = getattr(self, "_shutdown_wait_dialog", None)
        if dialog is not None:
            try:
                from dvs_ai.runtime.shutdown_blocker_registry import format_shutdown_wait_text
                dialog._shutdown_label.setText(
                    format_shutdown_wait_text(
                        len(survivors),
                        blocker_labels,
                        compact=False,
                    )
                )
            except Exception:
                pass
        if survivors:
            return
        timer = getattr(self, "_shutdown_registry_poll_timer", None)
        if timer is not None:
            timer.stop()
        self._shutdown_registry_waiting = False
        self._shutdown_pre_registry_complete = True
        elapsed_ms = round(
            (time.monotonic_ns() - int(self._shutdown_registry_poll_started_ns)) / 1_000_000.0, 3
        )
        self._shutdown_ux_write(
            "shutdown_ux_registry_clear",
            elapsed_ms=elapsed_ms,
            poll_ticks=self._shutdown_registry_poll_ticks,
        )
        observer = getattr(self, "_shutdown_blocker_observer", None)
        if observer is not None:
            observer.complete(phase="registry_clear")
        if dialog is not None:
            dialog.hide()
        QTimer.singleShot(0, self.close)

    def _run_ir01a_r6_strict_teardown_experiment(self, shutdown_probe=None) -> bool:
        """Controlled lifecycle experiment for Paper/History/AutoPaper workers.

        This intentionally changes only teardown ordering for the three selected
        pipelines.  It does not mutate CPython thread registries or trading logic.
        """
        if getattr(self, "_ir01a_r6_strict_teardown_done", False):
            return True
        self._ir01a_r6_strict_teardown_done = True

        experiment_path = "controlled_teardown_experiment.jsonl"

        def record(event_name: str, **extra) -> None:
            row = {
                "schema_version": "dvs.runtime.controlled_teardown_experiment.v1",
                "timestamp_utc": datetime.utcnow().isoformat(timespec="microseconds") + "Z",
                "pid": os.getpid(),
                "event": event_name,
                "gui_thread_ident": threading.get_ident(),
                "gui_qthread_name": QThread.currentThread().objectName(),
            }
            row.update(extra)
            try:
                self._append_rc63_jsonl(experiment_path, row)
            except Exception:
                logger.exception("IR-01A-r6 teardown telemetry write failed")

        try:
            import shiboken6
        except Exception:
            shiboken6 = None

        specs = (
            {
                "pipeline": "history",
                "thread_attr": "_history_prepare_thread",
                "worker_attr": "_history_prepare_worker",
                "producer_signal": self._history_prepare_requested,
                "worker_slot": getattr(self._history_prepare_worker, "prepare", None),
                "result_signal": getattr(self._history_prepare_worker, "prepared", None),
                "gui_slot": self._on_history_prepared,
            },
            {
                "pipeline": "paper",
                "thread_attr": "_paper_prepare_thread",
                "worker_attr": "_paper_prepare_worker",
                "producer_signal": self._paper_prepare_requested,
                "worker_slot": getattr(self._paper_prepare_worker, "prepare", None),
                "result_signal": getattr(self._paper_prepare_worker, "prepared", None),
                "gui_slot": self._on_paper_prepared,
            },
            {
                "pipeline": "auto_paper",
                "thread_attr": "_auto_paper_worker_thread",
                "worker_attr": "_auto_paper_worker",
                "producer_signal": self._auto_paper_work_requested,
                "worker_slot": getattr(self._auto_paper_worker, "process", None),
                "result_signal": None,
                "gui_slot": None,
            },
        )

        record(
            "experiment_begin",
            dummy_count=sum(1 for t in threading.enumerate() if t.__class__.__name__ == "_DummyThread"),
            active_count=len(threading.enumerate()),
        )

        all_ok = True
        for spec in specs:
            pipeline = spec["pipeline"]
            thread = getattr(self, spec["thread_attr"], None)
            worker = getattr(self, spec["worker_attr"], None)
            if thread is None or worker is None:
                record("pipeline_missing", pipeline=pipeline)
                continue

            thread_id = hex(id(thread))
            worker_id = hex(id(worker))
            try:
                thread_valid = bool(shiboken6.isValid(thread)) if shiboken6 is not None else None
                worker_valid = bool(shiboken6.isValid(worker)) if shiboken6 is not None else None
            except Exception:
                thread_valid = None
                worker_valid = None

            record(
                "pipeline_begin",
                pipeline=pipeline,
                qthread_object_id=thread_id,
                worker_object_id=worker_id,
                qthread_name=thread.objectName(),
                qthread_running=bool(thread.isRunning()),
                qthread_valid=thread_valid,
                worker_valid=worker_valid,
            )

            # Stop new work before touching lifecycle.
            if pipeline == "auto_paper":
                self._auto_paper_inflight = False
            state = getattr(self, "_data_prepare_state", {}).get(pipeline)
            if isinstance(state, dict):
                state["pending"] = None
                state["running"] = False

            disconnect_results = []
            for label, signal_obj, target in (
                ("producer", spec["producer_signal"], spec["worker_slot"]),
                ("result", spec["result_signal"], spec["gui_slot"]),
            ):
                if signal_obj is None or target is None:
                    continue
                try:
                    signal_obj.disconnect(target)
                    disconnect_results.append({"connection": label, "ok": True})
                except Exception as exc:
                    disconnect_results.append({
                        "connection": label,
                        "ok": False,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    })

            if pipeline == "auto_paper":
                for label, signal_name, target in (
                    ("completed", "completed", self._on_auto_paper_worker_completed),
                    ("failed", "failed", self._on_auto_paper_worker_failed),
                ):
                    signal_obj = getattr(worker, signal_name, None)
                    if signal_obj is None:
                        continue
                    try:
                        signal_obj.disconnect(target)
                        disconnect_results.append({"connection": label, "ok": True})
                    except Exception as exc:
                        disconnect_results.append({
                            "connection": label,
                            "ok": False,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        })

            record("signals_disconnected", pipeline=pipeline, results=disconnect_results)

            try:
                thread.requestInterruption()
            except Exception:
                pass

            # Queue deletion while the worker event loop is still alive, then stop it.
            delete_queued = False
            try:
                delete_queued = bool(
                    QMetaObject.invokeMethod(worker, "deleteLater", Qt.ConnectionType.QueuedConnection)
                )
            except Exception as exc:
                record(
                    "worker_deleteLater_queue_failed",
                    pipeline=pipeline,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )

            record(
                "worker_deleteLater_queued",
                pipeline=pipeline,
                invoke_return=delete_queued,
            )

            started_ns = time.monotonic_ns()
            try:
                thread.quit()
                wait_ok = bool(thread.wait(5000))
            except Exception as exc:
                wait_ok = False
                record(
                    "thread_wait_exception",
                    pipeline=pipeline,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            elapsed_ms = round((time.monotonic_ns() - started_ns) / 1_000_000.0, 3)
            running_after = bool(thread.isRunning()) if thread is not None else False

            try:
                worker_valid_after = bool(shiboken6.isValid(worker)) if shiboken6 is not None else None
                thread_valid_after = bool(shiboken6.isValid(thread)) if shiboken6 is not None else None
            except Exception:
                worker_valid_after = None
                thread_valid_after = None

            record(
                "thread_wait_completed",
                pipeline=pipeline,
                wait_ok=wait_ok,
                elapsed_ms=elapsed_ms,
                qthread_running_after=running_after,
                worker_valid_after_wait=worker_valid_after,
                qthread_valid_after_wait=thread_valid_after,
                dummy_count=sum(1 for t in threading.enumerate() if t.__class__.__name__ == "_DummyThread"),
                active_count=len(threading.enumerate()),
            )

            if not wait_ok or running_after:
                all_ok = False
                record("pipeline_teardown_failed", pipeline=pipeline)
                continue

            # QThread belongs to the GUI thread. Queue and flush its DeferredDelete
            # while QApplication's event loop is still alive.
            try:
                thread.deleteLater()
                QCoreApplication.sendPostedEvents(thread, QEvent.Type.DeferredDelete)
                QCoreApplication.processEvents()
                record("thread_deferred_delete_processed", pipeline=pipeline)
            except Exception as exc:
                all_ok = False
                record(
                    "thread_deferred_delete_failed",
                    pipeline=pipeline,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )

            setattr(self, spec["worker_attr"], None)
            setattr(self, spec["thread_attr"], None)
            record("pipeline_complete", pipeline=pipeline)

        record(
            "experiment_end",
            success=all_ok,
            dummy_count=sum(1 for t in threading.enumerate() if t.__class__.__name__ == "_DummyThread"),
            active_count=len(threading.enumerate()),
        )
        if shutdown_probe is not None:
            shutdown_probe.mark("ir01a_r6_strict_teardown_completed", success=all_ok)
            shutdown_probe.snapshot_threads("ir01a_r6_strict_teardown_completed")
        return all_ok

    def closeEvent(self,event):
        from dvs_ai.diagnostics.shutdown_probe import get_shutdown_probe
        from dvs_ai.runtime.mainwindow_wrapper_forensics import record_close_policy_decision
        from dvs_ai.runtime.shutdown_blocker_registry import (
            format_close_policy_blocker_text,
            record_close_policy_blocker,
        )
        record_close_policy_decision(
            self,
            "close_policy_enter",
            close_event=event,
            reason="user_close_event",
        )
        try:
            from dvs_ai.runtime.learning_dispatch_forensics import record_learning_dispatch
            record_learning_dispatch(
                "shutdown_close_event_enter",
                window=self,
                source="close_event",
                reason="user_close_event",
            )
        except Exception:
            pass
        _shutdown_probe = get_shutdown_probe()
        if _shutdown_probe is not None:
            _shutdown_probe.mark("main_window_close_event_enter", window_id=hex(id(self)))
            _shutdown_probe.snapshot_threads("main_window_close_event_enter")

        # RC6.11B (measurement only): checkpoint decomposition for the
        # close-path window between close_policy_gate_result and
        # paint_scheduler_close_begin. Purely additive -- records step
        # name, elapsed time, and (on failure) the Python exception repr.
        # Does not introspect any QObject/wrapper, does not add timers,
        # does not call processEvents(), does not change call order,
        # timeouts, existing try/except bodies, or event.accept()/ignore()
        # decisions. Local to this closeEvent call only.
        _shutdown_step_started_at: dict = {}

        def _shutdown_step_begin(step: str) -> None:
            _shutdown_step_started_at[step] = time.monotonic()
            if _shutdown_probe is not None:
                _shutdown_probe.mark("shutdown_step_begin", step=step)

        def _shutdown_step_end(step: str) -> None:
            elapsed_ms = round(
                (time.monotonic() - _shutdown_step_started_at.get(step, time.monotonic()))
                * 1000.0,
                3,
            )
            if _shutdown_probe is not None:
                _shutdown_probe.mark("shutdown_step_end", step=step, elapsed_ms=elapsed_ms)

        def _shutdown_step_error(step: str, exc: BaseException) -> None:
            elapsed_ms = round(
                (time.monotonic() - _shutdown_step_started_at.get(step, time.monotonic()))
                * 1000.0,
                3,
            )
            if _shutdown_probe is not None:
                _shutdown_probe.mark(
                    "shutdown_step_error",
                    step=step,
                    error=repr(exc),
                    elapsed_ms=elapsed_ms,
                )

        self.is_closing=True
        pending_before_close = bool(getattr(self, "_learning_refresh_pending", False))
        self._learning_refresh_pending = False
        try:
            from dvs_ai.runtime.learning_refresh_stabilization import record_stabilization
            record_stabilization(
                "shutdown_learning_backlog_cleared",
                pending_before_close=pending_before_close,
                refresh_running=bool(
                    getattr(self, "_learning_refresh_running", False)
                ),
            )
        except Exception:
            pass
        strict_teardown_ok = self._run_ir01a_r6_strict_teardown_experiment(_shutdown_probe)
        record_close_policy_decision(
            self,
            "close_policy_gate_result",
            close_event=event,
            reason="strict_teardown",
            gate_ok=bool(strict_teardown_ok),
        )
        if not strict_teardown_ok:
            try:
                self.status.setText(
                    "Không thể đóng an toàn: thí nghiệm teardown worker không hoàn tất."
                )
            except Exception:
                pass
            self.is_closing = False
            record_close_policy_decision(
                self,
                "close_policy_rejected",
                close_event=event,
                reason="strict_teardown_failed",
            )
            record_close_policy_blocker(
                self,
                reason="strict_teardown_failed",
                timeout_ms=None,
            )
            try:
                self.status.setText(
                    format_close_policy_blocker_text(
                        "strict_teardown_failed"
                    )
                )
            except Exception:
                pass
            event.ignore()
            return
        if _shutdown_probe is not None:
            _shutdown_probe.mark("shutdown_close_decomposition_begin")
        _shutdown_step_begin("qualification_metrics_thread_interrupt_quit")
        for thread_name in (
            "_qualification_metrics_thread",
        ):
            thread=getattr(self,thread_name,None)
            if thread is not None and thread.isRunning():
                if _shutdown_probe is not None:
                    _shutdown_probe.mark("thread_interrupt_quit_requested", owner="main_window", attribute=thread_name, object_id=hex(id(thread)), object_name=thread.objectName())
                thread.requestInterruption()
                thread.quit()
        _shutdown_step_end("qualification_metrics_thread_interrupt_quit")
        from dvs_ai.runtime.qthread_lifecycle_registry import REGISTRY as QTHREAD_REGISTRY
        if not getattr(self, "_shutdown_pre_registry_complete", False):
            _shutdown_step_begin("qthread_registry_snapshot_before_shutdown")
            QTHREAD_REGISTRY.snapshot("close_event_entered_before_shutdown")
            _shutdown_step_end("qthread_registry_snapshot_before_shutdown")
            # Defect B v5: stop dispatch and cancel Outcome Resolution first, while
            # the active stage still has a chance to observe the cooperative token.
            if hasattr(self, "outcome_resolution_timer"):
                _shutdown_step_begin("outcome_resolution_timer_stop")
                self.outcome_resolution_timer.stop()
                _shutdown_step_end("outcome_resolution_timer_stop")
            if hasattr(self, "outcome_resolution_coordinator"):
                try:
                    try:
                        from dvs_ai.runtime.outcome_resolution_forensics import (
                            record_outcome_resolution,
                        )
                        record_outcome_resolution(
                            "main_window_close_call_begin",
                            coordinator=self.outcome_resolution_coordinator,
                            timeout_ms=5000,
                        )
                    except Exception:
                        pass
                    _shutdown_step_begin("outcome_resolution_coordinator_close")
                    outcome_shutdown_ok = self.outcome_resolution_coordinator.close(timeout_ms=5000)
                    _shutdown_step_end("outcome_resolution_coordinator_close")
                    try:
                        record_outcome_resolution(
                            "main_window_close_call_end",
                            coordinator=self.outcome_resolution_coordinator,
                            timeout_ms=5000,
                            result=bool(outcome_shutdown_ok),
                        )
                    except Exception:
                        pass
                    if not outcome_shutdown_ok:
                        self.status.setText(
                            "Không thể đóng an toàn: Outcome Resolution chưa dừng trong 5 giây. "
                            "Vui lòng chờ rồi đóng lại."
                        )
                        self.is_closing = False
                        record_close_policy_decision(
                            self,
                            "close_policy_rejected",
                            close_event=event,
                            reason="outcome_resolution_timeout",
                        )
                        record_close_policy_blocker(
                            self,
                            reason="outcome_resolution_timeout",
                            timeout_ms=5000,
                        )
                        try:
                            self.status.setText(
                                format_close_policy_blocker_text(
                                    "outcome_resolution_timeout"
                                )
                            )
                        except Exception:
                            pass
                        event.ignore()
                        return
                except Exception as exc:
                    _shutdown_step_error("outcome_resolution_coordinator_close", exc)
                    logger.exception("Early Outcome Resolution coordinator shutdown failed")
                    self.status.setText("Không thể đóng an toàn: lỗi khi dừng Outcome Resolution.")
                    self.is_closing = False
                    record_close_policy_decision(
                        self,
                        "close_policy_rejected",
                        close_event=event,
                        reason="outcome_resolution_exception",
                    )
                    record_close_policy_blocker(
                        self,
                        reason="outcome_resolution_exception",
                        timeout_ms=None,
                    )
                    try:
                        self.status.setText(
                            format_close_policy_blocker_text(
                                "outcome_resolution_exception"
                            )
                        )
                    except Exception:
                        pass
                    event.ignore()
                    return
            try:
                _shutdown_step_begin("payload_footprint_telemetry_shutdown")
                payload_shutdown_ok = PAYLOAD_FOOTPRINT_TELEMETRY.shutdown(timeout_s=5.0)
                _shutdown_step_end("payload_footprint_telemetry_shutdown")
            except Exception as exc:
                _shutdown_step_error("payload_footprint_telemetry_shutdown", exc)
                logger.exception("Payload footprint worker shutdown failed")
                payload_shutdown_ok = False
            if not payload_shutdown_ok:
                logger.error("Payload footprint worker did not stop within shutdown timeout")
                try:
                    self.status.setText("Không thể đóng an toàn: tác vụ đo payload chưa dừng.")
                except Exception:
                    pass
                record_close_policy_decision(
                    self,
                    "close_policy_rejected",
                    close_event=event,
                    reason="payload_footprint_shutdown_failed",
                )
                record_close_policy_blocker(
                    self,
                    reason="payload_footprint_shutdown_failed",
                    timeout_ms=5000,
                )
                try:
                    self.status.setText(
                        format_close_policy_blocker_text(
                            "payload_footprint_shutdown_failed"
                        )
                    )
                except Exception:
                    pass
                event.ignore()
                return
            _shutdown_step_begin("cancel_active_universe_load")
            self._cancel_active_universe_load("application_closing")
            _shutdown_step_end("cancel_active_universe_load")
            try:
                _shutdown_step_begin("universe_thread_shutdown")
                universe_thread = getattr(self, "_universe_thread", None)
                if universe_thread is not None and universe_thread.isRunning():
                    universe_thread.requestInterruption()
                    universe_thread.quit()
                    # Provider deadlines bound the operation. Avoid blocking GUI close
                    # for the full network deadline; retain the object until process exit.
                    universe_thread.wait(250)
                _shutdown_step_end("universe_thread_shutdown")
            except Exception as exc:
                _shutdown_step_error("universe_thread_shutdown", exc)
                logger.exception("Universe loader worker shutdown failed")
            try:
                _shutdown_step_begin("outcome_thread_shutdown")
                outcome_thread = getattr(self, "_outcome_thread", None)
                if outcome_thread is not None and outcome_thread.isRunning():
                    outcome_thread.requestInterruption()
                    outcome_thread.quit()
                    outcome_thread.wait(250)
                _shutdown_step_end("outcome_thread_shutdown")
            except Exception as exc:
                _shutdown_step_error("outcome_thread_shutdown", exc)
                logger.exception("Outcome evaluator worker shutdown failed")
            try:
                _shutdown_step_begin("api_health_thread_shutdown")
                self._active_api_health_check_id = None
                api_health_thread = getattr(self, "_api_health_thread", None)
                if api_health_thread is not None and api_health_thread.isRunning():
                    api_health_thread.requestInterruption()
                    api_health_thread.quit()
                    api_health_thread.wait(250)
                _shutdown_step_end("api_health_thread_shutdown")
            except Exception as exc:
                _shutdown_step_error("api_health_thread_shutdown", exc)
                logger.exception("API health worker shutdown failed")
            try:
                _shutdown_step_begin("learning_refresh_shutdown")
                learning_worker = getattr(self, "_learning_worker", None)
                learning_thread = getattr(self, "_learning_thread", None)
                if learning_thread is not None and learning_thread.isRunning():
                    started = time.monotonic()
                    PAYLOAD_FOOTPRINT_TELEMETRY._write({
                        "event": "learning_refresh_shutdown_requested",
                        "thread_running": True,
                        "refresh_running": bool(getattr(self, "_learning_refresh_running", False)),
                        "timeout_ms": 5000,
                    })
                    try:
                        from dvs_ai.runtime.learning_refresh_lifecycle import snapshot_learning_refresh
                        snapshot_learning_refresh(
                            worker=learning_worker,
                            thread=learning_thread,
                            event="shutdown_sequence_enter",
                            timeout_ms=5000,
                            refresh_running=bool(
                                getattr(self, "_learning_refresh_running", False)
                            ),
                        )
                    except Exception:
                        pass
                    if learning_worker is not None:
                        learning_worker.request_stop()
                    try:
                        from dvs_ai.runtime.learning_refresh_lifecycle import snapshot_learning_refresh
                        snapshot_learning_refresh(
                            worker=learning_worker,
                            thread=learning_thread,
                            event="request_interruption_begin",
                        )
                    except Exception:
                        pass
                    learning_thread.requestInterruption()
                    try:
                        from dvs_ai.runtime.learning_refresh_lifecycle import snapshot_learning_refresh
                        snapshot_learning_refresh(
                            worker=learning_worker,
                            thread=learning_thread,
                            event="qthread_quit_begin",
                        )
                    except Exception:
                        pass
                    learning_thread.quit()
                    try:
                        from dvs_ai.runtime.learning_refresh_lifecycle import snapshot_learning_refresh
                        snapshot_learning_refresh(
                            worker=learning_worker,
                            thread=learning_thread,
                            event="qthread_wait_begin",
                            timeout_ms=5000,
                        )
                    except Exception:
                        pass
                    stopped = bool(learning_thread.wait(5000))
                    elapsed_ms = round((time.monotonic() - started) * 1000.0, 3)
                    try:
                        from dvs_ai.runtime.learning_refresh_lifecycle import snapshot_learning_refresh
                        snapshot_learning_refresh(
                            worker=learning_worker,
                            thread=learning_thread,
                            event=(
                                "qthread_wait_end"
                                if stopped and not learning_thread.isRunning()
                                else "qthread_wait_timeout"
                            ),
                            stopped=bool(stopped),
                            elapsed_ms=elapsed_ms,
                            timeout_ms=5000,
                        )
                    except Exception:
                        pass
                    if not stopped or learning_thread.isRunning():
                        PAYLOAD_FOOTPRINT_TELEMETRY._write({
                            "event": "learning_refresh_shutdown_timeout",
                            "thread_running": bool(learning_thread.isRunning()),
                            "elapsed_ms": elapsed_ms,
                            "timeout_ms": 5000,
                        })
                        logger.error(
                            "Learning refresh worker did not stop within 5000 ms; close rejected"
                        )
                        try:
                            self.status.setText(
                                "Không thể đóng an toàn: Learning Refresh chưa dừng. Vui lòng chờ rồi đóng lại."
                            )
                        except Exception:
                            pass
                        self.is_closing = False
                        record_close_policy_decision(
                            self,
                            "close_policy_rejected",
                            close_event=event,
                            reason="learning_refresh_shutdown_timeout",
                        )
                        record_close_policy_blocker(
                            self,
                            reason="learning_refresh_shutdown_timeout",
                            timeout_ms=5000,
                        )
                        try:
                            self.status.setText(
                                format_close_policy_blocker_text(
                                    "learning_refresh_shutdown_timeout"
                                )
                            )
                        except Exception:
                            pass
                        event.ignore()
                        return
                    PAYLOAD_FOOTPRINT_TELEMETRY._write({
                        "event": "learning_refresh_shutdown_completed",
                        "thread_running": False,
                        "elapsed_ms": elapsed_ms,
                    })
                _shutdown_step_end("learning_refresh_shutdown")
            except Exception as exc:
                _shutdown_step_error("learning_refresh_shutdown", exc)
                logger.exception("Learning refresh worker shutdown failed")
                PAYLOAD_FOOTPRINT_TELEMETRY._write({
                    "event": "learning_refresh_shutdown_failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                })
                self.is_closing = False
                record_close_policy_decision(
                    self,
                    "close_policy_rejected",
                    close_event=event,
                    reason="learning_refresh_shutdown_exception",
                )
                record_close_policy_blocker(
                    self,
                    reason="learning_refresh_shutdown_exception",
                    timeout_ms=None,
                )
                try:
                    self.status.setText(
                        format_close_policy_blocker_text(
                            "learning_refresh_shutdown_exception"
                        )
                    )
                except Exception:
                    pass
                event.ignore()
                return
            try:
                _shutdown_step_begin("signal_record_thread_shutdown")
                signal_record_thread = getattr(self, "_signal_record_thread", None)
                if signal_record_thread is not None and signal_record_thread.isRunning():
                    signal_record_thread.quit()
                    if not signal_record_thread.wait(5000):
                        logger.warning("Signal recorder worker did not stop within timeout")
                _shutdown_step_end("signal_record_thread_shutdown")
            except Exception as exc:
                _shutdown_step_error("signal_record_thread_shutdown", exc)
                logger.exception("Signal recorder worker shutdown failed")
            try:
                _shutdown_step_begin("object_census_worker_shutdown")
                census_worker = getattr(self, "_object_census_worker", None)
                census_thread = getattr(self, "_object_census_thread", None)
                if census_worker is not None and census_thread is not None and census_thread.isRunning():
                    # Invoke stop on the worker's own thread.  ObjectCensusWorker.stopped
                    # then queues QThread.quit(), preserving QTimer thread affinity.
                    from PySide6.QtCore import QMetaObject
                    QMetaObject.invokeMethod(census_worker, "stop", Qt.ConnectionType.QueuedConnection)
                    if not census_thread.wait(5000):
                        logger.warning("Object census worker did not stop within timeout")
                        census_thread.quit()
                        census_thread.wait(1000)
                _shutdown_step_end("object_census_worker_shutdown")
            except Exception as exc:
                _shutdown_step_error("object_census_worker_shutdown", exc)
                logger.exception("Object census worker shutdown failed")
            try:
                _shutdown_step_begin("auto_paper_thread_shutdown")
                auto_paper_thread = getattr(self, "_auto_paper_worker_thread", None)
                if auto_paper_thread is not None and auto_paper_thread.isRunning():
                    auto_paper_thread.quit()
                    if not auto_paper_thread.wait(5000):
                        logger.warning("Auto Paper worker did not stop within timeout")
                _shutdown_step_end("auto_paper_thread_shutdown")
            except Exception as exc:
                _shutdown_step_error("auto_paper_thread_shutdown", exc)
                logger.exception("Auto Paper worker shutdown failed")
            if _shutdown_probe is not None:
                _shutdown_probe.mark("qthread_registry_shutdown_begin")
                _shutdown_probe.snapshot_threads("qthread_registry_shutdown_begin")
            _shutdown_step_begin("qthread_registry_shutdown_registered")
            registry_ok, registry_survivors = QTHREAD_REGISTRY.shutdown_registered(timeout_ms=5000)
            _shutdown_step_end("qthread_registry_shutdown_registered")
            _shutdown_step_begin("qthread_registry_snapshot_after_shutdown")
            QTHREAD_REGISTRY.snapshot("close_event_after_registry_shutdown")
            _shutdown_step_end("qthread_registry_snapshot_after_shutdown")
            if _shutdown_probe is not None:
                _shutdown_probe.mark("qthread_registry_shutdown_end", ok=bool(registry_ok), survivor_count=len(registry_survivors), survivors=registry_survivors)
                _shutdown_probe.snapshot_threads("qthread_registry_shutdown_end")
            if not registry_ok:
                logger.error("QThread registry shutdown timeout: %s", registry_survivors)
                try:
                    self.status.setText("Không thể đóng an toàn: vẫn còn QThread đang chạy. Xem qthread_lifecycle.jsonl.")
                except Exception:
                    pass
                self._begin_shutdown_registry_poll(registry_survivors)
                record_close_policy_decision(
                    self,
                    "close_policy_rejected",
                    close_event=event,
                    reason="qthread_registry_survivors",
                )
                record_close_policy_blocker(
                    self,
                    reason="qthread_registry_survivors",
                    timeout_ms=None,
                )
                try:
                    self.status.setText(
                        format_close_policy_blocker_text(
                            "qthread_registry_survivors"
                        )
                    )
                except Exception:
                    pass
                event.ignore()
                return
            self._shutdown_pre_registry_complete = True
        _shutdown_step_begin("save_commercial_session")
        self._save_commercial_session()
        _shutdown_step_end("save_commercial_session")
        _shutdown_step_begin("ui_profiler_stop_and_report")
        if hasattr(self, "ui_profiler"):
            self.ui_profiler.stop()
            self.ui_profiler.log_report("close")
        _shutdown_step_end("ui_profiler_stop_and_report")
        _shutdown_step_begin("gui_timers_stop_and_queue_clear")
        if hasattr(self, "auto_scan_timer"):
            self.auto_scan_timer.stop()
        if hasattr(self, "aggregate_refresh_timer"):
            self.aggregate_refresh_timer.stop()
        if hasattr(self, "stream_table_timer"):
            self.stream_table_timer.stop()
        if hasattr(self, "scan_result_side_effect_timer"):
            self.scan_result_side_effect_timer.stop()
        self._stream_table_pending.clear()
        queue_before = len(self._scan_result_side_effect_queue)
        self._scan_result_side_effect_queue.clear()
        if hasattr(self, "_retention_owner_telemetry"):
            self._retention_owner_telemetry.record_mutation(
                "scan_result_side_effect_queue",
                operation="clear",
                count_before=queue_before,
                count_after=0,
                item_count=queue_before,
            )
        _shutdown_step_end("gui_timers_stop_and_queue_clear")
        _shutdown_step_begin("commercial_and_probe_timers_stop")
        if hasattr(self, "commercial_clock_timer"):
            self.commercial_clock_timer.stop()
        if hasattr(self, "rc63_scheduler_probe_timer"):
            self.rc63_scheduler_probe_timer.stop()
        if hasattr(self, "rc647_collection_probe_timer"):
            self.rc647_collection_probe_timer.stop()
        _shutdown_step_end("commercial_and_probe_timers_stop")
        _shutdown_step_begin("rc647_monitor_telemetry_join")
        self._rc647_monitor_stop.set()
        self._rc647_telemetry_stop.set()
        monitor_thread = getattr(self, "_rc647_monitor_thread", None)
        if monitor_thread is not None and monitor_thread.is_alive():
            monitor_thread.join(timeout=1.0)
        telemetry_thread = getattr(self, "_rc647_telemetry_thread", None)
        if telemetry_thread is not None and telemetry_thread.is_alive():
            telemetry_thread.join(timeout=1.5)
        _shutdown_step_end("rc647_monitor_telemetry_join")
        _shutdown_step_begin("gc_callback_remove")
        gc_callback = getattr(self, "_rc647_gc_callback", None)
        if gc_callback is not None:
            try:
                gc.callbacks.remove(gc_callback)
            except ValueError:
                pass
            self._rc647_gc_callback = None
        _shutdown_step_end("gc_callback_remove")
        _shutdown_step_begin("collection_writer_status_record")
        self._record_collection_writer_status(
            "collection_snapshot_writer_stopped",
            write_count=int(getattr(self, "_rc647_collection_sequence", 0)),
        )
        _shutdown_step_end("collection_writer_status_record")
        _shutdown_step_begin("outcome_resolution_timer_stop_second")
        if hasattr(self, "outcome_resolution_timer"):
            self.outcome_resolution_timer.stop()
        _shutdown_step_end("outcome_resolution_timer_stop_second")
        _shutdown_step_begin("performance_overlay_close_overlay")
        if hasattr(self, "performance_overlay"):
            self.performance_overlay.close_overlay()
        _shutdown_step_end("performance_overlay_close_overlay")
        _shutdown_step_begin("worker_stop")
        if self.worker is not None:
            try: self.worker.stop()
            except Exception: pass
        _shutdown_step_end("worker_stop")
        if (
            self.finalization_thread is not None
            and self.finalization_thread.isRunning()
        ):
            _shutdown_step_begin("finalization_thread_quit_wait")
            self.finalization_thread.quit()
            self.finalization_thread.wait(3000)
            _shutdown_step_end("finalization_thread_quit_wait")
        scan_runtime_thread = getattr(self, "_scan_runtime_thread", None)
        if scan_runtime_thread is not None and scan_runtime_thread.isRunning():
            self.status.setText("Đang dừng tác vụ nền...")
            _shutdown_step_begin("scan_runtime_thread_quit_wait")
            scan_runtime_thread.quit()
            scan_runtime_wait_ok = scan_runtime_thread.wait(6000)
            _shutdown_step_end("scan_runtime_thread_quit_wait")
            if not scan_runtime_wait_ok:
                self.status.setText("Tác vụ mạng chưa dừng. Vui lòng chờ rồi đóng lại.")
                record_close_policy_decision(
                    self,
                    "close_policy_rejected",
                    close_event=event,
                    reason="scan_runtime_thread_timeout",
                )
                record_close_policy_blocker(
                    self,
                    reason="scan_runtime_thread_timeout",
                    timeout_ms=6000,
                )
                try:
                    self.status.setText(
                        format_close_policy_blocker_text(
                            "scan_runtime_thread_timeout"
                        )
                    )
                except Exception:
                    pass
                event.ignore(); return
        if self.order_flow_runtime is not None:
            _shutdown_step_begin("order_flow_runtime_close")
            self.order_flow_runtime.close(timeout=5.0)
            _shutdown_step_end("order_flow_runtime_close")
        if self.core_runtime_adapter is not None:
            try:
                _shutdown_step_begin("core_runtime_adapter_shutdown")
                self.core_runtime_adapter._shutdown(timeout_ms=3000)
                _shutdown_step_end("core_runtime_adapter_shutdown")
            except Exception as exc:
                _shutdown_step_error("core_runtime_adapter_shutdown", exc)
                logger.exception("Unified Core shadow adapter shutdown failed")
        if hasattr(self, "episode_integrity_monitor"):
            try:
                _shutdown_step_begin("episode_integrity_monitor_close")
                self.episode_integrity_monitor.close(timeout_ms=5000)
                _shutdown_step_end("episode_integrity_monitor_close")
            except Exception as exc:
                _shutdown_step_error("episode_integrity_monitor_close", exc)
                logger.exception("Episode integrity monitor shutdown failed")
        if hasattr(self, "integrity_incident_ledger"):
            try:
                _shutdown_step_begin("integrity_incident_ledger_close")
                self.integrity_incident_ledger.close(timeout_ms=5000)
                _shutdown_step_end("integrity_incident_ledger_close")
            except Exception as exc:
                _shutdown_step_error("integrity_incident_ledger_close", exc)
                logger.exception("Integrity incident ledger shutdown failed")
        if hasattr(self, "integrity_alert_widget"):
            try:
                _shutdown_step_begin("integrity_alert_widget_close")
                self.integrity_alert_widget.close(timeout_ms=5000)
                _shutdown_step_end("integrity_alert_widget_close")
            except Exception as exc:
                _shutdown_step_error("integrity_alert_widget_close", exc)
                logger.exception("Integrity alert widget shutdown failed")
        if hasattr(self, "episode_audit_explorer"):
            try:
                _shutdown_step_begin("episode_audit_explorer_close")
                self.episode_audit_explorer.close(timeout_ms=5000)
                _shutdown_step_end("episode_audit_explorer_close")
            except Exception as exc:
                _shutdown_step_error("episode_audit_explorer_close", exc)
                logger.exception("Episode audit explorer shutdown failed")
        if hasattr(self, "research_experiment_widget"):
            try:
                _shutdown_step_begin("research_experiment_widget_close")
                self.research_experiment_widget.close(timeout_ms=5000)
                _shutdown_step_end("research_experiment_widget_close")
            except Exception as exc:
                _shutdown_step_error("research_experiment_widget_close", exc)
                logger.exception("Research experiment widget shutdown failed")
        if hasattr(self, "research_comparison_widget"):
            try:
                _shutdown_step_begin("research_comparison_widget_close")
                self.research_comparison_widget.close(timeout_ms=5000)
                _shutdown_step_end("research_comparison_widget_close")
            except Exception as exc:
                _shutdown_step_error("research_comparison_widget_close", exc)
                logger.exception("Research comparison widget shutdown failed")
        if hasattr(self, "research_cohort_widget"):
            try:
                _shutdown_step_begin("research_cohort_widget_close")
                shutdown = getattr(self.research_cohort_widget, "shutdown", None)
                if shutdown is not None:
                    shutdown(timeout_ms=5000)
                else:
                    self.research_cohort_widget.close()
                _shutdown_step_end("research_cohort_widget_close")
            except Exception as exc:
                _shutdown_step_error("research_cohort_widget_close", exc)
                logger.exception("Research cohort widget shutdown failed")
        if hasattr(self, "research_cohort_diagnostics_widget"):
            try:
                _shutdown_step_begin("research_cohort_diagnostics_widget_close")
                self.research_cohort_diagnostics_widget.close(timeout_ms=5000)
                _shutdown_step_end("research_cohort_diagnostics_widget_close")
            except Exception as exc:
                _shutdown_step_error("research_cohort_diagnostics_widget_close", exc)
                logger.exception("Research cohort diagnostics widget shutdown failed")
        if hasattr(self, "integrity_operations_console"):
            try:
                _shutdown_step_begin("integrity_operations_console_close")
                self.integrity_operations_console.close(timeout_ms=5000)
                _shutdown_step_end("integrity_operations_console_close")
            except Exception as exc:
                _shutdown_step_error("integrity_operations_console_close", exc)
                logger.exception("Integrity operations console shutdown failed")
        if hasattr(self, "statistical_diagnostics_dashboard"):
            try:
                _shutdown_step_begin("statistical_diagnostics_dashboard_close")
                self.statistical_diagnostics_dashboard.close(timeout_ms=5000)
                _shutdown_step_end("statistical_diagnostics_dashboard_close")
            except Exception as exc:
                _shutdown_step_error("statistical_diagnostics_dashboard_close", exc)
                logger.exception("Statistical diagnostics dashboard shutdown failed")
        # RC7.9: stop the non-GUI submitter before destroying its targets.
        try:
            self._stop_result_dispatcher(timeout_s=2.0)
        except Exception:
            logger.exception("Result dispatcher shutdown failed")

        if self.live_episode_capture is not None:
            close_capture = getattr(self.live_episode_capture, "close", None)
            if close_capture is not None:
                try:
                    _shutdown_step_begin("live_episode_capture_close")
                    close_capture(timeout_ms=5000)
                    _shutdown_step_end("live_episode_capture_close")
                except Exception as exc:
                    _shutdown_step_error("live_episode_capture_close", exc)
                    logger.exception("Live episode capture runner shutdown failed")
        if self.core_qualification_batch_runner is not None:
            try:
                _shutdown_step_begin("core_qualification_batch_runner_shutdown")
                self.core_qualification_batch_runner._shutdown(timeout_ms=5000)
                _shutdown_step_end("core_qualification_batch_runner_shutdown")
            except Exception as exc:
                _shutdown_step_error("core_qualification_batch_runner_shutdown", exc)
                logger.exception("Qualification batch runner shutdown failed")
        if _shutdown_probe is not None:
            _shutdown_probe.mark("shutdown_close_decomposition_end")
            _shutdown_probe.mark("paint_scheduler_close_begin")
        self.paint_scheduler.close(flush=False)
        if _shutdown_probe is not None:
            _shutdown_probe.mark("paint_scheduler_close_end")
            _shutdown_probe.snapshot_threads("main_window_before_event_accept")
            _shutdown_probe.mark("main_window_close_event_accept")
        record_close_policy_decision(
            self,
            "close_policy_accept_requested",
            close_event=event,
            reason="all_close_gates_passed",
        )
        event.accept()
        record_close_policy_decision(
            self,
            "close_policy_accept_completed",
            close_event=event,
            reason="all_close_gates_passed",
        )


    def _build_sidebar_navigation(self):
        self._validate_primary_workspace_contracts()
        """Build the UI 2.0 hierarchical navigation without changing page logic."""
        self.sidebar.clear()
        self._sidebar_items = {}

        def add_primary(label, widget, children=None):
            primary_index = self.tabs.indexOf(widget)
            item = QTreeWidgetItem([label])
            item.setData(0, Qt.ItemDataRole.UserRole, ("primary", primary_index, -1))
            self.sidebar.addTopLevelItem(item)
            self._sidebar_items[label] = item
            if children:
                child_tabs, child_labels = children
                for child_index, child_label in enumerate(child_labels):
                    child = QTreeWidgetItem([child_label])
                    child.setData(0, Qt.ItemDataRole.UserRole, ("nested", primary_index, child_index))
                    item.addChild(child)
                    self._sidebar_items[f"{label}/{child_label}"] = child
                item.setExpanded(True)
            return item

        dashboard_item = add_primary("Dashboard", self.dashboard_widget)
        add_primary("Phân tích chi tiết", self.detail_widget)
        add_primary(
            "Giao dịch",
            self.trading_folder_widget,
            (self.trading_tabs, ["Decision Core", "Smart Entry", "Paper Trade"]),
        )
        add_primary(
            "Phân tích thị trường",
            self.market_analysis_folder_widget,
            (self.market_analysis_tabs, [
                "Learning", "Liquidity & Wyckoff", "Smart Money",
                "Quantum Optimizer", "Lịch sử tín hiệu", "Truth Dashboard",
            ]),
        )
        add_primary(
            "Giám sát",
            self.monitoring_folder_widget,
            (self.monitoring_tabs, [
                "Statistical Diagnostics", "Episode Integrity",
                "Integrity History", "Integrity Alerts",
                "Integrity Operations", "Episode Audit",
            ]),
        )
        add_primary(
            "Nghiên cứu",
            self.research_folder_widget,
            (self.research_tabs, ["Thí nghiệm", "So sánh & tái lập", "Cohort & Batch", "Chẩn đoán cohort", "Lineage & Provenance", "Review & Approval", "Governance Dashboard", "Governance Incidents", "Compliance Operations", "Independent Audit Bundle", "Audit Bundle Verification"]),
        )
        add_primary(
            "Công cụ",
            self.tools_folder_widget,
            (self.tools_tabs, ["Trung tâm lỗi"]),
        )
        add_primary("Kiến thức", self.static_knowledge_library_widget)

        # Sidebar is now the only navigation surface for primary and folder tabs.
        self.tabs.tabBar().hide()
        for nested_tabs in (
            self.trading_tabs, self.market_analysis_tabs, self.monitoring_tabs,
            self.research_tabs, self.tools_tabs,
        ):
            nested_tabs.tabBar().hide()

        self.sidebar.itemClicked.connect(self._on_sidebar_item_clicked)
        self.sidebar.setCurrentItem(dashboard_item)
        self.tabs.setCurrentIndex(self.tabs.indexOf(self.dashboard_widget))

    @_audit_gui_callback("sidebar_item_clicked")
    def _on_sidebar_item_clicked(self, item, column=0):
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if not payload:
            return
        kind, primary_index, child_index = payload
        if primary_index < 0:
            return
        self.tabs.setCurrentIndex(primary_index)
        if kind != "nested":
            return
        primary_widget = self.tabs.widget(primary_index)
        nested_lookup = {
            self.trading_folder_widget: self.trading_tabs,
            self.market_analysis_folder_widget: self.market_analysis_tabs,
            self.monitoring_folder_widget: self.monitoring_tabs,
            self.research_folder_widget: self.research_tabs,
            self.tools_folder_widget: self.tools_tabs,
        }
        nested_tabs = nested_lookup.get(primary_widget)
        if nested_tabs is not None and 0 <= child_index < nested_tabs.count():
            self._ensure_lazy_nested_workspace(primary_widget, child_index)
            nested_tabs.setCurrentIndex(child_index)

    def _record_startup_phase(self, phase: str, started_ns: int, **extra) -> None:
        ended_ns = time.perf_counter_ns()
        self._append_rc63_jsonl("startup_decongestion.jsonl", {
            "schema_version": "dvs.startup_decongestion.v2.4.1",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "runtime_session_id": self._runtime_session_id,
            "event": "startup_init_phase",
            "phase": str(phase),
            "phase_ms": round((ended_ns - int(started_ns)) / 1_000_000.0, 3),
            "init_elapsed_ms": round((ended_ns - self._startup_init_started_ns) / 1_000_000.0, 3),
            **extra,
        })

    def showEvent(self, event):
        super().showEvent(event)
        if not self._startup_show_seen:
            self._startup_show_seen = True
            self._startup_show_ns = time.perf_counter_ns()
            self._append_rc63_jsonl("startup_decongestion.jsonl", {
                "schema_version": "dvs.startup_decongestion.v2",
                "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
                "runtime_session_id": self._runtime_session_id,
                "event": "window_show_event",
                "init_to_show_ms": round((self._startup_show_ns - self._startup_init_started_ns) / 1_000_000.0, 3),
                "shell_ready_to_show_ms": round((self._startup_show_ns - getattr(self, "_startup_shell_ready_ns", self._startup_show_ns)) / 1_000_000.0, 3),
            })

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._startup_first_paint_seen:
            self._startup_first_paint_seen = True
            first_paint_ns = time.perf_counter_ns()
            self._append_rc63_jsonl("startup_decongestion.jsonl", {
                "schema_version": "dvs.startup_decongestion.v2",
                "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
                "runtime_session_id": self._runtime_session_id,
                "event": "first_paint",
                "init_to_first_paint_ms": round((first_paint_ns - self._startup_init_started_ns) / 1_000_000.0, 3),
                "show_to_first_paint_ms": round((first_paint_ns - getattr(self, "_startup_show_ns", first_paint_ns)) / 1_000_000.0, 3),
            })
            callbacks = list(self._after_first_paint_callbacks)
            self._after_first_paint_callbacks.clear()
            for index, callback in enumerate(callbacks):
                QTimer.singleShot(25 + index * 25, callback)
            if not self._startup_deferred_scheduled:
                self._startup_deferred_scheduled = True
                QTimer.singleShot(75, self._start_deferred_ui_build)

    def defer_until_first_paint(self, callback) -> None:
        """Schedule non-shell startup work only after the first real paint."""
        if self._startup_first_paint_seen:
            QTimer.singleShot(0, callback)
        else:
            self._after_first_paint_callbacks.append(callback)

    def _make_folder_tabs(self, title, subtitle):
        folder = QWidget(self)
        layout = QVBoxLayout(folder)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        heading = QLabel(f"{title} · {subtitle}")
        heading.setObjectName("FolderHeading")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        tabs = QTabWidget(folder)
        tabs.setDocumentMode(True)
        tabs.setMovable(False)
        tabs.setUsesScrollButtons(True)
        tabs.setElideMode(Qt.TextElideMode.ElideRight)
        layout.addWidget(tabs, 1)
        return folder, tabs

    def _show_critical_startup_error(
        self,
        builder_name: str,
        exc: Exception,
    ) -> None:
        self._critical_startup_failed = True
        self._critical_startup_error = (
            f"{builder_name}: {type(exc).__name__}: {exc}"
        )
        placeholder = getattr(self, "_primary_workspace_placeholder", None)
        if placeholder is None:
            placeholder = QWidget(self)
            self._primary_workspace_placeholder = placeholder
            self.tabs.insertTab(0, placeholder, "Dashboard")
        layout = placeholder.layout()
        if layout is None:
            layout = QVBoxLayout(placeholder)
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        layout.addStretch(1)
        title = QLabel("KHÔNG THỂ KHỞI TẠO DASHBOARD")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setObjectName("CriticalStartupErrorTitle")
        layout.addWidget(title)
        detail = QLabel(
            "DVS AI đã dừng chuỗi xây giao diện để tránh chạy ở trạng thái "
            "thiếu Dashboard.\n\n"
            f"{self._critical_startup_error}\n\n"
            "Hãy thu Runtime Evidence và gửi lại để phân tích."
        )
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail.setWordWrap(True)
        detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(detail)
        layout.addStretch(1)
        self.start_btn.setEnabled(False)
        self.auto_scan_btn.setEnabled(False)
        if hasattr(self, "status"):
            self.status.setText(
                "Dashboard khởi tạo thất bại — runtime đã fail-closed"
            )

    def _validate_primary_workspace_contracts(self) -> None:
        required = {
            "dashboard_widget": getattr(self, "dashboard_widget", None),
            "table": getattr(self, "table", None),
            "detail_widget": getattr(self, "detail_widget", None),
        }
        missing = [
            name for name, value in required.items() if value is None
        ]
        if missing:
            raise RuntimeError(
                "Missing primary workspace contracts: "
                + ", ".join(missing)
            )

    def _build_dashboard_deferred(self) -> None:
        started_ns = time.perf_counter_ns()
        self._build_dashboard()
        self._append_rc63_jsonl("startup_decongestion.jsonl", {
            "schema_version": "dvs.startup_decongestion.v2.4.2",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "runtime_session_id": self._runtime_session_id,
            "event": "primary_workspace_build",
            "workspace": "dashboard",
            "elapsed_ms": round((time.perf_counter_ns() - started_ns) / 1_000_000.0, 3),
        })

    def _build_detail_deferred(self) -> None:
        started_ns = time.perf_counter_ns()
        self._build_detail_tab()
        if getattr(self, "dashboard_widget", None) is None:
            raise RuntimeError(
                "Detail build completed before Dashboard contract existed"
            )
        placeholder = getattr(self, "_primary_workspace_placeholder", None)
        if placeholder is not None:
            index = self.tabs.indexOf(placeholder)
            if index >= 0:
                self.tabs.removeTab(index)
            placeholder.deleteLater()
            self._primary_workspace_placeholder = None
        self.start_btn.setEnabled(True)
        self.auto_scan_btn.setEnabled(True)
        self._apply_ux_mode()
        self._append_rc63_jsonl("startup_decongestion.jsonl", {
            "schema_version": "dvs.startup_decongestion.v2.4.2",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "runtime_session_id": self._runtime_session_id,
            "event": "primary_workspace_build",
            "workspace": "detail",
            "elapsed_ms": round((time.perf_counter_ns() - started_ns) / 1_000_000.0, 3),
            "primary_ready": True,
        })

    @Slot()
    def _start_deferred_ui_build(self):
        if self._deferred_ui_build_active:
            return
        self._deferred_ui_build_active = True
        self._deferred_ui_build_started_ns = time.perf_counter_ns()
        self._build_next_deferred_workspace()

    @Slot()
    def _build_next_deferred_workspace(self):
        if self._critical_startup_failed:
            self._deferred_ui_build_active = False
            return

        queue = getattr(self, "_deferred_ui_build_queue", None)
        if not queue:
            try:
                self._validate_primary_workspace_contracts()
                self._build_sidebar_navigation()
                self._apply_ux_mode()
            except Exception as exc:
                self._show_critical_startup_error(
                    "primary_workspace_finalization",
                    exc,
                )
                self._deferred_ui_build_active = False
                return
            self._deferred_ui_build_active = False
            self._append_rc63_jsonl("startup_decongestion.jsonl", {
                "schema_version": "dvs.startup_decongestion.v2",
                "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
                "runtime_session_id": self._runtime_session_id,
                "event": "lazy_workspace_build_completed",
                "elapsed_ms": round(
                    (
                        time.perf_counter_ns()
                        - self._deferred_ui_build_started_ns
                    ) / 1_000_000.0,
                    3,
                ),
                "tab_count": int(self.tabs.count()),
            })
            return

        builder = queue.popleft()
        started_ns = time.perf_counter_ns()
        name = getattr(builder, "__name__", type(builder).__name__)
        critical = builder in {
            self._build_dashboard_deferred,
            self._build_detail_deferred,
        }
        try:
            builder()
            status = "completed"
            error = None
        except Exception as exc:
            status = "failed"
            error = f"{type(exc).__name__}: {exc}"
            logger.exception(
                "Deferred workspace build failed builder=%s critical=%s",
                name,
                critical,
            )
            if critical:
                self._show_critical_startup_error(name, exc)

        self._append_rc63_jsonl("startup_decongestion.jsonl", {
            "schema_version": "dvs.startup_decongestion.v2",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "runtime_session_id": self._runtime_session_id,
            "event": "lazy_workspace_build_step",
            "builder": name,
            "critical": bool(critical),
            "status": status,
            "elapsed_ms": round(
                (time.perf_counter_ns() - started_ns) / 1_000_000.0,
                3,
            ),
            "remaining": len(queue),
            "error": error,
        })

        if self._critical_startup_failed:
            self._deferred_ui_build_active = False
            return

        QTimer.singleShot(25, self._build_next_deferred_workspace)

    def _build_on_tabs(self, target_tabs, builders):
        primary_tabs = self.tabs
        try:
            self.tabs = target_tabs
            for builder in builders:
                builder()
        finally:
            self.tabs = primary_tabs

    def _make_lazy_workspace_placeholder(self, label: str) -> QWidget:
        placeholder = QWidget(self)
        layout = QVBoxLayout(placeholder)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addStretch(1)
        message = QLabel(f"{label}\n\nMở lần đầu để khởi tạo workspace.")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setWordWrap(True)
        message.setObjectName("LazyWorkspacePlaceholder")
        layout.addWidget(message)
        layout.addStretch(1)
        return placeholder

    def _register_lazy_nested_workspace(
        self,
        primary_widget,
        nested_tabs,
        labels,
        builders,
    ) -> None:
        if len(labels) != len(builders):
            raise ValueError("Lazy workspace labels/builders length mismatch")
        entries = []
        for index, (label, builder) in enumerate(zip(labels, builders)):
            placeholder = self._make_lazy_workspace_placeholder(label)
            nested_tabs.addTab(placeholder, label)
            entries.append({
                "label": str(label),
                "builder": builder,
                "placeholder": placeholder,
                "built": False,
                "index": int(index),
            })
        self._lazy_nested_workspaces[id(primary_widget)] = {
            "primary_widget": primary_widget,
            "tabs": nested_tabs,
            "entries": entries,
        }

    def _ensure_lazy_nested_workspace(
        self,
        primary_widget,
        child_index: int,
    ) -> None:
        registry = self._lazy_nested_workspaces.get(id(primary_widget))
        if not registry:
            return
        entries = registry["entries"]
        if not (0 <= int(child_index) < len(entries)):
            return
        entry = entries[int(child_index)]
        if entry["built"]:
            return

        key = (id(primary_widget), int(child_index))
        if key in self._lazy_nested_build_active:
            return
        self._lazy_nested_build_active.add(key)

        nested_tabs = registry["tabs"]
        placeholder = entry["placeholder"]
        label = entry["label"]
        builder = entry["builder"]
        previous_primary_tabs = self.tabs
        try:
            self.tabs = nested_tabs
            before_count = nested_tabs.count()
            builder()
            if nested_tabs.count() != before_count + 1:
                raise RuntimeError(
                    f"Lazy builder {getattr(builder, '__name__', builder)!r} "
                    "must add exactly one tab"
                )
            built_widget = nested_tabs.widget(nested_tabs.count() - 1)
            built_label = nested_tabs.tabText(nested_tabs.count() - 1) or label
            nested_tabs.removeTab(nested_tabs.count() - 1)

            placeholder_index = nested_tabs.indexOf(placeholder)
            if placeholder_index < 0:
                placeholder_index = int(child_index)
            else:
                nested_tabs.removeTab(placeholder_index)
            nested_tabs.insertTab(placeholder_index, built_widget, built_label)
            placeholder.deleteLater()

            entry["placeholder"] = None
            entry["built"] = True
            entry["widget"] = built_widget
        except Exception as exc:
            logger.exception(
                "Lazy workspace build failed label=%s index=%s",
                label,
                child_index,
            )
            if hasattr(self, "status"):
                self.status.setText(
                    f"Không thể khởi tạo {label}: {type(exc).__name__}"
                )
        finally:
            self.tabs = previous_primary_tabs
            self._lazy_nested_build_active.discard(key)

    def _build_trading_folder_tab(self):
        folder, tabs = self._make_folder_tabs(
            "GIAO DỊCH",
            "Decision Core · Smart Entry · Paper Trade",
        )
        self.trading_tabs = tabs
        primary_tabs = self.tabs
        try:
            self.tabs = tabs
            self._build_core_tab()
            self._build_smart_entry_tab()
            self._build_paper_trade_tab()
        finally:
            self.tabs = primary_tabs
        self.trading_folder_widget = folder
        self.tabs.addTab(folder, "Giao dịch")

    def _build_market_analysis_folder_tab(self):
        folder, tabs = self._make_folder_tabs(
            "PHÂN TÍCH THỊ TRƯỜNG",
            "Cấu trúc · Dòng tiền · Lịch sử · Truth",
        )
        self.market_analysis_tabs = tabs
        primary_tabs = self.tabs
        try:
            self.tabs = tabs
            self._build_backtest_tab()
            self._build_structure_tab()
            self._build_microstructure_tab()
            self._build_quantum_optimizer_tab()
            self._build_history_tab()
            self._build_truth_dashboard_tab()
        finally:
            self.tabs = primary_tabs
        self.market_analysis_folder_widget = folder
        self.market_analysis_tabs.currentChanged.connect(
            self._on_market_analysis_tab_changed
        )
        self.tabs.addTab(folder, "Phân tích thị trường")

    def _build_monitoring_folder_tab(self):
        folder, tabs = self._make_folder_tabs(
            "GIÁM SÁT & KIỂM ĐỊNH",
            "Statistical · Episode · Integrity · Audit",
        )
        self.monitoring_tabs = tabs
        self.monitoring_folder_widget = folder
        self._register_lazy_nested_workspace(
            folder,
            tabs,
            [
                "Statistical Diagnostics",
                "Episode Integrity",
                "Integrity History",
                "Integrity Alerts",
                "Integrity Operations",
                "Episode Audit",
            ],
            [
                self._build_statistical_diagnostics_tab,
                self._build_episode_integrity_tab,
                self._build_integrity_incident_ledger_tab,
                self._build_integrity_alert_tab,
                self._build_integrity_operations_console_tab,
                self._build_episode_audit_tab,
            ],
        )
        self.tabs.addTab(folder, "Giám sát")

    def _build_tools_folder_tab(self):
        folder, tabs = self._make_folder_tabs(
            "CÔNG CỤ",
            "Chẩn đoán và xử lý lỗi kỹ thuật",
        )
        self.tools_tabs = tabs
        primary_tabs = self.tabs
        try:
            self.tabs = tabs
            self._build_error_tab()
        finally:
            self.tabs = primary_tabs
        self.tools_folder_widget = folder
        self.tabs.addTab(folder, "Công cụ")

    def _build_static_knowledge_library_tab(self):
        # EDU-01 explicit UI-only integration; no runtime context is passed.
        self.static_knowledge_library_widget = StaticKnowledgeLibraryWidget(parent=self)
        self.tabs.addTab(self.static_knowledge_library_widget, "Kiến thức")

    def _build_episode_audit_tab(self):
        db_path = str(getattr(self.paper_trade_service, "db_path", "data/dvs_paper_trades.db"))
        self.episode_audit_explorer = EpisodeAuditExplorer(db_path, parent=self)
        self.tabs.addTab(self.episode_audit_explorer, "Episode Audit")

    def _build_episode_integrity_tab(self):
        db_path = str(getattr(self.paper_trade_service, "db_path", "data/dvs_paper_trades.db"))
        self.episode_integrity_monitor = EpisodeIntegrityMonitorWidget(db_path, parent=self)
        self.tabs.addTab(self.episode_integrity_monitor, "Episode Integrity")

    def _build_integrity_incident_ledger_tab(self):
        db_path = str(getattr(self.paper_trade_service, "db_path", "data/dvs_paper_trades.db"))
        self.integrity_incident_ledger = IntegrityIncidentLedgerWidget(
            db_path,
            "data/dvs_integrity_ledger.db",
            parent=self,
        )
        self.tabs.addTab(self.integrity_incident_ledger, "Integrity History")

    def _build_integrity_alert_tab(self):
        db_path = str(getattr(self.paper_trade_service, "db_path", "data/dvs_paper_trades.db"))
        self.integrity_alert_widget = IntegrityAlertWidget(
            db_path,
            "data/dvs_integrity_ledger.db",
            parent=self,
        )
        self.tabs.addTab(self.integrity_alert_widget, "Integrity Alerts")

    def _build_integrity_operations_console_tab(self):
        db_path = str(getattr(self.paper_trade_service, "db_path", "data/dvs_paper_trades.db"))
        self.integrity_operations_console = IntegrityOperationsConsoleWidget(db_path, "data/dvs_integrity_ledger.db", parent=self)
        self.tabs.addTab(self.integrity_operations_console, "Integrity Operations")

    def _build_research_folder_tab(self):
        """Create research navigation shell; build each tool on first use."""
        db_path = str(getattr(
            self.paper_trade_service,
            "db_path",
            "data/dvs_paper_trades.db",
        ))
        folder = QWidget(self)
        layout = QVBoxLayout(folder)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        heading = QLabel(
            "KHU VỰC NGHIÊN CỨU · Read-only · Không thay đổi Decision Engine"
        )
        heading.setObjectName("ResearchFolderHeading")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        tabs = QTabWidget(folder)
        tabs.setDocumentMode(True)
        tabs.setMovable(False)
        tabs.setUsesScrollButtons(True)
        tabs.setElideMode(Qt.TextElideMode.ElideRight)
        layout.addWidget(tabs, 1)
        self.research_tabs = tabs
        self.research_folder_widget = folder

        def build_experiment():
            self.research_experiment_widget = ResearchExperimentWidget(
                db_path, "data/research_workspace.db", parent=tabs
            )
            tabs.addTab(self.research_experiment_widget, "Thí nghiệm")

        def build_comparison():
            self.research_comparison_widget = ResearchComparisonWidget(
                "data/research_workspace.db", parent=tabs
            )
            tabs.addTab(self.research_comparison_widget, "So sánh & tái lập")

        def build_cohort():
            self.research_cohort_widget = ResearchCohortWidget(
                db_path, "data/research_workspace.db", parent=tabs
            )
            tabs.addTab(self.research_cohort_widget, "Cohort & Batch")

        def build_cohort_diagnostics():
            self.research_cohort_diagnostics_widget = (
                ResearchCohortDiagnosticsWidget(
                    "data/research_workspace.db", parent=tabs
                )
            )
            tabs.addTab(
                self.research_cohort_diagnostics_widget,
                "Chẩn đoán cohort",
            )

        def build_lineage():
            self.research_lineage_provenance_widget = (
                ResearchLineageProvenanceWidget(
                    "data/research_workspace.db", parent=tabs
                )
            )
            tabs.addTab(
                self.research_lineage_provenance_widget,
                "Lineage & Provenance",
            )

        def build_review():
            self.research_review_workflow_widget = ResearchReviewWorkflowWidget(
                "data/research_workspace.db",
                "data/research_reviews.db",
                parent=tabs,
            )
            tabs.addTab(
                self.research_review_workflow_widget,
                "Review & Approval",
            )

        def build_governance_dashboard():
            self.research_governance_dashboard_widget = (
                ResearchGovernanceDashboardWidget(
                    "data/research_workspace.db",
                    "data/research_reviews.db",
                    parent=tabs,
                )
            )
            tabs.addTab(
                self.research_governance_dashboard_widget,
                "Governance Dashboard",
            )

        def build_governance_incidents():
            self.governance_incident_ledger_widget = (
                GovernanceIncidentLedgerWidget(
                    "data/research_workspace.db",
                    "data/research_reviews.db",
                    "data/research_governance_ledger.db",
                    parent=tabs,
                )
            )
            tabs.addTab(
                self.governance_incident_ledger_widget,
                "Governance Incidents",
            )

        def build_compliance():
            self.governance_compliance_operations_widget = (
                GovernanceComplianceOperationsWidget(
                    "data/research_workspace.db",
                    "data/research_reviews.db",
                    "data/research_governance_ledger.db",
                    parent=tabs,
                )
            )
            tabs.addTab(
                self.governance_compliance_operations_widget,
                "Compliance Operations",
            )

        def build_audit_bundle():
            self.research_governance_audit_bundle_widget = (
                ResearchGovernanceAuditBundleWidget(
                    "data/research_workspace.db",
                    "data/research_reviews.db",
                    "data/research_governance_ledger.db",
                    parent=tabs,
                )
            )
            tabs.addTab(
                self.research_governance_audit_bundle_widget,
                "Independent Audit Bundle",
            )

        def build_audit_verifier():
            self.audit_bundle_verifier_widget = AuditBundleVerifierWidget(
                parent=tabs
            )
            tabs.addTab(
                self.audit_bundle_verifier_widget,
                "Audit Bundle Verification",
            )

        self._register_lazy_nested_workspace(
            folder,
            tabs,
            [
                "Thí nghiệm",
                "So sánh & tái lập",
                "Cohort & Batch",
                "Chẩn đoán cohort",
                "Lineage & Provenance",
                "Review & Approval",
                "Governance Dashboard",
                "Governance Incidents",
                "Compliance Operations",
                "Independent Audit Bundle",
                "Audit Bundle Verification",
            ],
            [
                build_experiment,
                build_comparison,
                build_cohort,
                build_cohort_diagnostics,
                build_lineage,
                build_review,
                build_governance_dashboard,
                build_governance_incidents,
                build_compliance,
                build_audit_bundle,
                build_audit_verifier,
            ],
        )
        self.tabs.addTab(folder, "Nghiên cứu")

    def _build_statistical_diagnostics_tab(self):
        db_path = str(getattr(
            self.paper_trade_service,
            "db_path",
            "data/dvs_paper_trades.db",
        ))
        self.statistical_diagnostics_dashboard = StatisticalDiagnosticsDashboard(
            db_path,
            parent=self,
        )
        self.tabs.addTab(
            self.statistical_diagnostics_dashboard,
            "Statistical Diagnostics",
        )

    def _build_dashboard(self):
        dash = QWidget(); dash.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored); layout = QVBoxLayout(dash); layout.setContentsMargins(6,6,6,6); layout.setSpacing(5)
        metrics = QHBoxLayout()
        self.market_bias_card = MetricCard("ĐỊNH HƯỚNG THỊ TRƯỜNG")
        self.risk_card = MetricCard("MỨC RỦI RO")
        self.breadth_card = MetricCard("ĐỘ RỘNG WATCHLIST")
        self.hot_card = MetricCard("CƠ HỘI READY")
        self.error_card = MetricCard("LỖI DỮ LIỆU")
        for c in (self.market_bias_card,self.risk_card,self.breadth_card,self.hot_card,self.error_card):
            metrics.addWidget(c)
        layout.addLayout(metrics, 0)

        pulse_row = QHBoxLayout()
        self.btc_pulse = MetricCard("BTC PULSE")
        self.flow_pulse = MetricCard("DÒNG TIỀN")
        self.momentum_pulse = MetricCard("ĐỘNG LƯỢNG")
        self.oi_pulse = MetricCard("OI / FUNDING")
        for c in (self.btc_pulse, self.flow_pulse, self.momentum_pulse, self.oi_pulse):
            pulse_row.addWidget(c)
        layout.addLayout(pulse_row, 0)

        top = QHBoxLayout()
        self.brief = QTextEdit()
        self.brief.setReadOnly(True)
        self.brief.setMaximumHeight(72)
        self.brief.setMinimumHeight(72)

        self.top_long = QTextEdit()
        self.top_long.setReadOnly(True)
        self.top_long.setMaximumHeight(72)
        self.top_long.setMinimumHeight(72)

        self.top_short = QTextEdit()
        self.top_short.setReadOnly(True)
        self.top_short.setMaximumHeight(72)
        self.top_short.setMinimumHeight(72)

        brief_panel = self._panel("🌍 MARKET BRIEF", self.brief)
        long_panel = self._panel("🔥 TOP LONG", self.top_long)
        short_panel = self._panel("🔴 TOP SHORT", self.top_short)
        for panel in (brief_panel, long_panel, short_panel):
            panel.setMinimumHeight(102)
            panel.setMaximumHeight(102)

        top.addWidget(brief_panel, 3)
        top.addWidget(long_panel, 2)
        top.addWidget(short_panel, 2)
        layout.addLayout(top,0)

        # Dashboard compact: đưa Confidence lên ngay sau Coin để luôn nằm
        # trong cùng một màn hình. Các chỉ số 1h chi tiết vẫn có ở tab
        # Phân tích chi tiết, tránh làm bảng chính quá rộng.
        self.table = QTableWidget(0, 17)
        self.table.setHorizontalHeaderLabels([
            "COIN",
            "CONF.",
            "GIÁ",
            "24H",
            "OI 15M",
            "OI 1H",
            "FUND.",
            "CMF 15M",
            "RSI 15M",
            "ADX 15M",
            "VOL 15M",
            "MARKET PHASE",
            "L-TREND",
            "L-ENTRY",
            "S-TREND",
            "S-ENTRY",
            "STATUS",
        ])
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setWordWrap(False)
        self.table.setShowGrid(False)
        self.table.setObjectName("OperatorMarketTable")

        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(38)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header.setStretchLastSection(False)

        # RC7.6-UI-C — preserve all four directional score columns while
        # fitting the full trading table inside the normal 1600–1920 px view.
        compact_widths = {
            0: 104,  # Coin
            1: 58,   # Confidence
            2: 76,   # Price
            3: 52,   # 24H
            4: 58,   # OI 15M
            5: 58,   # OI 1H
            6: 60,   # Funding
            7: 62,   # CMF 15M
            8: 58,   # RSI 15M
            9: 60,   # ADX 15M
            10: 60,  # VOL 15M
            12: 58,  # Long Trend
            13: 58,  # Long Entry
            14: 58,  # Short Trend
            15: 58,  # Short Entry
            16: 70,  # Status
        }
        for column, width in compact_widths.items():
            self.table.setColumnWidth(column, width)

        # Market Phase is a primary decision variable. It receives the
        # flexible section and is never intentionally abbreviated.
        header.setSectionResizeMode(
            11,
            QHeaderView.ResizeMode.Stretch,
        )
        header.setMinimumSectionSize(50)
        self.table.setColumnWidth(11, 168)

        self.table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.table.itemSelectionChanged.connect(self.show_selected)

        # Mặc định xếp Confidence từ cao xuống thấp.
        self.table.horizontalHeader().setSortIndicator(
            1, Qt.SortOrder.DescendingOrder
        )
        layout.addWidget(self.table,1)
        self.dashboard_widget = dash
        self.tabs.addTab(dash,"Dashboard")



    def _build_truth_dashboard_tab(self):
        self.truth_dashboard = TruthDashboard(
            analysis_provider=lambda: self.current_analysis,
            runtime_provider=(
                self.order_flow_runtime.diagnostics
                if self.order_flow_runtime is not None
                else lambda: {"state": "DISABLED", "running": False}
            ),
            observation_provider=(
                self.shadow_observation_runtime.diagnostics
                if self.shadow_observation_runtime is not None
                else lambda: {"recorded":0,"bound":0,"closed":0,"errors":0,"candidate_id":"DISABLED"}
            ),
        )
        self._truth_dashboard_tab_index = self.tabs.addTab(
            self.truth_dashboard, "Truth Dashboard"
        )
        self.truth_dashboard.set_active(False)

    def _build_detail_tab(self):
        detail = QWidget()
        page_layout = QVBoxLayout(detail)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        detail_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        detail_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )

        detail_content = QWidget()
        detail_content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        # RC7.6-UI-A: reserve the complete vertical canvas explicitly.
        # The parent QScrollArea handles smaller screens; the right-side cards
        # must never be compressed on top of the lower two gauges.
        detail_content.setMinimumHeight(1010)
        outer = QVBoxLayout(detail_content)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.detail_splitter = splitter
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(3)
        splitter.setOpaqueResize(False)

        left = QWidget()
        left.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.MinimumExpanding,
        )
        ll = QVBoxLayout(left)
        ll.setContentsMargins(2, 2, 2, 2)
        ll.setSpacing(6)
        ll.setAlignment(Qt.AlignmentFlag.AlignTop)

        title_row = QHBoxLayout()
        self.detail_title = QLabel("<h2>Chọn coin trong Dashboard</h2>")
        self.detail_title.setMaximumHeight(32)
        self.detail_title.setMinimumWidth(0)
        self.detail_title.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.long_zone_btn = QPushButton("✓ Hiện Long")
        self.long_zone_btn.setCheckable(True)
        self.long_zone_btn.setMaximumHeight(34)
        self.long_zone_btn.setChecked(True)
        self.short_zone_btn = QPushButton("✓ Hiện Short")
        self.short_zone_btn.setCheckable(True)
        self.short_zone_btn.setMaximumHeight(34)
        self.short_zone_btn.setChecked(True)
        self.signal_marker_btn = QPushButton("✓ Tín hiệu")
        self.signal_marker_btn.setCheckable(True)
        self.signal_marker_btn.setMaximumHeight(34)
        self.signal_marker_btn.setChecked(True)
        self.tf_selector = QComboBox()
        self.tf_selector.addItems(["15m", "1h", "4h", "1d"])
        self.tf_selector.setMaximumWidth(90)
        self.tf_selector.currentTextChanged.connect(self.change_chart_timeframe)
        self.long_zone_btn.toggled.connect(self.update_chart_overlays)
        self.short_zone_btn.toggled.connect(self.update_chart_overlays)
        self.signal_marker_btn.toggled.connect(self.update_chart_overlays)
        title_row.addWidget(self.detail_title)
        title_row.addStretch()
        title_row.addWidget(self.long_zone_btn)
        title_row.addWidget(self.short_zone_btn)
        title_row.addWidget(self.signal_marker_btn)
        title_row.addWidget(QLabel("Khung:"))
        title_row.addWidget(self.tf_selector)
        ll.addLayout(title_row)

        # Approved RC7.6-UI-C design: one compact market-structure strip.
        # It removes the large unused black region above the chart.
        score_container = QWidget()
        score_container.setObjectName("DetailStructureStrip")
        score_container.setFixedHeight(84)
        score_row = QHBoxLayout(score_container)
        score_row.setContentsMargins(6, 5, 6, 5)
        score_row.setSpacing(8)

        self.regime_badge = QLabel("REGIME: -")
        self.regime_badge.setObjectName("RegimeBadge")
        self.regime_badge.setFixedHeight(72)
        self.regime_badge.setMinimumWidth(250)
        self.regime_badge.setMaximumWidth(350)
        self.regime_badge.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )

        self.long_score_card = MiniScoreCard("AI LONG SCORE", "#22c55e")
        self.long_score_card.setFixedHeight(72)
        self.long_score_card.setMinimumWidth(180)

        self.short_score_card = MiniScoreCard("AI SHORT SCORE", "#ef4444")
        self.short_score_card.setFixedHeight(72)
        self.short_score_card.setMinimumWidth(180)

        score_row.addWidget(self.regime_badge, 2)
        score_row.addWidget(self.long_score_card, 1)
        score_row.addWidget(self.short_score_card, 1)
        ll.addWidget(score_container, 0)

        self.market_chart = MarketChart()
        self.market_chart.set_paint_scheduler(self.paint_scheduler)
        self.market_chart.setFixedHeight(390)
        self.market_chart.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        ll.addWidget(self.market_chart, 0)

        self.tf_table = QTableWidget(0, 10)
        self.tf_table.setFixedHeight(130)
        self.tf_table.verticalHeader().setDefaultSectionSize(21)
        self.tf_table.setHorizontalHeaderLabels([
            "TF","CMF","RSI","ADX","Vol","Pha",
            "Spring","Upthrust","L.Entry","S.Entry"
        ])
        self.tf_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.tf_table.verticalHeader().setVisible(False)
        self.tf_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.tf_table.cellClicked.connect(self.select_tf_from_table)
        ll.addWidget(self.tf_table)

        self.story_container = QWidget()
        self.story_container.setFixedHeight(122)
        story_row = QHBoxLayout(self.story_container)
        story_row.setContentsMargins(0, 0, 0, 0)
        story_row.setSpacing(5)

        self.timeline_text = QTextEdit()
        self.timeline_text.setReadOnly(True)
        self.timeline_text.setMinimumHeight(78)
        self.timeline_text.setMaximumHeight(88)

        self.market_story = QTextEdit()
        self.market_story.setReadOnly(True)
        self.market_story.setMinimumHeight(78)
        self.market_story.setMaximumHeight(88)

        self.timeline_panel = self._panel(
            "TIMELINE DIỄN BIẾN", self.timeline_text
        )
        self.market_story_panel = self._panel(
            "MARKET STORY — AI NARRATIVE", self.market_story
        )
        self.timeline_panel.setMinimumHeight(114)
        self.market_story_panel.setMinimumHeight(114)

        story_row.addWidget(self.timeline_panel, 1)
        story_row.addWidget(self.market_story_panel, 1)
        ll.addWidget(self.story_container, 0)

        right = QWidget()
        right.setObjectName("DetailDecisionRail")
        right.setMinimumWidth(330)
        right.setMaximumWidth(390)
        right.setMinimumHeight(900)
        right.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.MinimumExpanding,
        )
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 8, 8, 8)
        rl.setSpacing(9)
        rl.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.final_result_title = QLabel("KẾT QUẢ CUỐI CÙNG: STAND ASIDE")
        self.final_result_title.setObjectName("FinalResultTitle")
        self.final_result_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.final_result_title.setFixedHeight(40)
        self.final_result_title.setWordWrap(False)
        self.final_result_title.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        rl.addWidget(self.final_result_title, 0)

        self.decision_gauge = GaugeWidget("CONFIDENCE SCORE")
        self.decision_gauge.setObjectName("PrimaryConfidenceGauge")
        self.decision_gauge.setFixedHeight(94)
        rl.addWidget(self.decision_gauge, 0)

        self.decision_progress = QProgressBar()
        self.decision_progress.setRange(0, 100)
        self.decision_progress.setValue(0)
        self.decision_progress.setTextVisible(False)
        self.decision_progress.setFixedHeight(12)
        self.decision_progress.setObjectName("DecisionConfidenceProgress")
        self.decision_progress.setProperty("confidenceBand", "critical")
        self.decision_progress.setStyleSheet(
            "QProgressBar {"
            "background:#111827;"
            "border:1px solid #334155;"
            "border-radius:6px;"
            "}"
            "QProgressBar::chunk {"
            "background:#ef4444;"
            "border-radius:5px;"
            "}"
        )
        rl.addWidget(self.decision_progress, 0)

        self.engine_gauge_box = QWidget()
        self.engine_gauge_box.setObjectName("EngineGaugeGrid")
        self.engine_gauge_box.setMinimumHeight(202)
        self.engine_gauge_box.setMaximumHeight(202)
        self.engine_gauge_box.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        engine_gauges = QGridLayout(self.engine_gauge_box)
        engine_gauges.setContentsMargins(8, 8, 8, 8)
        engine_gauges.setHorizontalSpacing(8)
        engine_gauges.setVerticalSpacing(8)
        self.entry_gauge = GaugeWidget("ENTRY", compact=True)
        self.smart_gauge = GaugeWidget("SMART MONEY", compact=True)
        self.wyckoff_gauge = GaugeWidget("WYCKOFF", compact=True)
        self.risk_gauge = GaugeWidget("RISK", inverse=True, compact=True)
        for gauge in (
            self.entry_gauge,
            self.smart_gauge,
            self.wyckoff_gauge,
            self.risk_gauge,
        ):
            gauge.setFixedHeight(90)
            gauge.setMinimumWidth(138)
            gauge.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            gauge.setStyleSheet(
                "GaugeWidget {"
                "background:#0f172a;"
                "border:1px solid #27364f;"
                "border-radius:8px;"
                "}"
            )
        engine_gauges.addWidget(self.entry_gauge, 0, 0)
        engine_gauges.addWidget(self.smart_gauge, 0, 1)
        engine_gauges.addWidget(self.wyckoff_gauge, 1, 0)
        engine_gauges.addWidget(self.risk_gauge, 1, 1)
        engine_gauges.setColumnStretch(0, 1)
        engine_gauges.setColumnStretch(1, 1)
        rl.addWidget(self.engine_gauge_box, 0)

        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMinimumHeight(106)
        self.detail_text.setMaximumHeight(106)
        self.detail_text.setToolTip(
            "Structure Test: xác nhận volume/spread co lại sau Spring hoặc "
            "Upthrust. Sweep Volume State cho biết hấp thụ volume cao, "
            "cạn cung/cầu volume thấp, hoặc chưa xác nhận. "
            "Dynamic Buffer là khoảng đệm thanh lý theo ATR; "
            "Effective Stop đã gồm phí/trượt giá; "
            "Leverage Constraint cho biết stop có đang giới hạn đòn bẩy hay không."
        )
        self.detail_reason_panel = self._panel(
            "LÝ DO & KẾ HOẠCH GIAO DỊCH",
            self.detail_text,
        )
        self.detail_reason_panel.setMinimumHeight(136)
        self.detail_reason_panel.setMaximumHeight(136)
        self.detail_reason_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        rl.addWidget(self.detail_reason_panel, 0)

        plan_box = QFrame()
        plan_box.setObjectName("TradePlanCard")
        plan_box.setFixedHeight(78)
        plan_layout = QHBoxLayout(plan_box)
        plan_layout.setContentsMargins(10, 8, 10, 8)
        self.plan_summary = QLabel("KẾ HOẠCH: Chưa có dữ liệu")
        self.plan_summary.setWordWrap(True)
        self.plan_summary.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.rr_badge = QLabel("R:R -")
        self.rr_badge.setObjectName("RRBadge")
        plan_layout.addWidget(self.plan_summary, 1)
        plan_layout.addWidget(self.rr_badge)
        rl.addWidget(plan_box)

        paper_buttons = QHBoxLayout()
        self.test_long_btn = QPushButton("TEST LONG")
        self.test_short_btn = QPushButton("TEST SHORT")
        self.test_long_btn.setObjectName("TestLongButton")
        self.test_short_btn.setObjectName("TestShortButton")
        self.test_long_btn.clicked.connect(
            lambda: self.create_manual_paper_trade("LONG")
        )
        self.test_short_btn.clicked.connect(
            lambda: self.create_manual_paper_trade("SHORT")
        )
        paper_buttons.addWidget(self.test_long_btn)
        paper_buttons.addWidget(self.test_short_btn)
        rl.addLayout(paper_buttons)

        self.score_explain = QTextEdit()
        self.score_explain.setReadOnly(True)
        self.score_explain.setMinimumHeight(90)
        self.score_explain.setMaximumHeight(90)
        self.score_explain_panel = self._panel(
            "GIẢI THÍCH CHỈ SỐ & ENTRY SCORE",
            self.score_explain,
        )
        self.score_explain_panel.setMinimumHeight(120)
        self.score_explain_panel.setMaximumHeight(120)
        self.score_explain_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        rl.addWidget(self.score_explain_panel, 0)

        self.ai_voice = QLabel(
            "AI: Chưa có dữ liệu. Hãy chọn coin để nhận hướng dẫn hành động."
        )
        self.ai_voice.setWordWrap(True)
        self.ai_voice.setObjectName("AIVoice")
        self.ai_voice.setMinimumHeight(52)
        self.ai_voice.setMaximumHeight(52)
        self.ai_voice_panel = self._panel("AI VOICE", self.ai_voice)
        self.ai_voice_panel.setMinimumHeight(82)
        self.ai_voice_panel.setMaximumHeight(82)
        self.ai_voice_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        rl.addWidget(self.ai_voice_panel, 0)
        rl.addStretch(1)

        self.detail_left_panel = left
        self.detail_right_panel = right
        splitter.addWidget(left)
        splitter.addWidget(right)
        # Approved visual ratio: chart workspace dominates; decision rail
        # remains readable but no longer consumes one third of the screen.
        splitter.setStretchFactor(0, 75)
        splitter.setStretchFactor(1, 25)
        splitter.setSizes([1110, 360])
        outer.addWidget(splitter)

        detail_scroll.setWidget(detail_content)
        page_layout.addWidget(detail_scroll)
        self.detail_scroll_area = detail_scroll

        self.detail_widget = detail
        self.tabs.addTab(detail, "Phân tích chi tiết")
        self._apply_detail_tooltips()

    def update_chart_overlays(self):
        if not hasattr(self, "market_chart"):
            return
        self.market_chart.set_candidate_visibility(
            self.long_zone_btn.isChecked(),
            self.short_zone_btn.isChecked(),
        )
        self.market_chart.set_signal_markers_visible(
            self.signal_marker_btn.isChecked()
        )
        self.long_zone_btn.setText(
            "✓ Hiện Long" if self.long_zone_btn.isChecked() else "Hiện Long"
        )
        self.short_zone_btn.setText(
            "✓ Hiện Short" if self.short_zone_btn.isChecked() else "Hiện Short"
        )
        self.signal_marker_btn.setText(
            "✓ Tín hiệu" if self.signal_marker_btn.isChecked()
            else "Hiện tín hiệu"
        )

    def change_chart_timeframe(self, timeframe):
        if self.current_analysis is None:
            return
        analysis = self.current_analysis.timeframes.get(timeframe)
        if analysis is not None:
            self.market_chart.set_analysis(
                analysis,
                timeframe,
                self.current_analysis.trade_plan,
                self.current_analysis.direction,
                self.current_analysis,
            )
            self.update_score_explanation(timeframe)
            self._update_pro_panels(timeframe)

    def select_tf_from_table(self, row, column):
        item = self.tf_table.item(row, 0)
        if item is None:
            return
        timeframe = item.text()
        index = self.tf_selector.findText(timeframe)
        if index >= 0:
            self.tf_selector.setCurrentIndex(index)

    @staticmethod
    def _entry_label(score):
        if score < 30:
            return "KHÔNG NÊN VÀO"
        if score < 50:
            return "QUAN SÁT"
        if score < 70:
            return "CHUẨN BỊ / SETUP"
        if score < 85:
            return "ĐIỂM VÀO TỐT"
        return "ĐIỂM VÀO RẤT ĐẸP"

    def update_score_explanation(self, timeframe):
        if self.current_analysis is None:
            return
        r = self.current_analysis.timeframes[timeframe]
        direction_note = (
            "L.Entry đánh giá chất lượng vị trí vào LONG hiện tại; "
            "S.Entry đánh giá chất lượng vị trí vào SHORT. "
            "Đây không phải xác suất thắng."
        )
        money_note = (
            "CMF dương: dòng tiền nghiêng vào; CMF âm: dòng tiền nghiêng ra."
        )
        rsi_note = (
            "RSI dưới 30: quá bán; trên 70: quá mua. "
            "Không nên dùng RSI đơn lẻ để vào lệnh."
        )
        self.score_explain.setPlainText(
            f"GIẢI THÍCH KHUNG {timeframe}\n"
            f"L.Entry {r.long_entry_score:.0f}/100 — "
            f"{self._entry_label(r.long_entry_score)}\n"
            f"S.Entry {r.short_entry_score:.0f}/100 — "
            f"{self._entry_label(r.short_entry_score)}\n\n"
            f"{direction_note}\n"
            f"{money_note}\n"
            f"{rsi_note}\n\n"
            f"Hiện tại: CMF {r.cmf:+.3f}, RSI {r.rsi:.1f}, "
            f"ADX {r.adx:.1f}, Volume x{r.relative_volume:.2f}, "
            f"Pha {r.market_phase}."
        )


    def _canonical_symbol_from_display(self, value):
        text = str(value or "").strip().upper()
        if not text:
            return None
        if ":" in text:
            return text
        return f"{text}:USDT"

    def _select_symbol_from_table(
        self,
        table,
        *,
        symbol_column: int,
        source: str,
    ) -> None:
        row = table.currentRow()
        if row < 0:
            return
        item = table.item(row, symbol_column)
        if item is None:
            return
        symbol = self._canonical_symbol_from_display(item.text())
        if not symbol:
            return
        analysis = self.results.get(symbol)
        if analysis is not None:
            self._set_selected_analysis_context(
                analysis,
                source=source,
                sync_main_table=True,
            )
        else:
            self.selection_state.select(
                symbol,
                timeframe=self.selection_state.timeframe,
                source=source,
            )
            if hasattr(self, "current_coin_badge"):
                self.current_coin_badge.setText(
                    f"CURRENT: {symbol.replace(':USDT', '')}"
                )
            if hasattr(self, "header_symbol"):
                self.header_symbol.blockSignals(True)
                self.header_symbol.setCurrentText(symbol.replace(":USDT", ""))
                self.header_symbol.blockSignals(False)

    def _select_history_symbol(self) -> None:
        self._select_symbol_from_table(
            self.history_table,
            symbol_column=1,
            source="signal_history",
        )

    def _select_paper_symbol(self) -> None:
        self._select_symbol_from_table(
            self.paper_table,
            symbol_column=3,
            source="paper_trade",
        )

    def _restore_table_symbol_selection(
        self,
        table,
        *,
        symbol_column: int,
    ) -> bool:
        symbol = self.selection_state.symbol
        if not symbol:
            return False
        display = symbol.replace(":USDT", "")
        for row in range(table.rowCount()):
            item = table.item(row, symbol_column)
            if item is not None and item.text().strip().upper() == display:
                table.blockSignals(True)
                table.selectRow(row)
                item_to_show = table.item(row, symbol_column)
                if item_to_show is not None:
                    table.scrollToItem(item_to_show, QAbstractItemView.ScrollHint.PositionAtCenter)
                table.blockSignals(False)
                return True
        return False

    def _analysis_for_selected_symbol(self):
        """Return the cached analysis that matches the shared UI selection."""
        symbol = getattr(self.selection_state, "symbol", None)
        if not symbol:
            return None
        analysis = self.results.get(symbol)
        if analysis is not None:
            return analysis
        display = symbol.replace(":USDT", "")
        for key, candidate in self.results.items():
            if str(key).replace(":USDT", "").upper() == display.upper():
                return candidate
        return None

    @staticmethod
    def _smart_entry_level(value: float) -> tuple[str, str]:
        value = max(0.0, min(100.0, float(value)))
        if value >= 70:
            return "MẠNH", "#22c55e"
        if value >= 45:
            return "TRUNG BÌNH", "#facc15"
        return "YẾU", "#ef4444"

    def _set_smart_metric(self, key: str, value: float) -> None:
        bar = getattr(self, f"smart_metric_{key}_bar", None)
        label = getattr(self, f"smart_metric_{key}_value", None)
        if bar is None or label is None:
            return
        numeric = max(0, min(100, int(round(float(value)))))
        level, color = self._smart_entry_level(numeric)
        bar.setValue(numeric)
        bar.setFormat(f"{numeric}/100")
        bar.setStyleSheet(
            "QProgressBar{border:1px solid #334155;border-radius:5px;"
            "background:#0f172a;text-align:center;color:#e2e8f0;}"
            f"QProgressBar::chunk{{background:{color};border-radius:4px;}}"
        )
        label.setText(f"{level} · {numeric}")
        label.setStyleSheet(f"color:{color};font-weight:700;")

    def _render_smart_entry_for_analysis(self, analysis) -> bool:
        """Render the Smart Entry dashboard without navigating or repainting other tabs."""
        if analysis is None:
            return False
        required = ("smart_title", "smart_summary", "smart_text", "smart_score_bar")
        if not all(hasattr(self, name) for name in required):
            return False
        symbol = analysis.symbol
        se = analysis.smart_entry
        plain_view = self.plain_language_presenter.build(analysis)

        loi = float(se.long_opportunity_index)
        soi = float(se.short_opportunity_index)
        smp = float(se.smart_money_probability)
        dominant = "LONG" if loi > soi else "SHORT" if soi > loi else "NEUTRAL"
        overall = max(loi, soi)
        status = "READY" if overall >= 70 else "WATCH" if overall >= 50 else "WAIT"
        _, score_color = self._smart_entry_level(overall)

        self.smart_title.setText(f"<h3>{symbol.replace(':USDT','')} — {se.state}</h3>")
        self.smart_score_label.setText(f"SMART ENTRY SCORE · {dominant} · {status}")
        self.smart_score_value.setText(f"{overall:.0f}/100")
        self.smart_score_value.setStyleSheet(f"color:{score_color};font-size:24px;font-weight:800;")
        self.smart_score_bar.setValue(int(round(overall)))
        self.smart_score_bar.setFormat(f"{status} · {overall:.0f}/100")
        self.smart_score_bar.setStyleSheet(
            "QProgressBar{border:1px solid #334155;border-radius:6px;"
            "background:#0f172a;text-align:center;color:#e2e8f0;font-weight:700;}"
            f"QProgressBar::chunk{{background:{score_color};border-radius:5px;}}"
        )

        metrics = {
            "loi": loi, "soi": soi, "smp": smp,
            "panic": se.panic_flush_score, "weak": se.weak_hand_score,
            "absorption": se.absorption_score, "fake_down": se.fake_breakdown_score,
            "fake_up": se.fake_breakout_score,
        }
        for key, value in metrics.items():
            self._set_smart_metric(key, value)

        long_p = max(0.0, loi)
        short_p = max(0.0, soi)
        neutral_p = max(0.0, 100.0 - max(long_p, short_p))
        total = long_p + short_p + neutral_p or 1.0
        long_p, short_p, neutral_p = (100*x/total for x in (long_p, short_p, neutral_p))
        self.smart_probability.setText(
            f"LONG  {long_p:.0f}%    |    SHORT  {short_p:.0f}%    |    NEUTRAL  {neutral_p:.0f}%"
        )

        divergence = str(se.cmf_rsi_divergence or "NONE")
        trigger_rows = [
            ("Long opportunity ≥ 60", loi >= 60),
            ("Short opportunity ≥ 60", soi >= 60),
            ("Smart-money probability ≥ 55", smp >= 55),
            ("Absorption ≥ 45", float(se.absorption_score) >= 45),
            ("Panic/weak-hand confirmation", max(float(se.panic_flush_score), float(se.weak_hand_score)) >= 45),
            ("CMF/RSI divergence available", divergence.upper() not in {"", "NONE", "N/A"}),
        ]
        self.smart_trigger_text.setText("<br>".join(
            f"<span style='color:{'#22c55e' if ok else '#ef4444'};font-weight:700'>"
            f"{'✓' if ok else '✗'}</span> {name}" for name, ok in trigger_rows
        ))
        self.smart_timeline.setText(
            f"CURRENT: {se.state}   →   BIAS: {dominant}   →   NEXT: "
            + ("ENTRY READY" if status == "READY" else "WAIT FOR CONFIRMATION")
        )

        self.smart_summary.setHtml(self._plain_view_html(plain_view, "Điểm vào dễ hiểu"))
        self.smart_text.setPlainText(
            f"SMART ENTRY STATE\n{se.state}\n\n"
            f"LOI: {loi:.0f}/100\nSOI: {soi:.0f}/100\nSMP: {smp:.0f}/100\n\n"
            f"PANIC FLUSH: {se.panic_flush_score:.0f}/100\n"
            f"WEAK-HAND: {se.weak_hand_score:.0f}/100\n"
            f"ABSORPTION: {se.absorption_score:.0f}/100\n"
            f"FAKE BREAKDOWN: {se.fake_breakdown_score:.0f}/100\n"
            f"FAKE BREAKOUT: {se.fake_breakout_score:.0f}/100\n"
            f"CMF-RSI: {divergence}\n\n"
            f"GIẢI THÍCH\n- " + "\n- ".join(se.explanation)
            + ("\n\nAI NARRATIVE · OBSERVE ONLY\n- " + "\n- ".join(
                getattr(getattr(analysis, "explainable_narrative", None), "smart_entry_story", ())
            ) if getattr(analysis, "explainable_narrative", None) else "")
            + ("\n\nCẦN XÁC NHẬN TIẾP\n- " + "\n- ".join(
                getattr(analysis, "explainable_next_confirmation", ())
            ) if getattr(analysis, "explainable_next_confirmation", ()) else "")
        )
        return True

    def _render_structure_for_analysis(self, analysis) -> bool:
        """Render Liquidity/Wyckoff from the shared selection without changing tabs."""
        if analysis is None or not all(hasattr(self, n) for n in ("structure_title", "structure_text")):
            return False
        symbol = analysis.symbol.replace(":USDT", "")
        sdata = analysis.structure
        self.structure_title.setText(f"<h3>{symbol} — Liquidity & Wyckoff</h3>")
        self.structure_text.setPlainText(
            f"MỐC THANH KHOẢN\n"
            f"Đỉnh/đáy ngày: {sdata.daily_high:.8g} / {sdata.daily_low:.8g}\n"
            f"Đỉnh/đáy tuần: {sdata.weekly_high:.8g} / {sdata.weekly_low:.8g}\n"
            f"Đỉnh/đáy tháng: {sdata.monthly_high:.8g} / {sdata.monthly_low:.8g}\n\n"
            f"SỰ KIỆN THANH KHOẢN\n{sdata.liquidity_event}\n"
            f"Liquidity Score: {sdata.liquidity_score:.0f}/100\n"
            f"Sweep Volume State: {getattr(sdata, 'sweep_volume_state', 'NONE')}\n\n"
            f"WYCKOFF / EFFORT-vs-RESULT\n{sdata.wyckoff_signal}\n"
            f"{sdata.effort_result}\n"
            f"Wyckoff Score: {sdata.wyckoff_score:.0f}/100\n"
            f"Structure Test: {getattr(sdata, 'wyckoff_test', 'NONE')}\n"
            f"Test Score: {getattr(sdata, 'wyckoff_test_score', 0.0):.0f}/100\n\n"
            f"CẢNH BÁO\n- "
            + ("\n- ".join(sdata.warnings) if sdata.warnings else "Chưa có cảnh báo nổi bật")
        )
        return True

    def _render_decision_core_for_analysis(self, analysis) -> bool:
        """Render Decision Core from the shared selection without changing tabs."""
        if analysis is None or not all(hasattr(self, n) for n in ("core_title", "core_summary", "core_text")):
            return False
        plain_view = self.plain_language_presenter.build(analysis)
        symbol = analysis.symbol.replace(":USDT", "")
        self.core_title.setText(f"<h3>{symbol} — {analysis.action}</h3>")
        self.core_summary.setHtml(self._plain_view_html(plain_view, "Kết luận giao dịch"))
        self.core_text.setPlainText(
            f"QUYẾT ĐỊNH\n{analysis.action}\n\n"
            f"THỜI ĐIỂM\n{analysis.timing}\n\n"
            f"MARKET REGIME\n{analysis.regime.regime} | Direction {analysis.regime.direction} | "
            f"Strength {analysis.regime.strength:.0f}/100 | Volatility {analysis.regime.volatility_state}\n"
            f"{analysis.regime.description}\n\n"
            f"MULTI-TIMEFRAME\n{analysis.alignment.label}\n"
            f"Long {analysis.alignment.long_score:.0f}/100 | Short {analysis.alignment.short_score:.0f}/100\n"
            f"Đồng thuận: {', '.join(analysis.alignment.aligned_timeframes) or '-'}\n"
            f"Mâu thuẫn: {', '.join(analysis.alignment.conflicting_timeframes) or '-'}\n\n"
            f"RISK ENGINE\nRisk Score: {analysis.risk.risk_score:.0f}/100 — {analysis.risk.risk_level}\n"
            f"Position size factor: x{analysis.risk.size_factor:.2f}\n"
            f"Leverage: {analysis.risk.leverage:.1f}x\n"
            f"Liquidation safe: {'YES' if analysis.risk.liquidation_safe else 'NO'}"
        )
        return True

    def _current_cycle_for_token_telemetry(self) -> int:
        return int(getattr(self, "_scan_cycle_index", getattr(self, "scan_cycle_index", 0)) or 0)

    def _set_current_analysis_reference(self, analysis, *, mutation_site: str) -> None:
        previous = getattr(self, "current_analysis", None)
        cycle_index = self._current_cycle_for_token_telemetry()
        COIN_ANALYSIS_TOKENS.owner_transition(
            previous, analysis, "MainWindow.current_analysis",
            cycle_index=cycle_index, mutation_site=mutation_site,
        )
        self.current_analysis = analysis
        COIN_ANALYSIS_TOKENS.qobject_owner_snapshot(
            analysis, "MainWindow.current_analysis", self, cycle_index=cycle_index,
            mutation_site=f"{mutation_site}:MainWindow",
        ) if analysis is not None else None

    def _set_truth_pending_reference(self, analysis, *, mutation_site: str) -> None:
        previous = getattr(self, "_truth_dashboard_pending_analysis", None)
        cycle_index = self._current_cycle_for_token_telemetry()
        COIN_ANALYSIS_TOKENS.owner_transition(
            previous, analysis, "MainWindow._truth_dashboard_pending_analysis",
            cycle_index=cycle_index, mutation_site=mutation_site,
        )
        self._truth_dashboard_pending_analysis = analysis

    def _set_truth_dashboard_analysis(self, analysis, *, mutation_site: str) -> None:
        dashboard = getattr(self, "truth_dashboard", None)
        if dashboard is None:
            return
        previous = getattr(dashboard, "_last_analysis", None)
        cycle_index = self._current_cycle_for_token_telemetry()
        COIN_ANALYSIS_TOKENS.owner_transition(
            previous, analysis, "TruthDashboard._last_analysis",
            cycle_index=cycle_index, mutation_site=mutation_site,
        )
        dashboard.set_analysis(analysis)
        COIN_ANALYSIS_TOKENS.qobject_owner_snapshot(
            analysis, "TruthDashboard._last_analysis", dashboard, cycle_index=cycle_index,
            mutation_site=f"{mutation_site}:TruthDashboard",
        )

    def _schedule_truth_dashboard_seed(self, analysis, *, mutation_site: str) -> None:
        cycle_index = self._current_cycle_for_token_telemetry()
        owner_path = "QTimer.singleShot.truth_dashboard_seed_closure"
        COIN_ANALYSIS_TOKENS.owner_enter(analysis, owner_path, cycle_index=cycle_index, mutation_site=f"{mutation_site}:schedule")
        def invoke(item=analysis):
            try:
                self._seed_truth_dashboard_once(item)
            finally:
                COIN_ANALYSIS_TOKENS.owner_release(
                    item, owner_path, cycle_index=self._current_cycle_for_token_telemetry(),
                    mutation_site=f"{mutation_site}:callback_complete",
                )
        QTimer.singleShot(0, invoke)

    def _sync_views_to_selection(self) -> None:
        """Project the shared selection into every tab without signal loops."""
        symbol = self.selection_state.symbol
        if not symbol:
            return

        if hasattr(self, "current_coin_badge"):
            self.current_coin_badge.setText(
                f"CURRENT: {symbol.replace(':USDT', '')}"
            )

        if hasattr(self, "history_table"):
            self._restore_table_symbol_selection(
                self.history_table, symbol_column=1
            )
        if hasattr(self, "paper_table"):
            self._restore_table_symbol_selection(
                self.paper_table, symbol_column=3
            )
        if hasattr(self, "micro_table"):
            restored = self._restore_table_symbol_selection(
                self.micro_table, symbol_column=0
            )
            if restored:
                row = self.micro_table.currentRow()
                rows = getattr(self, "_micro_analysis_rows", ())
                if 0 <= row < len(rows):
                    self._render_microstructure_analysis(rows[row])

        analysis = self._analysis_for_selected_symbol()
        if analysis is not None:
            self._set_current_analysis_reference(analysis, mutation_site="_sync_views_to_selection")
            try:
                self._render_smart_entry_for_analysis(analysis)
            except Exception:
                logger.exception("UI_SELECTION_PROJECTION_FAILED:%s", "SMART_ENTRY")
            try:
                self._render_decision_core_for_analysis(analysis)
            except Exception:
                logger.exception("UI_SELECTION_PROJECTION_FAILED:%s", "DECISION_CORE")
            try:
                self._render_structure_for_analysis(analysis)
            except Exception:
                logger.exception("UI_SELECTION_PROJECTION_FAILED:%s", "LIQUIDITY_WYCKOFF")

    @_audit_gui_callback("tab_changed")
    def _on_tab_changed(self, index: int) -> None:
        """Restore shared context and lazily refresh read-only diagnostics."""
        self._sync_views_to_selection()
        if hasattr(self, "market_analysis_tabs"):
            self._on_market_analysis_tab_changed(
                self.market_analysis_tabs.currentIndex()
            )
        dashboard = getattr(self, "statistical_diagnostics_dashboard", None)
        if dashboard is not None and self.tabs.widget(index) is dashboard:
            dashboard.refresh()
        ledger = getattr(self, "integrity_incident_ledger", None)
        if ledger is not None and self.tabs.widget(index) is ledger:
            ledger.load_history()
        truth = getattr(self, "truth_dashboard", None)
        if truth is not None and self._is_truth_workspace_visible():
            analysis = (
                self.current_analysis
                or getattr(self, "_truth_dashboard_pending_analysis", None)
            )
            if analysis is not None and not getattr(
                self, "_truth_dashboard_seed_pending", False
            ):
                self._truth_dashboard_seed_pending = True
                self._schedule_truth_dashboard_seed(
                    analysis, mutation_site="_on_tab_changed"
                )

    def select_symbol_from_header(self, symbol_text):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.text() == symbol_text:
                self.table.selectRow(row)
                self.tabs.setCurrentIndex(1)
                return

    @staticmethod
    def _set_label_text_if_changed(widget, value) -> bool:
        rendered = str(value)
        if widget.text() == rendered:
            return False
        widget.setText(rendered)
        return True

    @staticmethod
    def _set_plain_text_if_changed(widget, value) -> bool:
        rendered = str(value)
        if widget.toPlainText() == rendered:
            return False
        widget.setPlainText(rendered)
        return True

    @staticmethod
    def _set_html_if_changed(widget, value) -> bool:
        rendered = str(value)
        if widget.property("_dvs_last_html") == rendered:
            return False
        widget.setProperty("_dvs_last_html", rendered)
        widget.setHtml(rendered)
        return True

    @staticmethod
    def _set_tooltip_if_changed(widget, value) -> bool:
        rendered = str(value)
        if widget.toolTip() == rendered:
            return False
        widget.setToolTip(rendered)
        return True

    @staticmethod
    def _set_dynamic_property_if_changed(widget, name: str, value) -> bool:
        if widget.property(name) == value:
            return False
        widget.setProperty(name, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()
        return True

    @staticmethod
    def _set_table_item_value(
        table,
        row: int,
        column: int,
        text_value: str,
        foreground=None,
    ) -> bool:
        rendered = str(text_value)
        item = table.item(row, column)
        if item is None:
            item = QTableWidgetItem(rendered)
            table.setItem(row, column, item)
            changed = True
        else:
            changed = item.text() != rendered
            if changed:
                item.setText(rendered)
        if foreground is not None and item.foreground().color() != foreground:
            item.setForeground(foreground)
            changed = True
        return changed

    def _market_story_text(self, a, timeframe):
        r = a.timeframes[timeframe]
        story = [
            f"{a.symbol.replace(':USDT','')} đang ở regime {a.regime.regime}, "
            f"nghiêng {a.regime.direction}.",
            f"Khung {timeframe}: CMF {r.cmf:+.3f}, RSI {r.rsi:.1f}, "
            f"ADX {r.adx:.1f}, volume x{r.relative_volume:.2f}.",
        ]
        if "Không có" not in a.structure.liquidity_event:
            story.append(f"Thanh khoản: {a.structure.liquidity_event}.")
        sweep_state = getattr(
            a.structure, "sweep_volume_state", "NONE"
        )
        if sweep_state != "NONE":
            story.append(
                f"Xác nhận volume của sweep: {sweep_state}."
            )
        if "nổi bật" not in a.structure.wyckoff_signal:
            story.append(f"Wyckoff: {a.structure.wyckoff_signal}.")
        structure_test = getattr(
            a.structure, "wyckoff_test", "NONE"
        )
        if structure_test != "NONE":
            story.append(
                f"{structure_test}, score "
                f"{getattr(a.structure, 'wyckoff_test_score', 0.0):.0f}/100."
            )
        story.append(
            f"Smart Entry {a.smart_entry.state}; LOI/SOI "
            f"{a.smart_entry.long_opportunity_index:.0f}/"
            f"{a.smart_entry.short_opportunity_index:.0f}."
        )
        story.append(f"Kết luận: {a.action}. {a.timing}")
        return " ".join(story)

    def _timeline_text_for(self, a, timeframe):
        events = []
        if "Không có" not in a.structure.liquidity_event:
            events.append(f"💧 {a.structure.liquidity_event}")
        sweep_state = getattr(
            a.structure, "sweep_volume_state", "NONE"
        )
        if sweep_state == "UNCONFIRMED":
            events.append("⚠ Sweep chưa được volume xác nhận")
        elif sweep_state == "LOW_VOLUME_EXHAUSTION":
            events.append("🫧 Sweep volume thấp: cạn cung/cầu")
        elif sweep_state == "HIGH_VOLUME_ABSORPTION":
            events.append("💥 Sweep volume cao: hấp thụ")
        structure_test = getattr(
            a.structure, "wyckoff_test", "NONE"
        )
        if structure_test != "NONE":
            events.append(f"🧪 {structure_test}")
        if a.timeframes[timeframe].spring:
            events.append("🟢 Spring")
        if a.timeframes[timeframe].upthrust:
            events.append("🔴 Upthrust")
        if a.smart_entry.weak_hand_score >= 60:
            events.append(f"🟣 Weak-hand {a.smart_entry.weak_hand_score:.0f}")
        if a.smart_entry.absorption_score >= 60:
            events.append(f"🟢 Absorption {a.smart_entry.absorption_score:.0f}")
        if abs(a.snapshot.oi_change_15m_pct) >= 0.5:
            events.append(f"⚡ OI15m {a.snapshot.oi_change_15m_pct:+.2f}%")
        events.append(f"⏳ {a.entry_status.value} · {a.action}")
        return "  →  ".join(events)

    def _update_pro_panels(self, timeframe="15m"):
        # RC6.12B-r2 (measurement only): one begin/end record per batch
        # call, not per gauge. try/finally guarantees the end marker fires
        # even on the early "no analysis yet" return below.
        _batch_started_ns = time.monotonic_ns()
        _batch_seq = _next_selection_batch_sequence()
        _rate = _pro_panel_batch_counts_and_record(_batch_started_ns)
        _freq_write(
            _PRO_PANEL_FORENSICS_PATH,
            "pro_panel_update_begin",
            batch_sequence=_batch_seq,
            timeframe=timeframe,
            gauge_count=5,
            **_rate,
        )
        _completed = False
        try:
            a = self.current_analysis
            if a is None:
                return
            _completed = True
            self.long_score_card.set_score(a.long_entry_score)
            self.short_score_card.set_score(a.short_entry_score)

            direction_score = (
                a.long_entry_score if a.direction == "LONG"
                else a.short_entry_score
            )

            # Single source of truth:
            # DecisionEngine.combine() owns the confidence formula.
            # The UI only renders CoinAnalysis.confidence_score.
            decision_score = max(
            0.0,
            min(100.0, float(a.confidence_score)),
            )

            if "READY" in a.action:
                final_state = a.action
            elif "CHUẨN BỊ" in a.action:
                final_state = a.action
            elif a.direction == "LONG" and direction_score >= 45:
                final_state = "LONG WATCH"
            elif a.direction == "SHORT" and direction_score >= 45:
                final_state = "SHORT WATCH"
            else:
                final_state = "STAND ASIDE"

            self._set_label_text_if_changed(
                self.final_result_title,
                f"KẾT QUẢ CUỐI CÙNG: {final_state}",
            )
            self._set_dynamic_property_if_changed(
                self.final_result_title,
                "decisionState",
                "long" if "LONG" in final_state
                else "short" if "SHORT" in final_state
                else "neutral",
            )

            self.decision_gauge.set_value(
                decision_score,
                f"CONFIDENCE · {final_state}"
            )
            progress_value = int(round(decision_score))
            if self.decision_progress.value() != progress_value:
                self.decision_progress.setValue(progress_value)
            progress_band = (
                "critical" if progress_value < 35
                else "watch" if progress_value < 60
                else "good" if progress_value < 80
                else "strong"
            )
            if (
                self.decision_progress.property("confidenceBand")
                != progress_band
            ):
                self.decision_progress.setProperty(
                    "confidenceBand",
                    progress_band,
                )
                progress_color = {
                    "critical": "#ef4444",
                    "watch": "#f59e0b",
                    "good": "#3b82f6",
                    "strong": "#22c55e",
                }[progress_band]
                self.decision_progress.setStyleSheet(
                    "QProgressBar {"
                    "background:#111827;"
                    "border:1px solid #334155;"
                    "border-radius:6px;"
                    "}"
                    "QProgressBar::chunk {"
                    f"background:{progress_color};"
                    "border-radius:5px;"
                    "}"
                )
            reason_preview = "\n".join(
                f"• {reason}"
                for reason in tuple(a.reasons)[:4]
            )
            self._set_tooltip_if_changed(
                self.decision_gauge,
                "Confidence Score từ DecisionEngine.combine()\n"
                f"Giá trị: {decision_score:.1f}/100\n"
                f"Hướng: {a.direction}\n"
                f"Trạng thái: {a.entry_status.value}\n"
                f"Maturity: {a.trend_maturity_score:.1f}/100 · "
                f"{a.trend_lifecycle}\n\n"
                f"{reason_preview}",
            )
            self.entry_gauge.set_value(
                direction_score,
                "LONG ENTRY" if a.direction == "LONG" else "SHORT ENTRY"
            )
            self.smart_gauge.set_value(
                a.smart_entry.smart_money_probability,
                a.smart_entry.state
            )
            self.wyckoff_gauge.set_value(
                a.structure.wyckoff_score,
                a.structure.wyckoff_signal
            )
            self.risk_gauge.set_value(
                a.risk.risk_score,
                a.risk.risk_level
            )

            self._set_label_text_if_changed(
                self.regime_badge,
                f"REGIME: {a.regime.regime} · {a.regime.direction}\n"
                f"MATURITY: {a.trend_maturity_score:.0f}/100 · "
                f"{a.trend_lifecycle}",
            )
            strength = (
                a.long_trend_score
                if a.direction == "LONG"
                else a.short_trend_score
            )
            self._set_tooltip_if_changed(
                self.regime_badge,
                f"Strength {strength:.0f} · Maturity "
                f"{a.trend_maturity_score:.0f}\n"
                f"{a.trend_lifecycle} · "
                f"15m/1h {a.maturity_15m:.0f}/{a.maturity_1h:.0f}",
            )
            self._set_plain_text_if_changed(
                self.timeline_text,
                self._timeline_text_for(a, timeframe),
            )
            self._set_plain_text_if_changed(
                self.market_story,
                self._market_story_text(a, timeframe),
            )
            p = a.trade_plan
            self._set_label_text_if_changed(
                self.plan_summary,
                f"KẾ HOẠCH {p.direction}\n"
                f"Entry {p.entry_low:.8g} – {p.entry_high:.8g}\n"
                f"Invalid {p.invalidation:.8g} · TP1 {p.tp1:.8g} · TP2 {p.tp2:.8g}",
            )
            self._set_label_text_if_changed(
                self.rr_badge,
                f"R:R {p.rr_to_tp2:.2f}",
            )
            if final_state == "STAND ASIDE":
                coach = (
                    "AI: ĐỨNG NGOÀI. Các engine chưa tạo đủ lợi thế thống nhất. "
                    "Chỉ quan sát và chờ tín hiệu mới."
                )
            elif "CHUẨN BỊ" in a.action:
                coach = (
                    f"AI: {a.action}. Chờ nến {timeframe} đóng xác nhận; "
                    "không đuổi giá ngoài Entry Zone."
                )
            elif "READY" in a.action:
                coach = (
                    f"AI: {a.action}. Ưu tiên quản trị rủi ro, "
                    f"R:R đến TP2 khoảng {p.rr_to_tp2:.2f}."
                )
            else:
                coach = f"AI: {a.timing}"
            self._set_label_text_if_changed(self.ai_voice, coach)
        finally:
            _freq_write(
                _PRO_PANEL_FORENSICS_PATH,
                "pro_panel_update_end",
                batch_sequence=_batch_seq,
                timeframe=timeframe,
                gauge_count=5,
                values_changed_count=(5 if _completed else 0),
                duration_ms=round((time.monotonic_ns() - _batch_started_ns) / 1_000_000.0, 3),
            )



    def _build_backtest_tab(self):
        tab = QWidget()
        root = QVBoxLayout(tab)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(7)

        top = QHBoxLayout()
        title = QLabel("<h2>Backtest & Learning Center</h2>")
        refresh = QPushButton("Làm mới phân tích")
        refresh.clicked.connect(self.refresh_learning_center)
        self.quantum_run_btn = QPushButton("Chạy Quantum Lab")
        self.quantum_run_btn.clicked.connect(self.run_quantum_optimizer)
        self.quantum_apply_btn = QPushButton("Apply to SHADOW")
        self.quantum_apply_btn.setEnabled(False)
        self.quantum_apply_btn.clicked.connect(self.apply_quantum_shadow)
        top.addWidget(title)
        top.addStretch()
        top.addWidget(self.quantum_run_btn)
        top.addWidget(self.quantum_apply_btn)
        top.addWidget(refresh)
        root.addLayout(top)

        summary_row = QHBoxLayout()
        self.learn_total = MetricCard("LỆNH ĐÃ ĐÓNG", "0", "Paper Trade")
        self.learn_wr = MetricCard("WIN RATE", "0%", "Chưa đủ mẫu")
        self.learn_avg_r = MetricCard("AVERAGE R", "+0.00", "Expectancy")
        self.learn_pf = MetricCard("PROFIT FACTOR", "0.00", "Tổng lợi nhuận / lỗ")
        self.learn_long_short = MetricCard("LONG / SHORT WR", "0 / 0", "Theo hướng")
        for card in (
            self.learn_total,
            self.learn_wr,
            self.learn_avg_r,
            self.learn_pf,
            self.learn_long_short,
        ):
            summary_row.addWidget(card)
        root.addLayout(summary_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_layout.addWidget(QLabel("<b>HIỆU SUẤT THEO SETUP</b>"))
        self.setup_perf_table = QTableWidget(0, 7)
        self.setup_perf_table.setHorizontalHeaderLabels([
            "Setup", "Trades", "Closed", "Win Rate", "Avg R", "PF", "Độ tin cậy"
        ])
        self.setup_perf_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.setup_perf_table.verticalHeader().setVisible(False)
        self.setup_perf_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.setup_perf_table.horizontalHeader().setStretchLastSection(True)
        left_layout.addWidget(self.setup_perf_table)

        left_layout.addWidget(QLabel("<b>HIỆU CHỈNH CONFIDENCE</b>"))
        self.calibration_table = QTableWidget(0, 5)
        self.calibration_table.setHorizontalHeaderLabels([
            "Khoảng", "Mẫu", "Confidence TB", "Win Rate thực", "Sai lệch"
        ])
        self.calibration_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.calibration_table.verticalHeader().setVisible(False)
        self.calibration_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        left_layout.addWidget(self.calibration_table)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        right_layout.addWidget(QLabel("<b>SIGNAL AVAILABILITY MONITOR</b>"))
        self.strictness_label = QLabel("CHƯA CÓ DỮ LIỆU")
        self.strictness_label.setObjectName("FinalResultTitle")
        self.strictness_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.strictness_label.setMinimumHeight(48)
        right_layout.addWidget(self.strictness_label)

        self.threshold_text = QTextEdit()
        self.threshold_text.setReadOnly(True)
        self.threshold_text.setMaximumHeight(190)
        right_layout.addWidget(self.threshold_text)

        right_layout.addWidget(QLabel("<b>ĐỀ XUẤT TRỌNG SỐ — CHỈ THAM KHẢO</b>"))
        self.weight_table = QTableWidget(0, 6)
        self.weight_table.setHorizontalHeaderLabels([
            "Setup", "Mẫu", "Win Rate", "Avg R", "Hành động", "Δ"
        ])
        self.weight_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.weight_table.verticalHeader().setVisible(False)
        self.weight_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.weight_table.horizontalHeader().setStretchLastSection(True)
        right_layout.addWidget(self.weight_table)

        right_layout.addWidget(QLabel("<b>QUANTUM LEARNING LAB</b>"))
        self.learning_quantum_readiness = QuantumReadinessWidget("QUANTUM READINESS")
        right_layout.addWidget(self.learning_quantum_readiness)
        self.quantum_text = QTextEdit()
        self.quantum_text.setReadOnly(True)
        self.quantum_text.setMaximumHeight(180)
        self.quantum_text.setPlainText(
            "Chưa chạy. Quantum-inspired optimizer dùng Genetic Algorithm "
            "và kiểm định train/validation theo thời gian."
        )
        right_layout.addWidget(self.quantum_text)

        warning = QLabel(
            "Quantum Lab không phải máy tính lượng tử. Hệ thống mặc định chỉ đề xuất; "
            "MAIN không bao giờ tự đổi. Shadow chỉ áp dụng khi validation đạt chuẩn và có xác nhận."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "color:#facc15;background:#2a210b;border:1px solid #854d0e;"
            "padding:7px;border-radius:6px;"
        )
        right_layout.addWidget(warning)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        self.tabs.addTab(tab, "Learning")
        self.refresh_learning_center()




    def _build_quantum_optimizer_tab(self):
        tab=QWidget()
        root=QVBoxLayout(tab)
        root.setContentsMargins(10,10,10,10)
        root.setSpacing(8)

        top=QHBoxLayout()
        top.addWidget(QLabel("<h2>Quantum Optimizer Dashboard</h2>"))
        top.addStretch()
        self.quantum_dashboard_run_btn=QPushButton("Chạy tối ưu")
        self.quantum_dashboard_run_btn.clicked.connect(self.run_quantum_optimizer)
        self.quantum_stop_btn=QPushButton("Dừng")
        self.quantum_stop_btn.setEnabled(False)
        self.quantum_stop_btn.clicked.connect(self.stop_quantum_optimizer)
        self.quantum_dashboard_apply_btn=QPushButton("Apply to SHADOW")
        self.quantum_dashboard_apply_btn.setEnabled(False)
        self.quantum_dashboard_apply_btn.clicked.connect(self.apply_quantum_shadow)
        top.addWidget(self.quantum_dashboard_run_btn)
        top.addWidget(self.quantum_stop_btn)
        top.addWidget(self.quantum_dashboard_apply_btn)
        root.addLayout(top)

        self.quantum_progress=QProgressBar()
        self.quantum_progress.setRange(0,self.quantum_optimizer.generations)
        root.addWidget(self.quantum_progress)

        cards=QHBoxLayout()
        self.quantum_generation_card=MetricCard("GENERATION","0 / 0","Chưa chạy")
        self.quantum_best_card=MetricCard("BEST FITNESS","0.00","Fitness tốt nhất")
        self.quantum_avg_card=MetricCard("AVG FITNESS","0.00","Fitness trung bình")
        self.quantum_eval_card=MetricCard("EVALUATIONS","0","Cấu hình đã chấm")
        self.quantum_cache_card=MetricCard("CACHE","0","LRU bounded cache")
        for card in (
            self.quantum_generation_card,self.quantum_best_card,
            self.quantum_avg_card,self.quantum_eval_card,
            self.quantum_cache_card,
        ):
            cards.addWidget(card)
        root.addLayout(cards)

        splitter=QSplitter(Qt.Orientation.Horizontal)
        chart_box=QGroupBox("Fitness Evolution")
        chart_layout=QVBoxLayout(chart_box)
        self.quantum_fitness_chart=Sparkline()
        chart_layout.addWidget(self.quantum_fitness_chart)
        self.quantum_runtime_label=QLabel("Elapsed 0.0s · ETA -")
        chart_layout.addWidget(self.quantum_runtime_label)
        splitter.addWidget(chart_box)

        detail_box=QGroupBox("Validation & Parameter Diff")
        detail_layout=QVBoxLayout(detail_box)
        self.quantum_dashboard_readiness = QuantumReadinessWidget("QUANTUM READINESS")
        detail_layout.addWidget(self.quantum_dashboard_readiness)
        self.quantum_dashboard_text=QTextEdit()
        self.quantum_dashboard_text.setReadOnly(True)
        self.quantum_dashboard_text.setPlainText("Chưa chạy tối ưu hóa.")
        detail_layout.addWidget(self.quantum_dashboard_text)
        splitter.addWidget(detail_box)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter,1)

        safety=QLabel(
            "MAIN bị khóa tuyệt đối. Chỉ SHADOW được đề xuất; "
            "áp dụng cần validation đạt chuẩn và xác nhận thủ công."
        )
        safety.setWordWrap(True)
        safety.setStyleSheet(
            "color:#facc15;background:#2a210b;"
            "border:1px solid #854d0e;padding:8px;border-radius:6px;"
        )
        root.addWidget(safety)
        self.tabs.addTab(tab,"Quantum Optimizer")




    def run_quantum_optimizer(self):
        if self.quantum_thread is not None:
            return
        governance = self.quantum_runtime_guard.evaluate(QuantumRuntimeAction.OPTIMIZE)
        if not governance.allowed:
            message = governance.message()
            logger.warning("Blocked legacy Quantum optimizer path: %s", message)
            self.quantum_text.setPlainText(message)
            if hasattr(self, "quantum_dashboard_text"):
                self.quantum_dashboard_text.setPlainText(message)
            self.quantum_apply_btn.setEnabled(False)
            if hasattr(self, "quantum_dashboard_apply_btn"):
                self.quantum_dashboard_apply_btn.setEnabled(False)
            QMessageBox.warning(self, "Quantum Governance BLOCK", message)
            return
        self.quantum_last_report=None
        self.quantum_fitness_history=[]
        self.quantum_run_btn.setEnabled(False)
        self.quantum_apply_btn.setEnabled(False)
        if hasattr(self,"quantum_dashboard_run_btn"):
            self.quantum_dashboard_run_btn.setEnabled(False)
            self.quantum_dashboard_apply_btn.setEnabled(False)
            self.quantum_stop_btn.setEnabled(True)
            self.quantum_progress.setValue(0)
            self.quantum_fitness_chart.set_values([])
            self.quantum_dashboard_text.setPlainText("Đang khởi tạo optimizer...")
        self.quantum_text.setPlainText("Đang tối ưu trên lịch sử lệnh đã đóng...")

        self.quantum_thread=QThread(self)
        self.quantum_worker=QuantumWorker(self.quantum_optimizer)
        self.quantum_worker.moveToThread(self.quantum_thread)
        self.quantum_thread.started.connect(self.quantum_worker.run)
        self.quantum_worker.progress.connect(self.on_quantum_progress)
        self.quantum_worker.finished.connect(self.on_quantum_finished)
        self.quantum_worker.error.connect(self.on_quantum_error)
        # S4.1.2-r1 (corrected): quit() must be causally dependent on the
        # worker's actual C++ destruction, not merely posted from the same
        # signal. worker.deleteLater() (DirectConnection, posted to the
        # worker-thread's own queue) and thread.quit() (QueuedConnection,
        # posted to the GUI-thread's queue) are two independent queues with
        # no ordering guarantee between them when both are wired from
        # finished/error directly. Chaining through destroyed enforces:
        # deleteLater() -> worker-thread processes DeferredDelete -> C++
        # object destroyed -> destroyed signal fires -> only then is
        # thread.quit() requested.
        self.quantum_worker.finished.connect(self.quantum_worker.deleteLater)
        self.quantum_worker.error.connect(self.quantum_worker.deleteLater)
        self.quantum_worker.destroyed.connect(self.quantum_thread.quit)
        self.quantum_thread.finished.connect(self.quantum_thread.deleteLater)
        self.quantum_thread.finished.connect(self._cleanup_quantum_thread)
        self.quantum_thread.start()

    def stop_quantum_optimizer(self):
        if self.quantum_worker is not None:
            self.quantum_worker.stop()
            self.quantum_text.append("\nĐang yêu cầu dừng sau generation hiện tại...")
            if hasattr(self,"quantum_stop_btn"):
                self.quantum_stop_btn.setEnabled(False)

    @Slot(object)
    def on_quantum_progress(self,info):
        generation=int(info.get("generation",0))
        generations=int(info.get("generations",0))
        best=float(info.get("best_fitness",0.0))
        average=float(info.get("avg_fitness",0.0))
        evaluations=int(info.get("evaluations",0))
        cache_entries=int(info.get("cache_entries",0))
        elapsed=float(info.get("elapsed_seconds",0.0))
        self.quantum_fitness_history.append(best)

        if hasattr(self,"quantum_progress"):
            self.quantum_progress.setMaximum(max(generations,1))
            self.quantum_progress.setValue(generation)
            self.quantum_generation_card.set_data(f"{generation} / {generations}","Đang tiến hóa")
            self.quantum_best_card.set_data(f"{best:.2f}","Fitness tốt nhất")
            self.quantum_avg_card.set_data(f"{average:.2f}","Fitness trung bình")
            self.quantum_eval_card.set_data(str(evaluations),"Cấu hình đã chấm")
            self.quantum_cache_card.set_data(str(cache_entries),"LRU bounded cache")
            self.quantum_fitness_chart.set_values(self.quantum_fitness_history)
            per_gen=elapsed/generation if generation else 0.0
            eta=max(0.0,per_gen*(generations-generation))
            self.quantum_runtime_label.setText(
                f"Elapsed {elapsed:.1f}s · ETA {eta:.1f}s"
            )
        self.quantum_text.setPlainText(
            f"Generation {generation}/{generations}\n"
            f"Best Fitness {best:.2f}\n"
            f"Average Fitness {average:.2f}\n"
            f"Evaluations {evaluations}"
        )

    @Slot(object)
    def on_quantum_finished(self, report):
        # Quantum can legitimately finish with CANCELLED/INSUFFICIENT_DATA or an
        # early-exit payload. Validate the contract before touching nested keys.
        payload = report if isinstance(report, dict) else {"status": "INVALID_REPORT", "raw_type": type(report).__name__}
        self.quantum_last_report = payload
        try:
            self.quantum_optimizer.save_report(payload)
        except Exception as exc:
            logger.warning("Unable to persist Quantum report: %s", exc)
        view = build_quantum_report_view(report)
        if not view.schema_valid:
            logger.error(
                "Quantum report schema mismatch: status=%s missing=%s keys=%s",
                view.status, view.missing_keys, sorted(payload.keys()),
            )
        self.quantum_text.setPlainText(view.text)
        if hasattr(self, "quantum_dashboard_text"):
            self.quantum_dashboard_text.setPlainText(view.text)
            self.quantum_dashboard_apply_btn.setEnabled(view.safe_to_apply_shadow)
            self.quantum_stop_btn.setEnabled(False)
        self.quantum_apply_btn.setEnabled(view.safe_to_apply_shadow)
        self._refresh_quantum_readiness()

    @Slot(str)
    def on_quantum_error(self,message):
        logger.error("Quantum optimizer failed: %s",message)
        text=f"Lỗi Quantum Lab: {message}"
        self.quantum_text.setPlainText(text)
        if hasattr(self,"quantum_dashboard_text"):
            self.quantum_dashboard_text.setPlainText(text)
            self.quantum_stop_btn.setEnabled(False)
        self.quantum_apply_btn.setEnabled(False)

    def _cleanup_quantum_thread(self):
        # S4.1.2-r1 (corrected): thread.deleteLater() is already scheduled
        # via thread.finished -> thread.deleteLater() at launch time. Do not
        # call deleteLater() a second time here; only clear Python refs and
        # update UI state.
        self.quantum_worker=None
        self.quantum_thread=None
        self.quantum_run_btn.setEnabled(True)
        if hasattr(self,"quantum_dashboard_run_btn"):
            self.quantum_dashboard_run_btn.setEnabled(True)
            self.quantum_stop_btn.setEnabled(False)

    def apply_quantum_shadow(self):
        """Create, simulate, review, then apply a SHADOW-only candidate."""
        governance = self.quantum_runtime_guard.evaluate(QuantumRuntimeAction.APPLY_SHADOW)
        if not governance.allowed:
            message = governance.message()
            logger.warning("Blocked legacy Quantum SHADOW path: %s", message)
            self.quantum_text.append("\n" + message)
            self.quantum_apply_btn.setEnabled(False)
            if hasattr(self, "quantum_dashboard_apply_btn"):
                self.quantum_dashboard_apply_btn.setEnabled(False)
            QMessageBox.warning(self, "Quantum Governance BLOCK", message)
            return
        if not self.quantum_last_report:
            return
        try:
            candidate = self.quantum_optimizer.create_shadow_candidate(self.quantum_last_report)
            backtester = CandidateBacktestService(self.quantum_optimizer)
            report = backtester.simulate(candidate)
            report_path = backtester.save_report(report)
            base = report.get("baseline", {})
            proposed = report.get("candidate", {})
            checks = report.get("checks", {})
            lines = [
                "SHADOW candidate validation report",
                f"State: {report.get('state')}",
                f"Holdout samples: {report.get('holdout_samples', 0)}",
                f"Baseline: n={base.get('n',0)} · WR={base.get('wr',0):.1f}% · AvgR={base.get('avg_r',0):+.3f} · DD={base.get('max_dd',0):.2f}",
                f"Candidate: n={proposed.get('n',0)} · WR={proposed.get('wr',0):.1f}% · AvgR={proposed.get('avg_r',0):+.3f} · DD={proposed.get('max_dd',0):.2f}",
                f"Backtest report: {report_path}",
                "Checks: " + ", ".join(f"{k}={'PASS' if v else 'FAIL'}" for k, v in checks.items()),
                "MAIN remains immutable. LIVE remains disabled.",
            ]
            self.quantum_text.append("\n" + "\n".join(lines))
            if report.get("state") != "PASS":
                QMessageBox.warning(self, "SHADOW candidate rejected", "Backtest/guardrails chưa PASS. Candidate không được áp dụng.")
                return
            answer = QMessageBox.question(
                self,
                "Apply to SHADOW — Review 1/2",
                "Candidate đã PASS chronological PAPER holdout.\n"
                "Thao tác này chỉ ghi SHADOW thresholds và family weights, tạo backup và audit log.\n"
                "MAIN không thay đổi. Tiếp tục?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            final = QMessageBox.warning(
                self,
                "Apply to SHADOW — Confirm 2/2",
                "Xác nhận cuối: ghi candidate vào SHADOW config?\n"
                "Sau khi áp dụng cần khởi động lại và quan sát PAPER. Không có auto-promotion sang MAIN.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if final != QMessageBox.StandardButton.Yes:
                return
            promotion = ShadowPromotionService(config_path=str(self.quantum_optimizer.config_path))
            audit = promotion.apply(candidate, report, human_confirmation="APPLY TO SHADOW")
            self.quantum_text.append(
                "\nĐã áp dụng SHADOW-only. "
                f"Backup: {audit['backup_path']}\nAudit: {audit['audit_path']}\n"
                "MAIN unchanged; restart required; PAPER observation required."
            )
            self.quantum_apply_btn.setEnabled(False)
            if hasattr(self, "quantum_dashboard_apply_btn"):
                self.quantum_dashboard_apply_btn.setEnabled(False)
        except Exception as exc:
            QMessageBox.warning(self, "Không thể Apply to SHADOW", str(exc))

    def _refresh_quantum_readiness(self):
        try:
            db_path = getattr(self.learning_service, "db_path", None) or getattr(self.quantum_optimizer, "db_path", "data/dvs_paper_trades.db")
            required = int(getattr(self.quantum_optimizer, "min_closed", 80) or 80)
            snapshot = QuantumReadinessService(db_path, required=required).snapshot()
            if hasattr(self, "learning_quantum_readiness"):
                self.learning_quantum_readiness.set_snapshot(snapshot)
            if hasattr(self, "quantum_dashboard_readiness"):
                self.quantum_dashboard_readiness.set_snapshot(snapshot)
            return snapshot
        except Exception as exc:
            logger.warning("Unable to refresh Quantum readiness: %s", exc)
            return None

    def _learning_stop_requested(self) -> bool:
        worker = getattr(self, "_learning_worker", None)
        stop_event = getattr(worker, "_stop_requested", None)
        try:
            return bool(stop_event is not None and stop_event.is_set())
        except Exception:
            return False

    def refresh_learning_center(self, *args, **kwargs):
        try:
            from dvs_ai.runtime.learning_dispatch_forensics import (
                infer_dispatch_source,
                record_learning_dispatch,
            )
            dispatch_source, dispatch_reason = infer_dispatch_source(
                self,
                args=tuple(args),
                kwargs=dict(kwargs),
            )
            record_learning_dispatch(
                "dispatch_attempt",
                window=self,
                source=dispatch_source,
                reason=dispatch_reason,
                capture_stack=True,
                positional_arg_count=len(args),
                keyword_names=sorted(str(key) for key in kwargs),
            )
        except Exception:
            dispatch_source, dispatch_reason = "forensics_unavailable", None

        stop_requested = self._learning_stop_requested()
        if not hasattr(self, "setup_perf_table") or self.is_closing or stop_requested:
            reject_reason = (
                "missing_learning_widgets"
                if not hasattr(self, "setup_perf_table")
                else "shutdown_in_progress"
                if self.is_closing
                else "worker_stop_requested"
            )
            if stop_requested:
                self._learning_refresh_pending = False
            try:
                from dvs_ai.runtime.learning_dispatch_forensics import record_learning_dispatch
                record_learning_dispatch(
                    "dispatch_rejected_precondition",
                    window=self,
                    source=dispatch_source,
                    reason=reject_reason,
                )
            except Exception:
                pass
            try:
                from dvs_ai.runtime.learning_refresh_stabilization import record_stabilization
                record_stabilization(
                    "dispatch_suppressed",
                    source=dispatch_source,
                    reason=reject_reason,
                    learning_refresh_running=bool(self._learning_refresh_running),
                    learning_refresh_pending=bool(self._learning_refresh_pending),
                )
            except Exception:
                pass
            return

        if self._learning_refresh_running:
            self._learning_refresh_pending = True
            try:
                from dvs_ai.runtime.learning_dispatch_forensics import record_learning_dispatch
                record_learning_dispatch(
                    "dispatch_coalesced_to_pending",
                    window=self,
                    source=dispatch_source,
                    reason=dispatch_reason,
                )
            except Exception:
                pass
            return

        self._learning_refresh_running = True
        try:
            from dvs_ai.runtime.learning_dispatch_forensics import record_learning_dispatch
            record_learning_dispatch(
                "dispatch_accepted",
                window=self,
                source=dispatch_source,
                reason=dispatch_reason,
            )
        except Exception:
            pass
        try:
            from dvs_ai.runtime.learning_refresh_lifecycle import record_learning_refresh_event
            record_learning_refresh_event(
                "refresh_dispatch_requested",
                worker=self._learning_worker,
                thread=self._learning_thread,
                refresh_pending=bool(self._learning_refresh_pending),
            )
        except Exception:
            pass
        self._learning_refresh_requested.emit()
        try:
            from dvs_ai.runtime.learning_dispatch_forensics import record_learning_dispatch
            record_learning_dispatch(
                "dispatch_signal_emitted",
                window=self,
                source=dispatch_source,
                reason=dispatch_reason,
            )
        except Exception:
            pass

    @Slot(object)
    def _on_learning_refresh_ready(self, payload) -> None:
        try:
            from dvs_ai.runtime.learning_refresh_lifecycle import record_learning_refresh_event
            record_learning_refresh_event(
                "gui_ready_received",
                worker=self._learning_worker,
                thread=self._learning_thread,
            )
        except Exception:
            pass
        self._learning_refresh_running = False
        if self.is_closing or not hasattr(self, "setup_perf_table"):
            return
        self._render_learning_payload(dict(payload or {}))
        if self._learning_refresh_pending and not self._learning_stop_requested():
            self._learning_refresh_pending = False
            try:
                from dvs_ai.runtime.learning_dispatch_forensics import record_learning_dispatch
                record_learning_dispatch(
                    "pending_dispatch_scheduled",
                    window=self,
                    source="pending_after_ready",
                    reason="learning_refresh_pending",
                    delay_ms=0,
                )
            except Exception:
                pass
            QTimer.singleShot(0, self.refresh_learning_center)

    @Slot(str)
    def _on_learning_refresh_failed(self, message: str) -> None:
        try:
            from dvs_ai.runtime.learning_refresh_lifecycle import record_learning_refresh_event
            record_learning_refresh_event(
                "gui_failed_received",
                worker=self._learning_worker,
                thread=self._learning_thread,
                error=str(message),
            )
        except Exception:
            pass
        self._learning_refresh_running = False
        logger.error("LEARNING_REFRESH_FAILED %s", message)
        if (
            self._learning_refresh_pending
            and not self.is_closing
            and not self._learning_stop_requested()
        ):
            self._learning_refresh_pending = False
            try:
                from dvs_ai.runtime.learning_dispatch_forensics import record_learning_dispatch
                record_learning_dispatch(
                    "pending_dispatch_scheduled",
                    window=self,
                    source="pending_after_failure",
                    reason="learning_refresh_pending",
                    delay_ms=250,
                )
            except Exception:
                pass
            QTimer.singleShot(250, self.refresh_learning_center)

    @Slot(str)
    def _on_learning_refresh_cancelled(self, reason: str) -> None:
        try:
            from dvs_ai.runtime.learning_refresh_lifecycle import record_learning_refresh_event
            record_learning_refresh_event(
                "gui_cancelled_received",
                worker=self._learning_worker,
                thread=self._learning_thread,
                reason=str(reason),
            )
        except Exception:
            pass
        self._learning_refresh_running = False
        self._learning_refresh_pending = False
        logger.info("LEARNING_REFRESH_CANCELLED %s", reason)

    def _render_learning_payload(self, payload):
        render_started = time.perf_counter()
        readiness_snapshot = payload.get("readiness")
        overview = payload.get("overview", {})
        main_overview = payload.get("main_overview", {})
        shadow_overview = payload.get("shadow_overview", {})
        pf = overview["profit_factor"]
        pf_text = "∞" if math.isinf(pf) else f"{pf:.2f}"

        open_count = max(0, int(overview['total']) - int(overview['closed']))
        eligible_count = int(getattr(readiness_snapshot, 'eligible', 0) or 0) if readiness_snapshot is not None else 0
        self.learn_total.set_data(
            str(overview["closed"]),
            f"Tổng PAPER {overview['total']} · đang mở {open_count} · đủ chuẩn Quantum {eligible_count}"
        )
        self.learn_wr.set_data(
            f"{overview['win_rate']:.1f}%",
            f"{overview['wins']} thắng · {overview['losses']} thua"
        )
        self.learn_avg_r.set_data(
            f"{overview['avg_r']:+.2f}",
            "R trung bình mỗi lệnh đã đóng"
        )
        self.learn_pf.set_data(
            pf_text,
            "Profit Factor"
        )
        self.learn_long_short.set_data(
            f"{overview['long_wr']:.0f}% / {overview['short_wr']:.0f}%",
            "LONG / SHORT"
        )

        self.setup_perf_table.setRowCount(0)
        for item in payload["setup_performance"]:
            row = self.setup_perf_table.rowCount()
            self.setup_perf_table.insertRow(row)
            values = [
                item["setup"],
                str(item["trades"]),
                str(item["closed"]),
                f"{item['win_rate']:.1f}%",
                f"{item['avg_r']:+.2f}",
                "∞" if math.isinf(item["profit_factor"]) else f"{item['profit_factor']:.2f}",
                "ĐỦ MẪU" if item["reliable"] else "THAM KHẢO",
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                self.setup_perf_table.setItem(row, col, cell)
            if item["reliable"]:
                self.setup_perf_table.item(row, 6).setForeground(QColor("#4ade80"))
            else:
                self.setup_perf_table.item(row, 6).setForeground(QColor("#facc15"))

        self.calibration_table.setRowCount(0)
        for item in payload["confidence_calibration"]:
            row = self.calibration_table.rowCount()
            self.calibration_table.insertRow(row)
            values = [
                item["bucket"],
                str(item["samples"]),
                f"{item['avg_confidence']:.1f}%",
                f"{item['observed_win_rate']:.1f}%",
                f"{item['calibration_gap']:+.1f}",
            ]
            for col, value in enumerate(values):
                self.calibration_table.setItem(row, col, QTableWidgetItem(value))
            gap_item = self.calibration_table.item(row, 4)
            if item["reliable"]:
                if abs(item["calibration_gap"]) <= 10:
                    gap_item.setForeground(QColor("#4ade80"))
                else:
                    gap_item.setForeground(QColor("#facc15"))
            else:
                gap_item.setForeground(QColor("#94a3b8"))

        monitor = payload["rejection_monitor"]
        shadow = payload["threshold_comparison"]
        execution = payload["execution_diagnostics"]
        self.strictness_label.setText(
            f"ĐỘ KHẮT KHE: {monitor['strictness']}"
        )
        rejection_lines = [
            f"Đã đánh giá: {monitor['evaluations']}",
            f"Đạt ngưỡng chính: {monitor['accepted']}",
            f"Tỷ lệ chấp nhận: {monitor['acceptance_rate']:.2f}%",
            "",
            "Điều kiện loại nhiều nhất:",
        ]
        if monitor["top_rejections"]:
            for reason, count in monitor["top_rejections"]:
                rejection_lines.append(f"• {reason}: {count}")
        else:
            rejection_lines.append("• Chưa có dữ liệu")
        rejection_lines.extend([
            "",
            "Execution diagnostics:",
            (
                f"• Plan repair: {execution['repaired']}/"
                f"{execution['plans']} "
                f"({execution['repair_rate']:.2f}%) — "
                f"{execution['repair_state']}"
            ),
            (
                f"• Slippage Avg/Median/P90: "
                f"{execution['avg_slippage_pct']:.3f}% / "
                f"{execution['median_slippage_pct']:.3f}% / "
                f"{execution['p90_slippage_pct']:.3f}% "
                f"(n={execution['slippage_samples']})"
            ),
            (
                f"• Ambiguous {execution['ambiguous']} · "
                f"Expired {execution['expired']} · "
                f"Avg hold {execution['avg_hold_minutes']:.1f}m"
            ),
            "",
            f"Main candidates: {shadow['main_candidates']}",
            f"Shadow candidates: {shadow['shadow_candidates']}",
            shadow["message"],
            "",
            (
            "MAIN: "
            f"{main_overview['closed']} closed · "
            f"{main_overview.get('determinate', 0)} determinate · "
            f"Amb {main_overview.get('ambiguous', 0)} · "
            f"WR {main_overview['win_rate']:.1f}% · "
            f"AvgR {main_overview['avg_r']:+.2f}"
        ),
        (
            "SHADOW: "
            f"{shadow_overview['closed']} closed · "
            f"{shadow_overview.get('determinate', 0)} determinate · "
            f"Amb {shadow_overview.get('ambiguous', 0)} · "
            f"WR {shadow_overview['win_rate']:.1f}% · "
            f"AvgR {shadow_overview['avg_r']:+.2f}"
        ),
        "",
        f"Khuyến nghị: {monitor['recommendation']}",
        ])
        self.threshold_text.setPlainText("\n".join(rejection_lines))

        self.weight_table.setRowCount(0)
        for item in payload["weight_recommendations"]:
            row = self.weight_table.rowCount()
            self.weight_table.insertRow(row)
            values = [
                item["setup"],
                str(item["samples"]),
                f"{item['win_rate']:.1f}%",
                f"{item['avg_r']:+.2f}",
                item["action"],
                f"{item['delta']:+d}",
            ]
            for col, value in enumerate(values):
                self.weight_table.setItem(row, col, QTableWidgetItem(value))
            action_item = self.weight_table.item(row, 4)
            if item["delta"] > 0:
                action_item.setForeground(QColor("#4ade80"))
            elif item["delta"] < 0:
                action_item.setForeground(QColor("#f87171"))
            else:
                action_item.setForeground(QColor("#94a3b8"))
        self._record_gui_hotspot(
            "learning_payload_render",
            (time.perf_counter() - render_started) * 1000.0,
            setup_rows=int(getattr(self.setup_perf_table, "rowCount", lambda: 0)()),
        )

    def _toggle_expert_mode(self, checked: bool):
        """Switch UX mode without depending on a removed legacy renderer.

        The unified UI renders the selected analysis through ``show_selected``.
        This method is intentionally fail-safe during startup, when no current
        analysis or selected table row may exist yet.
        """
        self.expert_mode = bool(checked)
        self.settings.setValue("ux/expert_mode", self.expert_mode)
        self.mode_btn.setText("Chế độ: Chuyên gia" if self.expert_mode else "Chế độ: Dễ hiểu")
        self._apply_ux_mode()

        if getattr(self, "current_analysis", None) is not None:
            refresh = getattr(self, "show_selected", None)
            if callable(refresh):
                try:
                    refresh(preserve_timeframe=True, preserve_scroll=True)
                except Exception:
                    logger.exception("UI_EXPERT_MODE_REFRESH_FAILED")

        refresh_microstructure = getattr(self, "refresh_microstructure_tab", None)
        if callable(refresh_microstructure):
            try:
                refresh_microstructure()
            except Exception:
                logger.exception("UI_EXPERT_MODE_MICROSTRUCTURE_REFRESH_FAILED")

    def _apply_ux_mode(self):
        """Apply a materially different beginner/expert information architecture."""
        expert = bool(self.expert_mode)

        # Beginner mode: concise explanation only. Expert mode: analytical dashboard + raw details.
        for name in (
            "smart_score_box", "smart_metrics_box", "smart_insight_container",
            "smart_timeline_box", "smart_text", "core_text",
            "micro_table", "micro_detail",
        ):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.setVisible(expert)

        for name in ("smart_summary", "core_summary", "micro_summary"):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.setVisible(not expert)

    @staticmethod
    def _plain_view_html(view, title: str) -> str:
        colors = {"GREEN": "#22c55e", "YELLOW": "#facc15", "RED": "#ef4444"}
        color = colors.get(view.traffic_light, "#94a3b8")
        reasons = "".join(f"<li>{x}</li>" for x in view.reasons)
        steps = "".join(f"<li>{x}</li>" for x in view.next_steps)
        return (
            f"<div style='font-size:15px'>"
            f"<h2 style='color:{color}'>● {view.traffic_label}</h2>"
            f"<h3>{title}</h3><p><b>{view.headline}</b></p>"
            f"<p>{view.direction_text}</p><p>{view.risk_text}</p>"
            f"<h3>Vì sao?</h3><ul>{reasons}</ul>"
            f"<h3>Cần chờ gì?</h3><ul>{steps}</ul>"
            f"<p style='color:#facc15'><b>AI Coach:</b> {view.caution}</p>"
            f"<p style='color:#94a3b8'>Bấm “Chế độ: Dễ hiểu” để chuyển sang dữ liệu chuyên gia.</p>"
            f"</div>"
        )

    def _build_microstructure_tab(self):
        tab = QWidget()
        root = QVBoxLayout(tab)
        root.setContentsMargins(10, 10, 10, 10)
        root.addWidget(QLabel("<h2>Smart Money Footprint V4 · Composite Exhaustion</h2>"))

        note = QLabel(
            "Kết hợp Microstructure L2, Position Building, Lifecycle, "
            "Order Block, FVG, BOS/CHOCH và Liquidity Sweep. "
            "Footprint là bằng chứng xác nhận; Decision Engine vẫn là nơi duy nhất ra quyết định."
        )
        note.setWordWrap(True)
        root.addWidget(note)
        self.micro_summary = QTextEdit()
        self.micro_summary.setReadOnly(True)
        self.micro_summary.setObjectName("BeginnerSummary")
        root.addWidget(self.micro_summary)

        self.micro_table = QTableWidget(0, 27)
        self.micro_table.setHorizontalHeaderLabels([
            "Coin", "Quality", "Lifecycle", "Direction",
            "FP Raw", "FP Context", "Confirm", "Align", "FP Gate",
            "Position", "Regime", "Book Imb", "Delta USD", "OFI",
            "Absorption", "Bid Wall", "Ask Wall", "Persistence",
            "Spoofing", "COS", "Operator Bias", "Distribution",
            "Sell Pressure", "Exhaustion", "Bottom %", "Bottom State", "Status",
        ])
        self.micro_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.micro_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.micro_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.micro_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.micro_table.verticalHeader().setVisible(False)
        self.micro_table.itemSelectionChanged.connect(
            self._show_selected_microstructure
        )
        self._micro_analysis_rows = []
        root.addWidget(self.micro_table, 1)

        self.micro_detail = QTextEdit()
        self.micro_detail.setReadOnly(True)
        self.micro_detail.setMaximumHeight(150)
        root.addWidget(self.micro_detail)

        self.tabs.addTab(tab, "Smart Money")


    def refresh_microstructure_tab(self, *args, **kwargs):
        if hasattr(self, "ui_profiler"):
            with self.ui_profiler.section("refresh_microstructure_tab"):
                return self._refresh_microstructure_tab_impl(*args, **kwargs)
        return self._refresh_microstructure_tab_impl(*args, **kwargs)

    def _refresh_microstructure_tab_impl(self):
        if not hasattr(self, "micro_table"):
            return

        selected_symbol = self.selection_state.symbol
        current_row = self.micro_table.currentRow()
        previous_rows = getattr(self, "_micro_analysis_rows", ())
        if selected_symbol is None and 0 <= current_row < len(previous_rows):
            selected_symbol = getattr(previous_rows[current_row], "symbol", None)

        rows = [
            analysis
            for analysis in self.results.values()
            if getattr(analysis, "microstructure", None) is not None
        ]
        rows.sort(
            key=lambda analysis: (
                float(getattr(analysis, "footprint_score", 0.0)),
                float(
                    analysis.microstructure.composite_operator_score
                ),
            ),
            reverse=True,
        )
    
        self.micro_table.setRowCount(len(rows))
        for row, analysis in enumerate(rows):
            micro = analysis.microstructure
            footprint = getattr(analysis, "footprint", None)
    
            lifecycle = str(
                getattr(
                    footprint,
                    "lifecycle_stage",
                    getattr(analysis, "maturity_lifecycle", "UNKNOWN"),
                )
            )
            footprint_direction = str(
                getattr(footprint, "direction", "NEUTRAL")
            )
            raw_score = float(
                getattr(analysis, "footprint_raw_score", 0.0)
            )
            context_score = float(
                getattr(analysis, "footprint_score", 0.0)
            )
            confirmation = str(
                getattr(
                    analysis,
                    "footprint_confirmation_depth",
                    "NONE",
                )
            )
            alignment = str(
                getattr(
                    analysis,
                    "footprint_direction_alignment",
                    "NOT_APPLIED",
                )
            )
            footprint_gate = str(
                getattr(analysis, "footprint_gate", "NOT_APPLIED")
            )
            position_score = float(
                getattr(analysis, "position_building_score", 0.0)
            )
            position_regime = str(
                getattr(
                    analysis,
                    "position_building_regime",
                    "UNKNOWN",
                )
            )
    
            values = [
                analysis.symbol.replace(":USDT", ""),
                micro.data_quality,
                lifecycle,
                footprint_direction,
                f"{raw_score:.1f}",
                f"{context_score:.1f}",
                confirmation,
                alignment,
                footprint_gate,
                f"{position_score:.1f}",
                position_regime,
                f"{micro.book_imbalance:+.3f}",
                f"{micro.trade_delta_usd:,.0f}",
                f"{micro.ofi_score:.1f}",
                f"{micro.absorption_score:.1f}",
                f"{micro.bid_wall_score:.1f}",
                f"{micro.ask_wall_score:.1f}",
                (
                    f"B {micro.bid_wall_persistence:.0f}/"
                    f"A {micro.ask_wall_persistence:.0f}"
                ),
                f"{micro.spoofing_probability:.1f}",
                f"{micro.composite_operator_score:.1f}",
                micro.operator_bias,
                f"{getattr(analysis, 'composite_distribution_progress', 0.0):.1f}",
                f"{getattr(analysis, 'composite_selling_pressure', 0.0):.1f}",
                f"{getattr(analysis, 'composite_exhaustion_score', 0.0):.1f}",
                f"{getattr(analysis, 'bottom_formation_probability', 0.0):.1f}",
                str(getattr(analysis, 'bottom_formation_state', 'NOT_EVALUATED')),
                analysis.entry_status.value,
            ]
    
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == 5:
                    if context_score >= 72:
                        item.setForeground(QColor("#4ade80"))
                    elif context_score >= 58:
                        item.setForeground(QColor("#facc15"))
                    else:
                        item.setForeground(QColor("#f87171"))
                elif col == 8:
                    if footprint_gate == "READY_CANDIDATE":
                        item.setForeground(QColor("#4ade80"))
                    elif footprint_gate.startswith("BLOCK"):
                        item.setForeground(QColor("#f87171"))
                    else:
                        item.setForeground(QColor("#facc15"))
                elif col == 26:
                    if analysis.entry_status.value == "READY":
                        item.setForeground(QColor("#4ade80"))
                    elif analysis.entry_status.value == "SETUP":
                        item.setForeground(QColor("#facc15"))
                    else:
                        item.setForeground(QColor("#94a3b8"))
                self.micro_table.setItem(row, col, item)
    
        self._micro_analysis_rows = rows
        if rows:
            selected_row = 0
            if selected_symbol:
                for index, analysis in enumerate(rows):
                    if getattr(analysis, "symbol", None) == selected_symbol:
                        selected_row = index
                        break
            self._render_microstructure_analysis(rows[selected_row])
            self.micro_table.blockSignals(True)
            self.micro_table.selectRow(selected_row)
            self.micro_table.blockSignals(False)
        else:
            self.micro_summary.setHtml("<h2>ĐANG CHỜ DỮ LIỆU</h2><p>Hãy hoàn thành một vòng quét để AI giải thích Smart Money bằng ngôn ngữ dễ hiểu.</p>")
            self.micro_detail.setPlainText(
                "Chưa có snapshot. Hệ thống sẽ hiển thị Footprint sau khi hoàn thành một vòng quét."
            )
    
    def _show_selected_microstructure(self) -> None:
        """Render details for the currently selected Smart Money row."""
        if not hasattr(self, "micro_table"):
            return
        row = self.micro_table.currentRow()
        rows = getattr(self, "_micro_analysis_rows", ())
        if row < 0 or row >= len(rows):
            return
        analysis = rows[row]
        self._set_selected_analysis_context(
            analysis,
            source="smart_money",
            sync_main_table=True,
        )
        self._render_microstructure_analysis(analysis)

    def _set_selected_analysis_context(
        self,
        analysis,
        *,
        source: str,
        sync_main_table: bool = False,
        timeframe: str | None = None,
    ) -> None:
        """Update shared selection without recursively rendering another tab."""
        if analysis is None:
            return
        symbol = getattr(analysis, "symbol", None)
        if not symbol:
            return
        self._set_current_analysis_reference(analysis, mutation_site="_set_selected_analysis_context")
        selected_timeframe = timeframe or self.selection_state.timeframe or "15m"
        self.selection_state.select(
            symbol,
            timeframe=selected_timeframe,
            source=source,
        )
        if hasattr(self, "current_coin_badge"):
            self.current_coin_badge.setText(
                f"CURRENT: {symbol.replace(':USDT', '')}"
            )
        if hasattr(self, "truth_dashboard"):
            self._set_truth_pending_reference(
                analysis,
                mutation_site="_set_selected_analysis_context",
            )
            if self._is_truth_workspace_visible():
                self._set_truth_dashboard_analysis(
                    analysis,
                    mutation_site=(
                        "_set_selected_analysis_context:visible"
                    ),
                )
                self._set_truth_pending_reference(
                    None,
                    mutation_site=(
                        "_set_selected_analysis_context:committed"
                    ),
                )
        if hasattr(self, "header_symbol"):
            self.header_symbol.blockSignals(True)
            self.header_symbol.setCurrentText(symbol.replace(":USDT", ""))
            self.header_symbol.blockSignals(False)
        if sync_main_table and hasattr(self, "table"):
            row = self._row_by_symbol.get(symbol, -1)
            if row >= 0 and self.table.currentRow() != row:
                self.table.blockSignals(True)
                self.table.selectRow(row)
                self.table.blockSignals(False)
        self._submit_core_shadow_cycle(analysis)

    def _legacy_action_for_shadow(self, analysis) -> str:
        action = str(getattr(analysis, "action", "")).upper()
        entry = str(getattr(getattr(analysis, "entry_status", None), "value", "WAIT")).upper()
        direction = str(getattr(analysis, "direction", "NEUTRAL")).upper()
        if entry not in ("READY", "SETUP") or "ĐỨNG NGOÀI" in action or "STAND" in action:
            return "NO_ACTION"
        return "BUY" if direction == "LONG" else "SELL" if direction == "SHORT" else "NO_ACTION"

    def _build_unified_cycle_request(
        self,
        analysis,
        *,
        pipeline_run_id: str,
    ) -> UnifiedCycleRequest | None:
        if analysis is None:
            return None
        symbol = str(getattr(analysis, "symbol", "")).strip()
        timeframe = self.selection_state.timeframe or "15m"
        timeframes = getattr(analysis, "timeframes", {}) or {}
        tf_data = timeframes.get(timeframe) or timeframes.get("15m")
        close = float(
            getattr(tf_data, "close", 0.0)
            or getattr(getattr(analysis, "snapshot", None), "last_price", 0.0)
            or 0.0
        )
        if not symbol or close <= 0:
            return None
        return UnifiedCycleRequest(
            pipeline_run_id=pipeline_run_id,
            snapshot=UnifiedMarketSnapshot(
                symbol=symbol,
                timeframe=timeframe,
                close=close,
                features={
                    "legacy_long_score": (
                        float(getattr(analysis, "long_trend_score", 0.0))
                        + float(getattr(analysis, "long_entry_score", 0.0))
                    ) / 2.0,
                    "legacy_short_score": (
                        float(getattr(analysis, "short_trend_score", 0.0))
                        + float(getattr(analysis, "short_entry_score", 0.0))
                    ) / 2.0,
                    "legacy_confidence": max(
                        0.0,
                        min(
                            1.0,
                            float(getattr(analysis, "confidence_score", 0.0)) / 100.0,
                        ),
                    ),
                },
            ),
            quantity=1.0,
        )

    def _submit_core_shadow_cycle(self, analysis) -> None:
        if self.core_runtime_adapter is None or analysis is None:
            return
        revision = int(getattr(self.selection_state, "revision", 0))
        symbol = str(getattr(analysis, "symbol", "")).strip()
        cycle = self._build_unified_cycle_request(
            analysis,
            pipeline_run_id=f"gui-shadow:{symbol}:{revision}",
        )
        if cycle is None:
            return
        request = CoreCycleRequest(cycle=cycle, analysis_revision=revision)
        self._core_shadow_latest_request_id = request.request_id
        self._core_shadow_result = None
        self._core_shadow_failure = None
        self._render_core_shadow_comparison(analysis)
        try:
            self.core_runtime_adapter.run_cycle_async(request)
        except Exception as exc:
            logger.exception("Unable to queue Unified Core shadow cycle for %s", symbol)
            log_gui_exception(context="submit_core_shadow_cycle", symbol=symbol, exc=exc)
            self._core_shadow_failure = CoreCycleFailureViewModel(
                request_id=request.request_id,
                analysis_revision=revision,
                symbol=symbol,
                error_code="SHADOW_QUEUE_FAILED",
                message=f"{type(exc).__name__}: {exc}",
            )
            self._render_core_shadow_comparison(analysis)

    def _render_core_shadow_comparison(self, analysis=None) -> None:
        if not hasattr(self, "core_legacy_panel"):
            return
        analysis = analysis or self.current_analysis
        if analysis is None:
            return
        legacy = self._legacy_action_for_shadow(analysis)
        entry = str(getattr(getattr(analysis, "entry_status", None), "value", "WAIT"))
        confidence = float(getattr(analysis, "confidence_score", 0.0))
        self.core_legacy_panel.setText(f"LEGACY\nDecision: {legacy}\nEntry: {entry}\nConfidence: {confidence:.1f}")
        if self._core_shadow_failure is not None:
            failure = self._core_shadow_failure
            self.core_unified_panel.setText(f"UNIFIED CORE\nFAILED / UNAVAILABLE\n{failure.error_code}\nShadow only: YES")
            self.core_agreement_panel.setText("AGREEMENT\nNOT_EVALUATED")
            return
        result = self._core_shadow_result
        if result is None:
            self.core_unified_panel.setText("UNIFIED CORE\nRUNNING ASYNC...\nQuantity exposed: 0\nShadow only: YES")
            self.core_agreement_panel.setText("AGREEMENT\nPENDING")
            return
        unified = str(result.decision).upper()
        self.core_unified_panel.setText(
            f"UNIFIED CORE\nDecision: {unified}\nAuthorized: {result.authorized}\n"
            f"Ledger: {'VERIFIED (synthetic)' if result.ledger_verified else 'NOT_VERIFIED'}\n"
            f"Risk allowed: {result.risk_allowed}\nQuantity exposed: {result.quantity:.1f}"
        )
        agreement_result = classify_agreement_result(legacy, unified)
        metrics_text = ""
        if self.core_shadow_agreement_store is not None:
            try:
                metrics = self.core_shadow_agreement_store.metrics()
                metrics_text = (
                    f"\nQualification: {metrics.total_cycles}/{metrics.minimum_cycles} cycles"
                    f" · FULL {metrics.full_agreement_ratio * 100:.1f}%"
                    f" · UNSAFE {metrics.unsafe_divergences}"
                    f"\nStatus: {metrics.qualification_status}"
                )
                self._render_shadow_qualification_dashboard(metrics)
            except Exception as exc:
                logger.warning("Unable to read shadow agreement metrics: %s", exc)
        self.core_agreement_panel.setText(
            f"AGREEMENT\n{agreement_result.display}\nSeverity: {agreement_result.severity}\nObserve only\nPaper authority: LEGACY{metrics_text}"
        )

    def _set_text_if_changed(self, widget, cache_key: str, text: str) -> bool:
        value = str(text)
        if self._qualification_render_cache.get(cache_key) == value:
            return False
        self._qualification_render_cache[cache_key] = value
        widget.setText(value)
        return True

    def _render_shadow_qualification_dashboard(self, payload) -> dict:
        """V2.4.1: delta-only projection; all DB analytics arrive from worker."""
        if not hasattr(self, "core_qualification_progress"):
            return {"updated_widgets": 0, "unchanged_widgets": 0}
        metrics = payload.get("metrics") if isinstance(payload, dict) else payload
        analytics = payload.get("analytics") if isinstance(payload, dict) else None
        if metrics is None:
            return {"updated_widgets": 0, "unchanged_widgets": 0}
        updated = 0
        unchanged = 0
        minimum = max(1, int(metrics.minimum_cycles))
        progress = min(100, int(round(metrics.total_cycles * 100 / minimum)))
        if self.core_qualification_progress.value() != progress:
            self.core_qualification_progress.setValue(progress); updated += 1
        else: unchanged += 1
        texts = [
            (self.core_qualification_cycles, "cycles", f"CYCLES\n{metrics.total_cycles}/{metrics.minimum_cycles}"),
            (self.core_qualification_agreement, "agreement", f"FULL AGREEMENT\n{metrics.full_agreement_ratio * 100:.1f}% / {metrics.required_full_agreement_ratio * 100:.1f}%"),
            (self.core_qualification_unsafe, "unsafe", f"UNSAFE\n{metrics.unsafe_divergences} (hard gate)"),
            (self.core_qualification_profile, "profile", f"PROFILE\n{metrics.profile_id}\n{metrics.profile_hash[:12]}…"),
        ]
        for widget, key, text in texts:
            if self._set_text_if_changed(widget, key, text): updated += 1
            else: unchanged += 1
        status = str(metrics.qualification_status)
        status_color = {"COLLECTING":"#38bdf8","BELOW_AGREEMENT_THRESHOLD":"#facc15","BLOCKED_UNSAFE_DIVERGENCE":"#ef4444","ACTIONABLE_EVIDENCE_INSUFFICIENT":"#f97316","READY_FOR_GOVERNANCE_REVIEW":"#22c55e"}.get(status,"#94a3b8")
        status_text = f"QUALIFICATION STATUS: {status} · ACTIONABLE {metrics.actionable_cycles}/{metrics.required_actionable_cycles} · PAPER AUTHORITY: LEGACY"
        if self._set_text_if_changed(self.core_qualification_status, "status_text", status_text): updated += 1
        else: unchanged += 1
        style = f"font-weight:700;color:{status_color};padding:6px;"
        if self._qualification_render_cache.get("status_style") != style:
            self._qualification_render_cache["status_style"] = style
            self.core_qualification_status.setStyleSheet(style); updated += 1
        else: unchanged += 1
        if analytics is not None and hasattr(self, "core_qualification_analytics"):
            def top_lines(title, items, limit=4):
                values=list(items)[:limit]
                return f"{title}: chưa có dữ liệu" if not values else title+": "+" | ".join(f"{item.key} {item.full_ratio*100:.1f}% ({item.total})" for item in values)
            recent=" | ".join(f"{symbol}:{agreement}" for _,symbol,agreement in analytics.recent_timeline[:5]) or "chưa có"
            analytics_text=("QUALIFICATION ANALYTICS · OBSERVE ONLY\n"+top_lines("Theo coin",analytics.by_symbol)+"\n"+top_lines("Theo regime",analytics.by_regime)+"\n"+top_lines("Theo confidence",analytics.by_confidence_bucket)+f"\nRecent: {recent}\nUnsafe cases: {0 if not analytics.unsafe_cases else len(analytics.unsafe_cases)}")
            if self._set_text_if_changed(self.core_qualification_analytics,"analytics",analytics_text): updated += 1
            else: unchanged += 1
        self._qualification_evidence_dirty = True
        return {"updated_widgets": updated, "unchanged_widgets": unchanged}

    def _refresh_qualification_evidence(self) -> None:
        if self.core_shadow_agreement_store is None or not hasattr(self, "qualification_evidence_table"):
            return
        symbol = self.qualification_evidence_search.text().strip() if hasattr(self, "qualification_evidence_search") else ""
        agreement = self.qualification_evidence_filter.currentData() if hasattr(self, "qualification_evidence_filter") else ""
        try:
            records = self.core_shadow_agreement_store.list_evidence(
                symbol=symbol, agreement=str(agreement or ""), limit=250
            )
        except Exception as exc:
            logger.warning("Unable to load qualification evidence: %s", exc)
            return
        table = self.qualification_evidence_table
        table.blockSignals(True)
        try:
            table.setRowCount(len(records))
            self._qualification_evidence_records = {record.request_id: record for record in records}
            for row, record in enumerate(records):
                values = (
                    record.observed_at.replace("T", " ")[:19],
                    record.symbol,
                    record.agreement,
                    f"{record.confidence:.1f}",
                    record.regime,
                    record.integrity_status,
                    record.request_id,
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column == 6:
                        item.setData(Qt.ItemDataRole.UserRole, record.request_id)
                    table.setItem(row, column, item)
            if records:
                table.selectRow(0)
                self._show_qualification_evidence_detail(records[0])
            else:
                self.qualification_evidence_detail.setPlainText("Không có evidence phù hợp bộ lọc.")
        finally:
            table.blockSignals(False)

    @Slot()
    def _on_qualification_evidence_selected(self) -> None:
        table = self.qualification_evidence_table
        row = table.currentRow()
        if row < 0:
            return
        item = table.item(row, 6)
        request_id = str(item.data(Qt.ItemDataRole.UserRole) or item.text()) if item is not None else ""
        record = getattr(self, "_qualification_evidence_records", {}).get(request_id)
        if record is not None:
            self._show_qualification_evidence_detail(record)

    def _show_qualification_evidence_detail(self, record) -> None:
        reasons = "\n".join(f"  - {code}" for code in record.reason_codes) or "  - none"
        events = "\n".join(f"  - {name}" for name in record.event_names) or "  - none"
        text = (
            f"EVIDENCE RECORD · {record.request_id}\n"
            f"Timestamp: {record.observed_at}\n"
            f"Symbol: {record.symbol}\n"
            f"Timeframe/Regime/Phase: {record.timeframe} / {record.regime} / {record.phase}\n"
            f"Legacy: {record.legacy_action}\n"
            f"Unified: {record.unified_action}\n"
            f"Agreement: {record.agreement}\n"
            f"Confidence: {record.confidence:.2f}\n"
            f"Authorized: {record.authorized}\n"
            f"Risk allowed: {record.risk_allowed}\n"
            f"Quantity exposed: {record.quantity:.4f}\n"
            f"Ledger: {'VERIFIED (synthetic)' if record.ledger_verified else 'NOT VERIFIED'}\n"
            f"Ledger hash: {record.ledger_hash or '-'}\n"
            f"Profile hash: {record.profile_hash}\n"
            f"Evidence hash: {record.evidence_hash or '-'}\n"
            f"Integrity: {record.integrity_status}\n\n"
            f"Reason codes:\n{reasons}\n\n"
            f"Events:\n{events}"
        )
        self.qualification_evidence_detail.setPlainText(text)
        # Performance 4.0.4: do not build replay/graph while scanning or merely
        # selecting an evidence row. Keep only the selected immutable record and
        # construct the replay on demand when the Replay workspace is opened.
        self._qualification_replay_pending_record = record
        self._qualification_replay_dirty = True

    @Slot(int)
    def _on_core_workspace_changed(self, index: int) -> None:
        """Lazy-load expensive read-only projections only when visible.

        Evidence list queries/table population and replay graph construction are
        intentionally excluded from the scan completion path.
        """
        if not hasattr(self, "core_workspace_tabs"):
            return
        label = self.core_workspace_tabs.tabText(index)
        if label == "Evidence" and getattr(self, "_qualification_evidence_dirty", True):
            self._refresh_qualification_evidence()
            self._qualification_evidence_dirty = False
            return
        if label == "Replay" and getattr(self, "_qualification_replay_dirty", False):
            record = getattr(self, "_qualification_replay_pending_record", None)
            if record is not None:
                self._load_qualification_replay(record)
                self._qualification_replay_dirty = False

    def _load_qualification_replay(self, record) -> None:
        if not hasattr(self, "qualification_replay_steps"):
            return
        session = QualificationReplayService().build(record)
        self._qualification_replay_session = session
        self._qualification_replay_index = 0
        self.qualification_replay_title.setText(
            f"REPLAY · {session.symbol} · {session.request_id}"
        )
        self.qualification_replay_integrity.setText(
            f"INTEGRITY: {session.integrity_status} · {session.final_verdict}"
        )
        self._populate_qualification_decision_graph(session)
        self.qualification_replay_steps.clear()
        for step in session.steps:
            self.qualification_replay_steps.addItem(
                f"{step.index:02d}  {step.title}  [{step.status}]"
            )
        if session.steps:
            self.qualification_replay_steps.setCurrentRow(0)
            self._show_qualification_replay_step(0)
        self.qualification_replay_progress.setRange(0, max(1, len(session.steps)))
        self.qualification_replay_progress.setValue(1 if session.steps else 0)
        self.qualification_replay_progress.setFormat(
            f"STEP 1/{len(session.steps)}" if session.steps else "NO REPLAY"
        )

    def _populate_qualification_decision_graph(self, session) -> None:
        if not hasattr(self, "qualification_decision_graph"):
            return
        tree = self.qualification_decision_graph
        tree.clear()
        root = QTreeWidgetItem([f"{session.symbol} · DECISION GRAPH", session.final_verdict, ""])
        root.setExpanded(True)
        tree.addTopLevelItem(root)
        for node in session.graph_nodes:
            contribution = f"{node.contribution:.1f}" if node.contribution > 0 else "—"
            item = QTreeWidgetItem([f"{node.index:02d} · {node.label}", node.status, contribution])
            item.setData(0, Qt.ItemDataRole.UserRole, node.index - 1)
            root.addChild(item)
        tree.expandAll()
        self._populate_qualification_confidence_breakdown(session)
        if root.childCount():
            tree.setCurrentItem(root.child(0))
            self._show_qualification_decision_node(0)

    def _populate_qualification_confidence_breakdown(self, session) -> None:
        table = getattr(self, "qualification_confidence_breakdown", None)
        if table is None:
            return
        weighted = [node for node in session.graph_nodes if node.contribution > 0]
        table.setRowCount(len(weighted) + 1)
        total = 0.0
        for row, node in enumerate(weighted):
            total += node.contribution
            values = (node.category, node.source, node.status, f"{node.contribution:.2f}")
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, node.index - 1)
                table.setItem(row, column, item)
        summary = ("TOTAL DESCRIPTIVE", "PERSISTED", "READ ONLY", f"{total:.2f}")
        for column, value in enumerate(summary):
            table.setItem(len(weighted), column, QTableWidgetItem(str(value)))

    def _show_qualification_decision_node(self, index: int) -> None:
        session = getattr(self, "_qualification_replay_session", None)
        if session is None or not session.graph_nodes:
            return
        index = max(0, min(index, len(session.graph_nodes) - 1))
        node = session.graph_nodes[index]
        contribution = f"{node.contribution:.2f}" if node.contribution > 0 else "Không áp dụng"
        self.qualification_decision_inspector.setPlainText(
            f"NODE {node.index}/{len(session.graph_nodes)}\n\n"
            f"{node.label}\n"
            f"Category: {node.category}\n"
            f"Source: {node.source}\n"
            f"Status: {node.status}\n"
            f"Confidence contribution: {contribution}\n\n"
            "EVIDENCE\n"
            f"{node.detail}\n\n"
            "INTERPRETATION\n"
            f"{node.interpretation or 'Không có diễn giải bổ sung.'}\n\n"
            "SCIENTIFIC NOTE\n"
            "Contribution là phân bổ mô tả từ confidence đã lưu; không phải trọng số giao dịch mới, "
            "không nội suy giá trị chỉ báo bị thiếu và không thay đổi quyết định gốc."
        )

    @Slot()
    def _on_qualification_decision_node_selected(self) -> None:
        item = self.qualification_decision_graph.currentItem()
        if item is None:
            return
        index = item.data(0, Qt.ItemDataRole.UserRole)
        if index is not None:
            self._show_qualification_decision_node(int(index))

    def _show_qualification_replay_step(self, index: int) -> None:
        session = getattr(self, "_qualification_replay_session", None)
        if session is None or not session.steps:
            return
        index = max(0, min(index, len(session.steps) - 1))
        self._qualification_replay_index = index
        step = session.steps[index]
        self.qualification_replay_steps.blockSignals(True)
        self.qualification_replay_steps.setCurrentRow(index)
        self.qualification_replay_steps.blockSignals(False)
        self.qualification_replay_detail.setPlainText(
            f"STEP {step.index}/{len(session.steps)}\n\n"
            f"{step.title}\nStatus: {step.status}\n\n{step.detail}"
        )
        self.qualification_replay_progress.setValue(index + 1)
        self.qualification_replay_progress.setFormat(
            f"STEP {index + 1}/{len(session.steps)} · {step.status}"
        )

    @Slot()
    def _qualification_replay_previous(self) -> None:
        self._show_qualification_replay_step(
            int(getattr(self, "_qualification_replay_index", 0)) - 1
        )

    @Slot()
    def _qualification_replay_next(self) -> None:
        self._show_qualification_replay_step(
            int(getattr(self, "_qualification_replay_index", 0)) + 1
        )

    @Slot()
    def _qualification_replay_reset(self) -> None:
        self._show_qualification_replay_step(0)

    @Slot()
    def _qualification_replay_auto(self) -> None:
        session = getattr(self, "_qualification_replay_session", None)
        if session is None or not session.steps:
            return
        if self.qualification_replay_timer.isActive():
            self.qualification_replay_timer.stop()
            self.qualification_replay_auto_btn.setText("Auto Replay")
        else:
            if int(getattr(self, "_qualification_replay_index", 0)) >= len(session.steps) - 1:
                self._show_qualification_replay_step(0)
            self.qualification_replay_timer.start(850)
            self.qualification_replay_auto_btn.setText("Dừng Replay")

    @Slot()
    def _qualification_replay_tick(self) -> None:
        session = getattr(self, "_qualification_replay_session", None)
        if session is None:
            self.qualification_replay_timer.stop()
            return
        current = int(getattr(self, "_qualification_replay_index", 0))
        if current >= len(session.steps) - 1:
            self.qualification_replay_timer.stop()
            self.qualification_replay_auto_btn.setText("Auto Replay")
            return
        self._show_qualification_replay_step(current + 1)

    @Slot()
    def _on_qualification_replay_step_selected(self) -> None:
        row = self.qualification_replay_steps.currentRow()
        if row >= 0:
            self._show_qualification_replay_step(row)

    @Slot()
    def _export_qualification_evidence_json(self) -> None:
        if self.core_shadow_agreement_store is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Qualification Evidence JSON", "qualification_evidence.json", "JSON (*.json)")
        if not path:
            return
        count = self.core_shadow_agreement_store.export_evidence_json(
            path, symbol=self.qualification_evidence_search.text().strip(),
            agreement=str(self.qualification_evidence_filter.currentData() or ""), limit=5000
        )
        self.status.setText(f"Đã export {count} evidence records ra JSON")

    @Slot()
    def _export_scientific_qualification_report(self) -> None:
        if self.core_shadow_agreement_store is None:
            QMessageBox.warning(self, "Scientific Report", "Qualification store chưa sẵn sàng.")
            return
        directory = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu Scientific Qualification Report")
        if not directory:
            return
        try:
            service = QualificationReportService(self.core_shadow_agreement_store, build_version=APP_VERSION)
            base = Path(directory) / f"DVS_AI_Qualification_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            service.export_json(base.with_suffix(".json"))
            service.export_html(base.with_suffix(".html"))
            service.export_pdf(base.with_suffix(".pdf"))
            QMessageBox.information(
                self, "Scientific Report",
                f"Đã xuất bộ báo cáo read-only:\n{base.with_suffix('.json')}\n{base.with_suffix('.html')}\n{base.with_suffix('.pdf')}\n\nPaper Authority vẫn là LEGACY."
            )
        except Exception as exc:
            logger.exception("Unable to export scientific qualification report")
            QMessageBox.warning(self, "Scientific Report", str(exc))

    def _export_qualification_evidence_csv(self) -> None:
        if self.core_shadow_agreement_store is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Qualification Evidence CSV", "qualification_evidence.csv", "CSV (*.csv)")
        if not path:
            return
        count = self.core_shadow_agreement_store.export_evidence_csv(
            path, symbol=self.qualification_evidence_search.text().strip(),
            agreement=str(self.qualification_evidence_filter.currentData() or ""), limit=5000
        )
        self.status.setText(f"Đã export {count} evidence records ra CSV")

    @Slot(object)
    def _on_core_shadow_completed(self, result: CoreCycleResultViewModel) -> None:
        if result.request_id != self._core_shadow_latest_request_id:
            return
        if self.selection_state.symbol and result.symbol != self.selection_state.symbol:
            return
        if result.analysis_revision != int(getattr(self.selection_state, "revision", -1)):
            return
        self._core_shadow_result = result
        self._core_shadow_failure = None
        analysis = self.current_analysis
        if analysis is not None and self.core_shadow_agreement_store is not None:
            try:
                legacy = self._legacy_action_for_shadow(analysis)
                unified = str(result.decision).upper()
                agreement_result = classify_agreement_result(legacy, unified)
                self.core_shadow_agreement_store.append(
                    ShadowAgreementObservation(
                        request_id=result.request_id,
                        symbol=result.symbol,
                        analysis_revision=result.analysis_revision,
                        legacy_action=legacy,
                        unified_action=unified,
                        agreement=agreement_result.code,
                        ledger_verified=bool(result.ledger_verified),
                        synthetic_lifecycle=True,
                    )
                )
            except Exception as exc:
                logger.warning("Unable to persist shadow agreement observation: %s", exc)
        self._render_core_shadow_comparison()

    @Slot(object)
    def _on_core_shadow_failed(self, failure: CoreCycleFailureViewModel) -> None:
        if failure.request_id != self._core_shadow_latest_request_id:
            return
        self._core_shadow_failure = failure
        self._core_shadow_result = None
        self._render_core_shadow_comparison()

    @Slot(str)
    def _on_core_shadow_stale(self, request_id: str) -> None:
        logger.debug("Discarded stale Unified Core GUI result: %s", request_id)

    def _render_microstructure_analysis(self, best_analysis) -> None:
        plain_view = self.plain_language_presenter.build(best_analysis)
        self.micro_summary.setHtml(self._plain_view_html(plain_view, "Smart Money nói gì?"))
        micro = best_analysis.microstructure
        footprint = getattr(best_analysis, "footprint", None)
        detail = [
            f"Coin: {best_analysis.symbol}",
            f"AI Reasoning: {getattr(best_analysis, 'reasoning_headline', '-')}",
            f"Decision Quality: {getattr(best_analysis, 'decision_quality_score', 0.0):.1f}/100",
            f"Opportunity: #{getattr(best_analysis, 'opportunity_rank', 999)} · "
            f"{getattr(best_analysis, 'opportunity_score', 0.0):.1f}/100 · "
            f"P{getattr(best_analysis, 'opportunity_percentile', 0.0):.0f}",
            f"Opportunity breakdown: "
            f"{getattr(best_analysis, 'opportunity_base_score', 0.0):.1f} "
            f"+{getattr(best_analysis, 'opportunity_bonus', 0.0):.1f} "
            f"-{getattr(best_analysis, 'opportunity_penalty', 0.0):.1f} · "
            f"{getattr(best_analysis, 'opportunity_penalty_reason', 'NONE')}",
            f"Decision: {best_analysis.direction} · "
            f"{best_analysis.entry_status.value}",
            f"Footprint raw/context: "
            f"{getattr(best_analysis, 'footprint_raw_score', 0.0):.1f}/"
            f"{getattr(best_analysis, 'footprint_score', 0.0):.1f}",
            f"Confirmation: "
            f"{getattr(best_analysis, 'footprint_confirmation_depth', 'NONE')}",
            f"Alignment: "
            f"{getattr(best_analysis, 'footprint_direction_alignment', 'NOT_APPLIED')}",
            f"Gate: {getattr(best_analysis, 'footprint_gate', 'NOT_APPLIED')}",
            f"Position Building: "
            f"{getattr(best_analysis, 'position_building_score', 0.0):.1f} · "
            f"{getattr(best_analysis, 'position_building_regime', 'UNKNOWN')}",
            f"Persistence/Acceleration/Confidence: "
            f"{getattr(best_analysis, 'position_persistence_score', 0.0):.1f}/"
            f"{getattr(best_analysis, 'position_acceleration_score', 0.0):.1f}/"
            f"{getattr(best_analysis, 'position_confidence_score', 0.0):.1f}",
            f"Footprint Chain: "
            f"{getattr(best_analysis, 'footprint_chain_text', 'NO_CONFIRMED_CHAIN')}",
            "",
            "COMPOSITE EXHAUSTION · OBSERVE ONLY",
            f"Distribution progress: {getattr(best_analysis, 'composite_distribution_progress', 0.0):.1f}/100",
            f"Selling pressure: {getattr(best_analysis, 'composite_selling_pressure', 0.0):.1f}/100",
            f"Exhaustion: {getattr(best_analysis, 'composite_exhaustion_score', 0.0):.1f}/100",
            f"Bottom-formation evidence: {getattr(best_analysis, 'bottom_formation_probability', 0.0):.1f}/100",
            f"Bottom state: {getattr(best_analysis, 'bottom_formation_state', 'NOT_EVALUATED')}",
            f"Composite timeline: {' → '.join(getattr(best_analysis, 'composite_timeline', ()) or ('NONE',))}",
            "This module cannot create an entry or identify an exact bottom price.",
            "",
            "AI MARKET STORY · OBSERVE ONLY",
            *(getattr(getattr(best_analysis, "explainable_narrative", None), "market_story", ()) or ("Narrative not available",)),
            "",
            "SMART MONEY STORY",
            *(getattr(getattr(best_analysis, "explainable_narrative", None), "smart_money_story", ()) or ("Narrative not available",)),
            "",
            "WHY WAIT / BLOCKERS",
            *(getattr(best_analysis, "explainable_blockers", ()) or ("No explicit blocker",)),
            "",
            "NEXT CONFIRMATION",
            *(getattr(best_analysis, "explainable_next_confirmation", ()) or ("Continue observing",)),
            "",
            "FOOTPRINT EXPLANATION",
        ]
        exhaustion = getattr(best_analysis, "composite_exhaustion", None)
        if exhaustion is not None:
            detail.extend(str(line) for line in getattr(exhaustion, "explanation", ()))
            detail.append("")
        if footprint is not None:
            detail.extend(
                str(line)
                for line in getattr(
                    footprint,
                    "explanation",
                    (),
                )
            )
        detail.extend((
            "",
            "MICROSTRUCTURE EXPLANATION",
            *micro.explanation,
        ))
        self.micro_detail.setPlainText("\n".join(detail))

    def _build_paper_trade_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(6)

        top = QHBoxLayout()
        self.paper_summary = QLabel("MAIN + SHADOW PAPER LAB")
        self.paper_summary.setObjectName("PaperSummary")
        self.auto_paper_btn = QPushButton("AUTO PAPER: OFF")
        self.auto_paper_btn.setCheckable(True)
        self.auto_paper_btn.toggled.connect(self.toggle_auto_paper)
        update_btn = QPushButton("Cập nhật kết quả lệnh")
        update_btn.clicked.connect(self.update_paper_trades)
        refresh_btn = QPushButton("Làm mới bảng")
        refresh_btn.clicked.connect(self.refresh_paper_trade_tab)
        top.addWidget(self.paper_summary)
        top.addStretch()
        top.addWidget(self.auto_paper_btn)
        top.addWidget(update_btn)
        top.addWidget(refresh_btn)
        layout.addLayout(top)

        limits = QLabel(
            "MAIN: READY · Conf ≥70 · Entry ≥65 · Risk ≤50 · R:R ≥1.8 "
            "(25 Long + 25 Short).  |  "
            "SHADOW: SETUP/READY · Conf ≥55 · Entry ≥50 · Risk ≤60 · "
            "R:R ≥1.5 (50 Long + 50 Short)."
        )
        limits.setWordWrap(True)
        limits.setStyleSheet("color:#94a3b8;padding:4px;")
        layout.addWidget(limits)

        self.paper_diagnostics = QLabel("Paper runtime: chưa có diagnostics")
        self.paper_diagnostics.setWordWrap(True)
        self.paper_diagnostics.setStyleSheet("color:#94a3b8;padding:3px 5px;")
        layout.addWidget(self.paper_diagnostics)

        self.paper_table = QTableWidget(0, 21)
        self.paper_table.setHorizontalHeaderLabels([
            "ID","Lab","Thời gian","Coin","Hướng","Nguồn","Trạng thái",
            "Entry Low","Entry High","Giá khớp","Invalid","TP1","TP2",
            "Confidence","Entry","Risk","Kết quả","R","MFE(R)","MAE(R)",
            "Slip %"
        ])
        self.paper_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.paper_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.paper_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.paper_table.itemSelectionChanged.connect(
            self._select_paper_symbol
        )
        self.paper_table.verticalHeader().setVisible(False)
        # V2.3.1: ResizeToContents caused repeated full-column measurement during
        # chunked QTableWidget commits. Keep stable interactive widths instead.
        paper_header = self.paper_table.horizontalHeader()
        paper_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        paper_header.setStretchLastSection(True)
        paper_widths = (58, 78, 142, 104, 72, 178, 92, 94, 94, 94, 94, 94, 94, 86, 72, 72, 110, 72, 78, 78, 72)
        for column, width in enumerate(paper_widths):
            paper_header.resizeSection(column, width)
        layout.addWidget(self.paper_table)

        self.tabs.addTab(tab, "Paper Trade")
        self.refresh_paper_trade_tab()

    def toggle_auto_paper(self, enabled):
        self.auto_paper_enabled = bool(enabled)
        self.auto_paper_btn.setText(
            "AUTO PAPER: ON" if enabled else "AUTO PAPER: OFF"
        )
        self.status.setText(
            "Đã bật Auto Paper Trade."
            if enabled else "Đã tắt Auto Paper Trade."
        )

    def create_manual_paper_trade(self, direction):
        if self.current_analysis is None:
            QMessageBox.warning(
                self, "Chưa chọn coin",
                "Hãy chọn một coin trong Dashboard trước."
            )
            return
        ok, message = self.paper_trade_service.create_trade(
            self.current_analysis,
            direction,
            source="MANUAL",
            enforce_thresholds=True,
            lab="MAIN",
        )
        if ok:
            QMessageBox.information(self, "Paper Trade", message)
        else:
            QMessageBox.warning(self, "Không tạo được lệnh", message)
        self.refresh_paper_trade_tab()

    def update_paper_trades(self):
        # RC6: network/database resolution must never run on the GUI thread.
        self.status.setText("Đang xếp hàng cập nhật Paper Trade...")
        self.outcome_resolution_coordinator.request_resolution()


    def refresh_paper_trade_tab(self, *args, **kwargs):
        self._submit_data_prepare("paper", str(kwargs.get("reason", "refresh_paper_trade_tab")))

    def _submit_data_prepare(self, owner: str, reason: str) -> None:
        if self.is_closing:
            return
        state=self._data_prepare_state[owner]
        state["generation"] += 1
        generation=int(state["generation"])
        request={"generation":generation,"reason":str(reason)}
        if owner == "history":
            request["db_path"]=str(self.history_service.db_path)
        else:
            request.update({"db_path":str(self.paper_trade_service.db_path),
                "main_pilot_id":str(self.paper_trade_service.MAIN_PILOT_ID),
                "shadow_pilot_id":str(self.paper_trade_service.SHADOW_PILOT_ID),
                "diagnostics":dict(getattr(self.paper_trade_service,"_diagnostics",{}))})
        self._write_data_prepare_event(owner,generation,reason,"prepare_submitted",pending=bool(state["running"]))
        if state["running"]:
            state["pending"]=request
            return
        state["running"]=True
        self._emit_data_prepare(owner,request)

    def _queued_pipeline_enabled(self, pipeline: str) -> bool:
        """Return the RC7.12 per-pipeline startup gate state."""
        states = getattr(self, "_queued_signal_pipeline_enabled", None)
        if not isinstance(states, dict):
            # Backward-compatible fallback for partially initialized startup.
            return bool(getattr(self, "_queued_signal_pipelines_enabled", True))
        return bool(states.get(str(pipeline), False))

    def _emit_data_prepare(self, owner, request):
        if not self._queued_pipeline_enabled(owner):
            self._write_data_prepare_event(
                owner,
                request["generation"],
                request["reason"],
                "pipeline_disabled_self_test_failed",
                pipeline_enabled=False,
                gate_scope="per_pipeline",
            )
            self._record_signal_path_event(
                owner,
                "pipeline_disabled_self_test_failed",
                generation=int(request["generation"]),
                gate_scope="per_pipeline",
                enabled_states=dict(getattr(self, "_queued_signal_pipeline_enabled", {})),
            )
            self._data_prepare_state[owner]["running"] = False
            return
        self._record_signal_path_event(owner, "gui_before_emit",
                                       generation=int(request["generation"]),
                                       request_reason=str(request["reason"]))
        if owner == "history":
            self._history_prepare_requested.emit(request["generation"],request["reason"],request)
        else:
            self._paper_prepare_requested.emit(request["generation"],request["reason"],request)
        self._record_signal_path_event(owner, "gui_after_emit",
                                       generation=int(request["generation"]),
                                       request_reason=str(request["reason"]))

    def _write_data_prepare_event(self, owner, generation, reason, event, **extra):
        row={"schema_version":"dvs.runtime.gui_data_prepare.v2","timestamp_utc":datetime.utcnow().isoformat(timespec="milliseconds")+"Z",
             "runtime_session_id":self._runtime_session_id,"pid":os.getpid(),"event":event,"owner":owner,
             "generation":int(generation),"request_reason":str(reason),**extra}
        self._append_rc63_jsonl("gui_data_prepare.jsonl",row)

    def _record_signal_path_event(self, pipeline: str, event: str, **extra) -> None:
        try:
            from dvs_ai.diagnostics.shutdown_probe import get_shutdown_probe
            _probe = get_shutdown_probe()
            if _probe is not None:
                _probe.record_current_thread_mapping(pipeline, event, source="gui_signal_path")
        except Exception:
            pass
        row = {
            "schema_version": "dvs.runtime.signal_path_forensics.v1",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="microseconds") + "Z",
            "runtime_session_id": getattr(self, "_runtime_session_id", None),
            "pid": os.getpid(),
            "pipeline": str(pipeline),
            "event": str(event),
            "thread_ident": threading.get_ident(),
            "thread_name": QThread.currentThread().objectName(),
            "main_window_class": type(self).__name__,
            "main_window_object_id": hex(id(self)),
        }
        row.update(extra)
        self._append_rc63_jsonl("signal_path_forensics.jsonl", row)

    def _record_signal_connection(self, pipeline: str, signal_name: str, worker, thread) -> None:
        self._record_signal_path_event(
            pipeline, "signal_connection_completed", signal_name=signal_name,
            sender_class=type(self).__name__, sender_object_id=hex(id(self)),
            receiver_class=type(worker).__name__, receiver_object_id=hex(id(worker)),
            receiver_qthread_object_id=hex(id(thread)),
            receiver_thread_name=thread.objectName(),
            worker_affinity_thread_name=worker.thread().objectName(),
            connect_after_move_to_thread=(worker.thread() is thread),
            connection_type="QueuedConnection",
        )

    def _start_queued_signal_self_test(self) -> None:
        state = getattr(self, "_queued_signal_self_test", None)
        if not state or state.get("started") or self.is_closing:
            return
        state["started"] = True
        token = state["token"]
        self._record_signal_path_event("startup_gate", "self_test_started", token=token,
                                       deadline_ms=state["deadline_ms"])
        self._record_signal_connection("history", "_history_prepare_requested",
                                       self._history_prepare_worker, self._history_prepare_thread)
        self._record_signal_connection("paper", "_paper_prepare_requested",
                                       self._paper_prepare_worker, self._paper_prepare_thread)
        self._record_signal_connection("auto_paper", "_auto_paper_work_requested",
                                       self._auto_paper_worker, self._auto_paper_worker_thread)
        reason = f"__queued_signal_probe__:{token}"
        probe_request = {"__queued_signal_probe__": True, "token": token}
        self._record_signal_path_event("history", "gui_before_emit", token=token,
                                       generation=-1, sender_class=type(self).__name__,
                                       receiver_class=type(self._history_prepare_worker).__name__)
        self._history_prepare_requested.emit(-1, reason, probe_request)
        self._record_signal_path_event("history", "gui_after_emit", token=token, generation=-1)
        self._record_signal_path_event("paper", "gui_before_emit", token=token,
                                       generation=-1, sender_class=type(self).__name__,
                                       receiver_class=type(self._paper_prepare_worker).__name__)
        self._paper_prepare_requested.emit(-1, reason, probe_request)
        self._record_signal_path_event("paper", "gui_after_emit", token=token, generation=-1)
        capture_key = f"__queued_signal_probe__:{token}"
        self._record_signal_path_event("auto_paper", "gui_before_emit", token=token,
                                       payload_id=capture_key, sender_class=type(self).__name__,
                                       receiver_class=type(self._auto_paper_worker).__name__)
        self._auto_paper_work_requested.emit(
            {"__queued_signal_probe__": True, "token": token},
            capture_key,
            None,
            False,
        )
        self._record_signal_path_event("auto_paper", "gui_after_emit", token=token,
                                       payload_id=capture_key)
        QTimer.singleShot(int(state["deadline_ms"]), self._finish_queued_signal_self_test)

    def _mark_queued_signal_probe_received(self, pipeline: str, token: str, **extra) -> None:
        state = getattr(self, "_queued_signal_self_test", None)
        if not state or str(token) != str(state.get("token")):
            return
        state["received"].add(str(pipeline))
        self._record_signal_path_event(pipeline, "gui_result_slot_entered", token=token, **extra)
        if state["received"] >= state["expected"]:
            self._finish_queued_signal_self_test()

    def _finish_queued_signal_self_test(self) -> None:
        state = getattr(self, "_queued_signal_self_test", None)
        if not state or state.get("finished"):
            return
        state["finished"] = True
        expected = set(state["expected"])
        received = set(state["received"])
        missing = sorted(expected - received)
        state["passed"] = not missing

        # RC7.12: evaluate each signal path independently.
        per_pipeline = {
            pipeline: (pipeline in received)
            for pipeline in sorted(expected)
        }
        self._queued_signal_pipeline_enabled = dict(per_pipeline)
        self._queued_signal_pipelines_enabled = all(per_pipeline.values())

        event = "self_test_passed" if not missing else "QUEUED_SIGNAL_SELF_TEST_PARTIAL_FAILURE"
        self._record_signal_path_event(
            "startup_gate",
            event,
            token=state["token"],
            received=sorted(received),
            missing=missing,
            per_pipeline_enabled=dict(per_pipeline),
            all_pipelines_enabled=bool(self._queued_signal_pipelines_enabled),
            gate_scope="per_pipeline",
        )
        _write_auto_paper_pipeline_event(
            "self_test_gate_resolved",
            token=str(state["token"]),
            received=sorted(received),
            missing=missing,
            per_pipeline_enabled=dict(per_pipeline),
            auto_paper_enabled=bool(per_pipeline.get("auto_paper", False)),
        )

        if missing:
            try:
                # Surface the failed path(s) without implying healthy paths
                # have been disabled.
                healthy = [p for p, enabled in per_pipeline.items() if enabled]
                self.status.setText(
                    "QUEUED SIGNAL SELF-TEST PARTIAL: "
                    + "FAIL " + ", ".join(missing)
                    + (" · PASS " + ", ".join(healthy) if healthy else "")
                )
            except Exception:
                pass

    def _complete_prepare(self, owner, generation, reason, payload, timing):
        state=self._data_prepare_state[owner]
        latest=int(state["generation"]); stale=int(generation)!=latest
        self._write_data_prepare_event(owner,generation,reason,"prepare_completed",
            query_ms=round(float(timing.get("query_ms",0)),3),transform_ms=round(float(timing.get("transform_ms",0)),3),
            data_prepare_ms=round(float(timing.get("data_prepare_ms",0)),3),thread_name=timing.get("thread_name"),
            failure_type=timing.get("failure_type"),stale_payload=stale,row_count=len(payload.get("rows",[])))
        state["running"]=False
        if not stale and not timing.get("failure_type") and not self.is_closing:
            if owner == "history": self._begin_history_commit(generation,reason,payload)
            else: self._begin_paper_commit(generation,reason,payload)
        elif stale:
            self._write_data_prepare_event(owner,generation,reason,"stale_payload_rejected",stale_payload=True)
        pending=state.get("pending"); state["pending"]=None
        if pending is not None and not self.is_closing:
            state["running"]=True; self._emit_data_prepare(owner,pending)

    @Slot(int,str,object,object)
    def _on_history_prepared(self,generation,reason,payload,timing):
        if str(reason).startswith("__queued_signal_probe__:"):
            token=str(reason).split(":",1)[1]
            self._record_signal_path_event("history", "worker_result_received", token=token,
                                           worker_thread_name=dict(timing or {}).get("thread_name"))
            self._mark_queued_signal_probe_received("history", token, generation=int(generation))
            return
        self._complete_prepare("history",generation,reason,dict(payload or {}),dict(timing or {}))

    @Slot(int,str,object,object)
    def _on_paper_prepared(self,generation,reason,payload,timing):
        if str(reason).startswith("__queued_signal_probe__:"):
            token=str(reason).split(":",1)[1]
            self._record_signal_path_event("paper", "worker_result_received", token=token,
                                           worker_thread_name=dict(timing or {}).get("thread_name"))
            self._mark_queued_signal_probe_received("paper", token, generation=int(generation))
            return
        self._complete_prepare("paper",generation,reason,dict(payload or {}),dict(timing or {}))

    def _record_gui_commit(self,owner,generation,reason,started,row_count,chunk_index,final_chunk):
        ms=(time.perf_counter()-started)*1000.0
        self._write_data_prepare_event(owner,generation,reason,"gui_commit",
            gui_commit_ms=round(ms,3),budget_ms=25.0,budget_exceeded=ms>25.0,
            row_count=int(row_count),chunk_index=int(chunk_index),final_chunk=bool(final_chunk),
            thread_name=QThread.currentThread().objectName())

    def _begin_paper_commit(self,generation,reason,payload):
        if generation != self._data_prepare_state["paper"]["generation"]: return
        started=time.perf_counter(); main=payload["main"]; shadow=payload["shadow"]; diag=payload["diagnostics"]
        mpf="∞" if math.isinf(main["profit_factor"]) else f"{main['profit_factor']:.2f}"
        spf="∞" if math.isinf(shadow["profit_factor"]) else f"{shadow['profit_factor']:.2f}"
        self.paper_summary.setText(f"MAIN L {main['longs']}/{self.config.main_long_limit} · S {main['shorts']}/{self.config.main_short_limit} · WR {main['win_rate']:.1f}% · AvgR {main['avg_r']:+.2f} · PF {mpf} · Amb {main.get('ambiguous',0)} · Exp {main.get('expired',0)}   ||   SHADOW L {shadow['longs']}/{self.config.shadow_long_limit} · S {shadow['shorts']}/{self.config.shadow_short_limit} · WR {shadow['win_rate']:.1f}% · AvgR {shadow['avg_r']:+.2f} · PF {spf} · Amb {shadow.get('ambiguous',0)} · Exp {shadow.get('expired',0)}")
        self.paper_diagnostics.setText("Paper runtime · "+f"evaluated {diag.get('evaluated',0)} · MAIN eligible {diag.get('main_eligible',0)} · SHADOW eligible {diag.get('shadow_eligible',0)} · created {diag.get('created',0)} · gate blocked {diag.get('gate_blocked',0)} · duplicate blocked {diag.get('duplicate_blocked',0)} · capacity blocked {diag.get('capacity_blocked',0)} · active {diag.get('active_trades',0)} · last {diag.get('last_trade_created_at') or '—'}")
        self.paper_table.setUpdatesEnabled(False); self.paper_table.blockSignals(True); self.paper_table.setRowCount(len(payload["rows"])); self.paper_table.blockSignals(False); self.paper_table.setUpdatesEnabled(True)
        self._paper_render_state={"generation":generation,"reason":reason,"rows":payload["rows"],"raw":payload.get("raw_rows",[]),"index":0,"chunk":0,"scheduled_ns":time.monotonic_ns()}
        self._record_gui_commit("paper",generation,reason,started,0,0,not payload["rows"])
        QTimer.singleShot(0,self._commit_paper_chunk)

    @_audit_gui_callback("paper_trade_chunk_commit", record_threshold_ms=100.0)
    def _commit_paper_chunk(self):
        callback_entry_ns = time.monotonic_ns()
        st = self._paper_render_state
        if (
            not st
            or st["generation"] != self._data_prepare_state["paper"]["generation"]
            or self.is_closing
        ):
            return

        scheduled_ns = int(st.get("scheduled_ns") or callback_entry_ns)
        queue_wait_ms = max(0.0, (callback_entry_ns - scheduled_ns) / 1_000_000.0)
        qt_started_ns = time.perf_counter_ns()
        begin = int(st["index"])
        table = self.paper_table
        spans = {}
        slow_ops = []
        set_item_total_ns = 0
        set_foreground_total_ns = 0
        max_set_item_ns = 0
        max_foreground_ns = 0
        slowest = None
        created_items = 0
        updated_cells = 0
        unchanged_cells = 0
        rows_committed = 0
        # Time-budgeted commit: yield after a completed row once the GUI budget is spent.
        commit_budget_ns = 10_000_000
        max_rows_per_turn = 12

        sorting_was_enabled = bool(table.isSortingEnabled())
        updates_were_enabled = bool(table.updatesEnabled())
        signals_were_blocked = bool(table.signalsBlocked())
        selected_row_before = int(table.currentRow())
        row_count_before = int(table.rowCount())

        def span(name, fn, row=None, col=None):
            nonlocal slowest
            t0 = time.perf_counter_ns()
            result = fn()
            dt = time.perf_counter_ns() - t0
            spans[name] = spans.get(name, 0) + dt
            if slowest is None or dt > slowest[0]:
                slowest = (dt, name, row, col)
            if dt >= 250_000_000:
                slow_ops.append({"name": name, "row": row, "column": col, "ms": round(dt / 1_000_000.0, 3)})
            return result, dt

        failure_type = None
        end = begin
        try:
            span("block_signals", lambda: table.blockSignals(True))
            span("set_updates_disabled", lambda: table.setUpdatesEnabled(False))
            span("set_sorting_disabled", lambda: table.setSortingEnabled(False))

            total_rows = len(st["rows"])
            while end < total_rows and rows_committed < max_rows_per_turn:
                row = end
                vals = st["rows"][row]
                raw = st["raw"][row] if row < len(st["raw"]) else None
                for col, value in enumerate(vals):
                    text = str(value)
                    item = table.item(row, col)
                    if item is None:
                        item = QTableWidgetItem(text)
                        _, dt = span("set_item_create", lambda r=row, c=col, i=item: table.setItem(r, c, i), row, col)
                        created_items += 1
                        updated_cells += 1
                        set_item_total_ns += dt
                        max_set_item_ns = max(max_set_item_ns, dt)
                    elif item.text() != text:
                        _, dt = span("set_item_text", lambda i=item, t=text: i.setText(t), row, col)
                        updated_cells += 1
                        set_item_total_ns += dt
                        max_set_item_ns = max(max_set_item_ns, dt)
                    else:
                        unchanged_cells += 1

                if raw:
                    color_specs = [
                        (1, "#4ade80" if raw[1] == "MAIN" else "#facc15"),
                        (4, "#4ade80" if raw[4] == "LONG" else "#f87171"),
                    ]
                    if raw[16] in ("TP2", "STOP", "AMBIGUOUS", "PARTIAL_AMBIGUOUS"):
                        color_specs.append((16, "#4ade80" if raw[16] == "TP2" else "#f87171" if raw[16] == "STOP" else "#facc15"))
                    for col, color in color_specs:
                        item = table.item(row, col)
                        if item is not None and item.foreground().color() != QColor(color):
                            _, dt = span("set_foreground", lambda i=item, c=color: i.setForeground(QColor(c)), row, col)
                            set_foreground_total_ns += dt
                            max_foreground_ns = max(max_foreground_ns, dt)

                end += 1
                rows_committed += 1
                if time.perf_counter_ns() - qt_started_ns >= commit_budget_ns:
                    break

            st["index"] = end
            st["chunk"] += 1
            final = end >= len(st["rows"])
            if final:
                span("selection_restore", lambda: self._restore_table_symbol_selection(table, symbol_column=3))
                span("viewport_schedule", lambda: self.paint_scheduler.request(table.viewport(), priority=20))
                self._paper_render_state = None
        except Exception as exc:
            failure_type = type(exc).__name__
            raise
        finally:
            try:
                span("sorting_restore", lambda: table.setSortingEnabled(sorting_was_enabled))
            finally:
                try:
                    span("signals_restore", lambda: table.blockSignals(signals_were_blocked))
                finally:
                    span("updates_restore", lambda: table.setUpdatesEnabled(updates_were_enabled))

        qt_commit_ms = (time.perf_counter_ns() - qt_started_ns) / 1_000_000.0
        callback_execution_ms = (time.monotonic_ns() - callback_entry_ns) / 1_000_000.0
        final = end >= len(st["rows"])
        budget_exceeded = qt_commit_ms > 25.0
        record = {
            "schema_version": "dvs.runtime.paper_commit_forensics.v2",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "runtime_session_id": self._runtime_session_id, "pid": os.getpid(), "event": "paper_chunk_commit",
            "owner": "paper", "generation": int(st["generation"]), "request_reason": str(st["reason"]),
            "chunk_index": int(st["chunk"]), "row_begin": int(begin), "row_end": int(end),
            "row_count": int(end - begin), "final_chunk": bool(final),
            "scheduled_monotonic_ns": scheduled_ns, "callback_entry_monotonic_ns": callback_entry_ns,
            "queue_wait_ms": round(queue_wait_ms, 3), "qt_commit_ms": round(qt_commit_ms, 3),
            "callback_execution_ms": round(callback_execution_ms, 3), "budget_ms": 25.0,
            "adaptive_turn_budget_ms": 10.0, "budget_exceeded": bool(budget_exceeded),
            "signals_were_blocked": signals_were_blocked, "sorting_was_enabled": sorting_was_enabled,
            "updates_were_enabled": updates_were_enabled, "selected_row_before": selected_row_before,
            "row_count_before": row_count_before, "row_count_after": int(table.rowCount()),
            "created_items": int(created_items), "updated_cells": int(updated_cells),
            "unchanged_cells": int(unchanged_cells),
            "set_item_total_ms": round(set_item_total_ns / 1_000_000.0, 3),
            "set_foreground_total_ms": round(set_foreground_total_ns / 1_000_000.0, 3),
            "max_single_set_item_ms": round(max_set_item_ns / 1_000_000.0, 3),
            "max_single_set_foreground_ms": round(max_foreground_ns / 1_000_000.0, 3),
            "slowest_operation": slowest[1] if slowest else None,
            "slowest_row": slowest[2] if slowest else None,
            "slowest_column": slowest[3] if slowest else None,
            "slowest_operation_ms": round((slowest[0] if slowest else 0) / 1_000_000.0, 3),
            "gc_active": self._rc647_gc_active_generation is not None,
            "gc_active_generation": self._rc647_gc_active_generation,
            "active_generation": int(self._data_prepare_state["paper"]["generation"]),
            "failure_type": failure_type, "thread_name": QThread.currentThread().objectName(),
            "telemetry_mode": "async_enqueue", "telemetry_publish_ms": 0.0,
        }
        if budget_exceeded:
            record["span_breakdown_ms"] = {k: round(v / 1_000_000.0, 3) for k, v in spans.items()}
            record["slow_spans"] = slow_ops
            record["slow_span_detected"] = bool(slow_ops)
        enqueue_started_ns = time.perf_counter_ns()
        self._paper_commit_forensic_ring.append(record)
        record["telemetry_publish_ms"] = round((time.perf_counter_ns() - enqueue_started_ns) / 1_000_000.0, 6)
        self._record_gui_commit("paper", st["generation"], st["reason"], qt_started_ns / 1_000_000_000.0, end - begin, st["chunk"], final)
        if not final:
            st["scheduled_ns"] = time.monotonic_ns()
            QTimer.singleShot(0, self._commit_paper_chunk)

    def auto_paper_consider(self, analysis, unified_identity=None):
        if not self.auto_paper_enabled:
            return
        try:
            ok, message = self.paper_trade_service.auto_consider(
                analysis, unified_identity=unified_identity
            )
        except Exception as exc:
            direction = getattr(
                analysis,
                "direction",
                "UNKNOWN",
            )
            message = (
                f"Auto Paper lỗi {analysis.symbol}: "
                f"{type(exc).__name__}: {str(exc)[:120]}"
            )
            self.status.setText(message)
            stack_trace = traceback.format_exc()
            persisted = self.recorder.record_error(
                symbol=analysis.symbol,
                direction=direction,
                error_type=type(exc).__name__,
                error_message=str(exc),
                stack_trace=stack_trace,
                context={
                    "confidence": getattr(
                        analysis,
                        "confidence_score",
                        None,
                    ),
                    "entry_status": getattr(
                        getattr(
                            analysis,
                            "entry_status",
                            None,
                        ),
                        "value",
                        str(
                            getattr(
                                analysis,
                                "entry_status",
                                None,
                            )
                        ),
                    ),
                    "source_method": "auto_paper_consider",
                },
                source="AUTO_PAPER_TRADE",
            )
            if not persisted:
                logger.error(
                    "Auto Paper error could not be persisted | "
                    "symbol=%s direction=%s error=%s",
                    analysis.symbol,
                    direction,
                    exc,
                )
                self.status.setText(
                    message + " | Không ghi được error audit."
                )
            return

        if ok:
            self.status.setText(message)
            self.refresh_paper_trade_tab()

    def _apply_detail_tooltips(self):
        tips = {
            0: "Khung thời gian.",
            1: "CMF: đo dòng tiền. Dương nghiêng vào, âm nghiêng ra.",
            2: "RSI: động lượng. Dưới 30 quá bán, trên 70 quá mua.",
            3: "ADX: độ mạnh xu hướng. <20 yếu; 20–30 vừa; >30 mạnh.",
            4: "Relative Volume: x1.0 là bằng trung bình 20 nến.",
            5: "Pha thị trường do engine phân loại.",
            6: "Spring: quét đáy rồi lấy lại vùng giá.",
            7: "Upthrust: quét đỉnh rồi đóng lại phía dưới.",
            8: "L.Entry: chất lượng điểm vào Long, không phải xác suất thắng.",
            9: "S.Entry: chất lượng điểm vào Short, không phải xác suất thắng.",
        }
        for col, tip in tips.items():
            item = self.tf_table.horizontalHeaderItem(col)
            if item is not None:
                item.setToolTip(tip)
    def _build_error_tab(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        note = QLabel("Danh sách coin lỗi và nguyên nhân. Có thể bấm Quét lại lỗi ở thanh trên.")
        layout.addWidget(note)
        self.error_table = QTableWidget(0,3)
        self.error_table.setHorizontalHeaderLabels(["Coin","Nguyên nhân","Trạng thái"])
        self.error_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
        self.error_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        self.error_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.ResizeToContents)
        self.error_table.verticalHeader().setVisible(False)
        layout.addWidget(self.error_table)
        self.tabs.addTab(tab,"Trung tâm lỗi")




    def _build_smart_entry_tab(self):
        tab = QWidget()
        outer = QVBoxLayout(tab)
        self.smart_title = QLabel("<h3>Chọn coin để xem Smart Entry</h3>")
        outer.addWidget(self.smart_title)

        self.smart_score_box = QGroupBox("SMART ENTRY DASHBOARD")
        score_layout = QHBoxLayout(self.smart_score_box)
        score_text = QVBoxLayout()
        self.smart_score_label = QLabel("SMART ENTRY SCORE")
        self.smart_score_value = QLabel("0/100")
        score_text.addWidget(self.smart_score_label)
        score_text.addWidget(self.smart_score_value)
        self.smart_score_bar = QProgressBar()
        self.smart_score_bar.setRange(0, 100)
        self.smart_score_bar.setMinimumHeight(34)
        score_layout.addLayout(score_text, 1)
        score_layout.addWidget(self.smart_score_bar, 4)
        outer.addWidget(self.smart_score_box)

        self.smart_metrics_box = QGroupBox("CHỈ SỐ CỐT LÕI")
        metrics_layout = QHBoxLayout(self.smart_metrics_box)
        metric_specs = [
            ("loi", "LOI"), ("soi", "SOI"), ("smp", "SMP"),
            ("panic", "Panic Flush"), ("weak", "Weak Hand"),
            ("absorption", "Absorption"), ("fake_down", "Fake Breakdown"),
            ("fake_up", "Fake Breakout"),
        ]
        for key, title in metric_specs:
            card = QFrame()
            card.setFrameShape(QFrame.Shape.StyledPanel)
            card_layout = QVBoxLayout(card)
            name = QLabel(title)
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value = QLabel("0")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(True)
            bar.setFixedHeight(22)
            setattr(self, f"smart_metric_{key}_value", value)
            setattr(self, f"smart_metric_{key}_bar", bar)
            card_layout.addWidget(name)
            card_layout.addWidget(value)
            card_layout.addWidget(bar)
            metrics_layout.addWidget(card)
        outer.addWidget(self.smart_metrics_box)

        self.smart_insight_container = QWidget()
        insight_row = QHBoxLayout(self.smart_insight_container)
        probability_box = QGroupBox("XÁC SUẤT TƯƠNG ĐỐI")
        probability_layout = QVBoxLayout(probability_box)
        self.smart_probability = QLabel("LONG 0% | SHORT 0% | NEUTRAL 100%")
        self.smart_probability.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.smart_probability.setStyleSheet("font-size:16px;font-weight:700;")
        probability_layout.addWidget(self.smart_probability)
        trigger_box = QGroupBox("TRIGGER MATRIX")
        trigger_layout = QVBoxLayout(trigger_box)
        self.smart_trigger_text = QLabel("Chưa có dữ liệu")
        self.smart_trigger_text.setWordWrap(True)
        trigger_layout.addWidget(self.smart_trigger_text)
        insight_row.addWidget(probability_box, 1)
        insight_row.addWidget(trigger_box, 1)
        outer.addWidget(self.smart_insight_container)

        self.smart_timeline_box = QGroupBox("WYCKOFF / ENTRY TIMELINE")
        timeline_layout = QVBoxLayout(self.smart_timeline_box)
        self.smart_timeline = QLabel("CURRENT: - → BIAS: - → NEXT: -")
        self.smart_timeline.setWordWrap(True)
        self.smart_timeline.setStyleSheet("font-size:14px;font-weight:700;")
        timeline_layout.addWidget(self.smart_timeline)
        outer.addWidget(self.smart_timeline_box)

        details = QSplitter(Qt.Orientation.Vertical)
        self.smart_summary = QTextEdit()
        self.smart_summary.setReadOnly(True)
        self.smart_summary.setObjectName("BeginnerSummary")
        self.smart_text = QTextEdit()
        self.smart_text.setReadOnly(True)
        details.addWidget(self.smart_summary)
        details.addWidget(self.smart_text)
        details.setSizes([360, 420])
        outer.addWidget(details, 1)
        self.tabs.addTab(tab, "Smart Entry")
        self._apply_ux_mode()

    def _build_core_tab(self):
        """Build a responsive Decision Core workspace without stacked panels.

        Release 3.5.4 separates overview, evidence and conclusion into their own
        workspace pages.  Each page owns its scrolling/resizing behaviour, so a
        short desktop viewport can never force qualification cards, analytics,
        evidence controls and trade conclusions to paint over one another.
        """
        tab = QWidget()
        root_layout = QVBoxLayout(tab)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        self.core_title = QLabel("<h3>Chọn coin để xem Decision Core</h3>")
        self.core_title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        root_layout.addWidget(self.core_title)

        self.core_workspace_tabs = QTabWidget()
        self.core_workspace_tabs.setObjectName("DecisionCoreWorkspace")
        self.core_workspace_tabs.setDocumentMode(True)
        root_layout.addWidget(self.core_workspace_tabs, 1)

        # ---------------- Overview workspace ----------------
        overview_scroll = QScrollArea()
        overview_scroll.setWidgetResizable(True)
        overview_scroll.setFrameShape(QFrame.Shape.NoFrame)
        overview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        overview_content = QWidget()
        overview_layout = QVBoxLayout(overview_content)
        overview_layout.setContentsMargins(6, 6, 6, 12)
        overview_layout.setSpacing(12)

        comparison = QGroupBox("SHADOW-ONLY · LEGACY vs UNIFIED CORE")
        compare_layout = QHBoxLayout(comparison)
        compare_layout.setContentsMargins(12, 18, 12, 12)
        compare_layout.setSpacing(10)
        self.core_legacy_panel = QLabel("LEGACY\nChưa có dữ liệu")
        self.core_unified_panel = QLabel("UNIFIED CORE\nChưa chạy")
        self.core_agreement_panel = QLabel("AGREEMENT\nNOT_EVALUATED")
        for panel in (self.core_legacy_panel, self.core_unified_panel, self.core_agreement_panel):
            panel.setWordWrap(True)
            panel.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            panel.setObjectName("DecisionBox")
            panel.setMinimumHeight(118)
            panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            compare_layout.addWidget(panel, 1)
        overview_layout.addWidget(comparison)

        qualification = QGroupBox("SHADOW QUALIFICATION · FROZEN GOVERNANCE PROFILE")
        qualification_layout = QVBoxLayout(qualification)
        qualification_layout.setContentsMargins(12, 18, 12, 12)
        qualification_layout.setSpacing(10)
        self.core_qualification_progress = QProgressBar()
        self.core_qualification_progress.setRange(0, 100)
        self.core_qualification_progress.setValue(0)
        self.core_qualification_progress.setFormat("COLLECTING · %p% OF MINIMUM CYCLES")
        self.core_qualification_progress.setMinimumHeight(24)
        qualification_layout.addWidget(self.core_qualification_progress)

        qualification_cards = QHBoxLayout()
        qualification_cards.setSpacing(10)
        self.core_qualification_cycles = QLabel("CYCLES\n0/500")
        self.core_qualification_agreement = QLabel("FULL AGREEMENT\n0.0% / 85.0%")
        self.core_qualification_unsafe = QLabel("UNSAFE\n0 (hard gate)")
        self.core_qualification_profile = QLabel("PROFILE\nNot loaded")
        for card in (
            self.core_qualification_cycles,
            self.core_qualification_agreement,
            self.core_qualification_unsafe,
            self.core_qualification_profile,
        ):
            card.setObjectName("DecisionBox")
            card.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card.setWordWrap(True)
            card.setMinimumHeight(76)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            qualification_cards.addWidget(card, 1)
        qualification_layout.addLayout(qualification_cards)

        self.core_qualification_status = QLabel(
            "QUALIFICATION STATUS: COLLECTING · PAPER AUTHORITY: LEGACY"
        )
        self.core_qualification_status.setWordWrap(True)
        self.core_qualification_status.setMinimumHeight(28)
        qualification_layout.addWidget(self.core_qualification_status)

        self.core_qualification_analytics = QLabel("QUALIFICATION ANALYTICS\nChưa có dữ liệu")
        self.core_qualification_analytics.setObjectName("DecisionBox")
        self.core_qualification_analytics.setWordWrap(True)
        self.core_qualification_analytics.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.core_qualification_analytics.setMinimumHeight(145)
        self.core_qualification_analytics.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding
        )
        qualification_layout.addWidget(self.core_qualification_analytics)
        overview_layout.addWidget(qualification)
        overview_layout.addStretch(1)
        overview_scroll.setWidget(overview_content)
        self.core_workspace_tabs.addTab(overview_scroll, "Tổng quan")

        # ---------------- Evidence workspace ----------------
        evidence_page = QWidget()
        evidence_page_layout = QVBoxLayout(evidence_page)
        evidence_page_layout.setContentsMargins(6, 6, 6, 6)
        evidence_page_layout.setSpacing(8)
        evidence = QGroupBox("QUALIFICATION EVIDENCE CENTER · READ ONLY")
        evidence_layout = QVBoxLayout(evidence)
        evidence_layout.setContentsMargins(12, 18, 12, 12)
        evidence_layout.setSpacing(10)

        evidence_controls = QHBoxLayout()
        evidence_controls.setSpacing(8)
        self.qualification_evidence_search = QLineEdit()
        self.qualification_evidence_search.setPlaceholderText("Tìm coin, ví dụ BTC/USDT")
        self.qualification_evidence_search.setMinimumWidth(220)
        self.qualification_evidence_filter = QComboBox()
        self.qualification_evidence_filter.addItem("ALL AGREEMENTS", "")
        self.qualification_evidence_filter.addItem("FULL", "FULL")
        self.qualification_evidence_filter.addItem("PARTIAL", "PARTIAL")
        self.qualification_evidence_filter.addItem("CONSERVATIVE", "PARTIAL_UNIFIED_MORE_CONSERVATIVE")
        self.qualification_evidence_filter.addItem("UNSAFE", "UNSAFE_DIVERGENCE")
        refresh_evidence_btn = QPushButton("Làm mới")
        export_json_btn = QPushButton("Export JSON")
        export_csv_btn = QPushButton("Export CSV")
        export_report_btn = QPushButton("Scientific Report")
        evidence_controls.addWidget(self.qualification_evidence_search, 3)
        evidence_controls.addWidget(self.qualification_evidence_filter, 1)
        evidence_controls.addWidget(refresh_evidence_btn)
        evidence_controls.addWidget(export_json_btn)
        evidence_controls.addWidget(export_csv_btn)
        evidence_controls.addWidget(export_report_btn)
        evidence_layout.addLayout(evidence_controls)

        self.qualification_evidence_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.qualification_evidence_splitter.setObjectName("QualificationEvidenceSplitter")
        self.qualification_evidence_splitter.setChildrenCollapsible(False)
        self.qualification_evidence_table = QTableWidget(0, 7)
        self.qualification_evidence_table.setHorizontalHeaderLabels((
            "TIME", "SYMBOL", "AGREEMENT", "CONF", "REGIME", "INTEGRITY", "REQUEST ID"
        ))
        self.qualification_evidence_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.qualification_evidence_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.qualification_evidence_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.qualification_evidence_table.setAlternatingRowColors(True)
        self.qualification_evidence_table.verticalHeader().setVisible(False)
        self.qualification_evidence_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.qualification_evidence_table.horizontalHeader().setStretchLastSection(True)
        self.qualification_evidence_table.setMinimumWidth(620)
        self.qualification_evidence_table.setMinimumHeight(330)

        self.qualification_evidence_detail = QTextEdit()
        self.qualification_evidence_detail.setReadOnly(True)
        self.qualification_evidence_detail.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.qualification_evidence_detail.setMinimumWidth(390)
        self.qualification_evidence_detail.setMinimumHeight(330)
        self.qualification_evidence_detail.setPlainText(
            "Evidence mới sẽ xuất hiện sau qualification batch."
        )
        self.qualification_evidence_splitter.addWidget(self.qualification_evidence_table)
        self.qualification_evidence_splitter.addWidget(self.qualification_evidence_detail)
        self.qualification_evidence_splitter.setStretchFactor(0, 3)
        self.qualification_evidence_splitter.setStretchFactor(1, 2)
        evidence_layout.addWidget(self.qualification_evidence_splitter, 1)
        evidence_page_layout.addWidget(evidence, 1)

        refresh_evidence_btn.clicked.connect(self._refresh_qualification_evidence)
        self.qualification_evidence_search.returnPressed.connect(self._refresh_qualification_evidence)
        self.qualification_evidence_filter.currentIndexChanged.connect(self._refresh_qualification_evidence)
        self.qualification_evidence_table.itemSelectionChanged.connect(self._on_qualification_evidence_selected)
        export_json_btn.clicked.connect(self._export_qualification_evidence_json)
        export_csv_btn.clicked.connect(self._export_qualification_evidence_csv)
        export_report_btn.clicked.connect(self._export_scientific_qualification_report)
        self.core_workspace_tabs.addTab(evidence_page, "Evidence")

        # ---------------- Deterministic replay workspace ----------------
        replay_page = QWidget()
        replay_layout = QVBoxLayout(replay_page)
        replay_layout.setContentsMargins(6, 6, 6, 6)
        replay_layout.setSpacing(8)
        replay_group = QGroupBox("SHADOW REPLAY ENGINE · DETERMINISTIC · READ ONLY")
        replay_group_layout = QVBoxLayout(replay_group)
        replay_group_layout.setContentsMargins(12, 18, 12, 12)
        replay_group_layout.setSpacing(10)

        replay_header = QHBoxLayout()
        self.qualification_replay_title = QLabel("Chọn một Evidence record để replay")
        self.qualification_replay_title.setWordWrap(True)
        self.qualification_replay_integrity = QLabel("INTEGRITY: NOT LOADED")
        self.qualification_replay_integrity.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        replay_header.addWidget(self.qualification_replay_title, 2)
        replay_header.addWidget(self.qualification_replay_integrity, 1)
        replay_group_layout.addLayout(replay_header)

        self.qualification_replay_progress = QProgressBar()
        self.qualification_replay_progress.setRange(0, 1)
        self.qualification_replay_progress.setValue(0)
        self.qualification_replay_progress.setFormat("NO REPLAY")
        replay_group_layout.addWidget(self.qualification_replay_progress)

        replay_controls = QHBoxLayout()
        replay_reset_btn = QPushButton("Về đầu")
        replay_prev_btn = QPushButton("◀ Bước trước")
        replay_next_btn = QPushButton("Bước tiếp ▶")
        self.qualification_replay_auto_btn = QPushButton("Auto Replay")
        replay_controls.addWidget(replay_reset_btn)
        replay_controls.addWidget(replay_prev_btn)
        replay_controls.addWidget(replay_next_btn)
        replay_controls.addWidget(self.qualification_replay_auto_btn)
        replay_controls.addStretch(1)
        replay_group_layout.addLayout(replay_controls)

        self.qualification_replay_views = QTabWidget()
        self.qualification_replay_views.setDocumentMode(True)

        timeline_page = QWidget()
        timeline_layout = QVBoxLayout(timeline_page)
        timeline_layout.setContentsMargins(0, 0, 0, 0)
        replay_splitter = QSplitter(Qt.Orientation.Horizontal)
        replay_splitter.setChildrenCollapsible(False)
        self.qualification_replay_steps = QListWidget()
        self.qualification_replay_steps.setMinimumWidth(500)
        self.qualification_replay_steps.setAlternatingRowColors(True)
        self.qualification_replay_detail = QTextEdit()
        self.qualification_replay_detail.setReadOnly(True)
        self.qualification_replay_detail.setMinimumWidth(440)
        self.qualification_replay_detail.setPlainText(
            "Evidence Replay sẽ tái dựng tuần tự context, Legacy, Unified, reason codes, events, risk gate và agreement.\n\nKhông chạy lại chiến lược và không có quyền giao dịch."
        )
        replay_splitter.addWidget(self.qualification_replay_steps)
        replay_splitter.addWidget(self.qualification_replay_detail)
        replay_splitter.setStretchFactor(0, 2)
        replay_splitter.setStretchFactor(1, 3)
        timeline_layout.addWidget(replay_splitter)
        self.qualification_replay_views.addTab(timeline_page, "Decision Timeline")

        graph_page = QWidget()
        graph_layout = QVBoxLayout(graph_page)
        graph_layout.setContentsMargins(0, 0, 0, 0)
        graph_splitter = QSplitter(Qt.Orientation.Horizontal)
        graph_splitter.setChildrenCollapsible(False)
        self.qualification_decision_graph = QTreeWidget()
        self.qualification_decision_graph.setHeaderLabels(("DECISION NODE", "STATUS", "CONF"))
        self.qualification_decision_graph.setAlternatingRowColors(True)
        self.qualification_decision_graph.setMinimumWidth(560)
        self.qualification_decision_graph.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.qualification_decision_graph.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.qualification_decision_graph.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        inspector_splitter = QSplitter(Qt.Orientation.Vertical)
        inspector_splitter.setChildrenCollapsible(False)
        self.qualification_decision_inspector = QTextEdit()
        self.qualification_decision_inspector.setReadOnly(True)
        self.qualification_decision_inspector.setMinimumWidth(420)
        self.qualification_decision_inspector.setMinimumHeight(220)
        self.qualification_decision_inspector.setPlainText(
            "Chọn Evidence để dựng Decision Graph. Mỗi node được tạo từ dữ liệu đã lưu; không chạy lại chiến lược."
        )
        self.qualification_confidence_breakdown = QTableWidget(0, 4)
        self.qualification_confidence_breakdown.setHorizontalHeaderLabels(("CATEGORY", "SOURCE", "STATUS", "CONF"))
        self.qualification_confidence_breakdown.verticalHeader().setVisible(False)
        self.qualification_confidence_breakdown.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.qualification_confidence_breakdown.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.qualification_confidence_breakdown.setAlternatingRowColors(True)
        self.qualification_confidence_breakdown.setMinimumHeight(180)
        self.qualification_confidence_breakdown.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.qualification_confidence_breakdown.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.qualification_confidence_breakdown.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.qualification_confidence_breakdown.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        inspector_splitter.addWidget(self.qualification_decision_inspector)
        inspector_splitter.addWidget(self.qualification_confidence_breakdown)
        inspector_splitter.setStretchFactor(0, 3)
        inspector_splitter.setStretchFactor(1, 2)
        graph_splitter.addWidget(self.qualification_decision_graph)
        graph_splitter.addWidget(inspector_splitter)
        graph_splitter.setStretchFactor(0, 3)
        graph_splitter.setStretchFactor(1, 2)
        graph_layout.addWidget(graph_splitter)
        self.qualification_replay_views.addTab(graph_page, "Decision Graph & Inspector")
        replay_group_layout.addWidget(self.qualification_replay_views, 1)
        replay_layout.addWidget(replay_group, 1)

        self.qualification_replay_timer = QTimer(self)
        self.qualification_replay_timer.timeout.connect(self._qualification_replay_tick)
        replay_reset_btn.clicked.connect(self._qualification_replay_reset)
        replay_prev_btn.clicked.connect(self._qualification_replay_previous)
        replay_next_btn.clicked.connect(self._qualification_replay_next)
        self.qualification_replay_auto_btn.clicked.connect(self._qualification_replay_auto)
        self.qualification_replay_steps.itemSelectionChanged.connect(self._on_qualification_replay_step_selected)
        self.qualification_decision_graph.itemSelectionChanged.connect(self._on_qualification_decision_node_selected)
        self.core_workspace_tabs.addTab(replay_page, "Replay")

        # ---------------- Conclusion workspace ----------------
        conclusion_page = QWidget()
        conclusion_layout = QVBoxLayout(conclusion_page)
        conclusion_layout.setContentsMargins(6, 6, 6, 6)
        conclusion_layout.setSpacing(8)
        conclusion_splitter = QSplitter(Qt.Orientation.Vertical)
        conclusion_splitter.setChildrenCollapsible(False)
        self.core_summary = QTextEdit()
        self.core_summary.setReadOnly(True)
        self.core_summary.setObjectName("BeginnerSummary")
        self.core_summary.setMinimumHeight(180)
        self.core_text = QTextEdit()
        self.core_text.setReadOnly(True)
        self.core_text.setMinimumHeight(240)
        conclusion_splitter.addWidget(self.core_summary)
        conclusion_splitter.addWidget(self.core_text)
        conclusion_splitter.setStretchFactor(0, 2)
        conclusion_splitter.setStretchFactor(1, 3)
        conclusion_layout.addWidget(conclusion_splitter, 1)
        self.core_workspace_tabs.addTab(conclusion_page, "Kết luận & giải thích")
        self.core_workspace_tabs.currentChanged.connect(self._on_core_workspace_changed)
        self._qualification_evidence_dirty = True
        self._qualification_replay_dirty = False
        self._qualification_replay_pending_record = None

        self.tabs.addTab(tab, "Decision Core")

    def _build_structure_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.structure_title = QLabel("<h3>Chọn coin trong Dashboard để xem Liquidity & Wyckoff</h3>")
        self.structure_text = QTextEdit()
        self.structure_text.setReadOnly(True)
        self.structure_text.setToolTip(
            "Structure Test là phép xác nhận sau Spring/Upthrust ở cấp "
            "cấu trúc. Điểm cao khi giá không phá lại cực trị, volume và "
            "spread co lại. Dữ liệu này dùng để giải thích/xác nhận, "
            "không được cộng điểm hai lần."
        )
        layout.addWidget(self.structure_title)
        layout.addWidget(self.structure_text)
        self.tabs.addTab(tab, "Liquidity & Wyckoff")

    def _build_history_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        top = QHBoxLayout()
        self.history_summary = QLabel("Chưa có dữ liệu lịch sử")
        refresh_btn = QPushButton("Làm mới lịch sử")
        outcome_btn = QPushButton("Cập nhật kết quả")
        refresh_btn.clicked.connect(self.refresh_history)
        outcome_btn.clicked.connect(self.update_outcomes)
        top.addWidget(self.history_summary)
        top.addStretch()
        top.addWidget(outcome_btn)
        top.addWidget(refresh_btn)
        layout.addLayout(top)

        self.history_table = QTableWidget(0, 15)
        self.history_table.setHorizontalHeaderLabels([
            "Thời gian", "Coin", "Hướng", "Entry",
            "Confidence", "L.Trend", "L.Entry",
            "S.Trend", "S.Entry", "Giá", "Pha", "OI",
            "Kết quả", "R", "Chi tiết"
        ])
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history_table.itemSelectionChanged.connect(
            self._select_history_symbol
        )
        self.history_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        history_widths = (
            132, 110, 72, 72, 88, 76, 76, 76,
            76, 92, 190, 130, 92, 64, 210,
        )
        for column, width in enumerate(history_widths):
            self.history_table.setColumnWidth(column, width)
        self.history_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.history_table)
        self.history_widget = tab
        self.tabs.addTab(tab, "Lịch sử tín hiệu")
        self._history_ui_dirty = True
        self._history_pending_payload = None

    @_audit_gui_callback("outcome_update_request")
    def update_outcomes(self):
        if self._outcome_update_running:
            self.status.setText(
                "Outcome đang được cập nhật ở nền..."
            )
            return
        self._outcome_update_running = True
        self.status.setText(
            "Đang cập nhật kết quả tín hiệu ở nền..."
        )
        self._outcome_update_requested.emit(120)

    @Slot(object, float)
    def _on_outcome_update_completed(
        self,
        stats,
        elapsed_ms: float,
    ) -> None:
        self._outcome_update_running = False
        self.status.setText(
            f"Outcome: kiểm tra {stats['checked']}, "
            f"cập nhật {stats['updated']}, "
            f"TP1 trung gian {stats.get('tp1_intermediate', 0)}, "
            f"expired {stats.get('expired', 0)}, "
            f"lỗi {stats['errors']} · {elapsed_ms:.0f} ms nền"
        )
        self._history_ui_dirty = True
        if self._is_history_workspace_visible():
            self.refresh_history()

    @Slot(str, float)
    def _on_outcome_update_failed(
        self,
        message: str,
        elapsed_ms: float,
    ) -> None:
        self._outcome_update_running = False
        self.status.setText(
            f"Outcome lỗi sau {elapsed_ms:.0f} ms: {message}"
        )

    def _is_history_workspace_visible(self) -> bool:
        return bool(
            getattr(self, "market_analysis_folder_widget", None) is not None
            and self.tabs.currentWidget()
            is self.market_analysis_folder_widget
            and getattr(self, "market_analysis_tabs", None) is not None
            and self.market_analysis_tabs.currentWidget()
            is getattr(self, "history_widget", None)
        )

    def _is_truth_workspace_visible(self) -> bool:
        return bool(
            getattr(self, "market_analysis_folder_widget", None) is not None
            and self.tabs.currentWidget()
            is self.market_analysis_folder_widget
            and getattr(self, "market_analysis_tabs", None) is not None
            and self.market_analysis_tabs.currentWidget()
            is getattr(self, "truth_dashboard", None)
        )

    def _on_market_analysis_tab_changed(self, index: int) -> None:
        truth = getattr(self, "truth_dashboard", None)
        if truth is not None:
            truth.set_active(self._is_truth_workspace_visible())

        if self._is_history_workspace_visible():
            pending = getattr(self, "_history_pending_payload", None)
            if pending is not None:
                self._history_pending_payload = None
                self._begin_history_commit(*pending)
            elif getattr(self, "_history_render_state", None):
                QTimer.singleShot(0, self._commit_history_chunk)
            elif getattr(self, "_history_ui_dirty", False):
                self.refresh_history()

    @_audit_gui_callback("history_refresh")
    def refresh_history(self):
        self._history_ui_dirty = False
        self._submit_data_prepare("history", "refresh_history")

    def _begin_history_commit(self,generation,reason,payload):
        if generation != self._data_prepare_state["history"]["generation"]:
            return
        if not self._is_history_workspace_visible():
            self._history_pending_payload = (
                generation,
                reason,
                payload,
            )
            self._history_ui_dirty = False
            return
        started=time.perf_counter(); stats=payload["stats"]
        self.history_summary.setText(f"Record: {stats['count']} | READY: {stats['ready']} | Đã chốt: {stats['resolved']} | Win rate: {stats['win_rate']:.1f}% | Avg R: {stats['avg_r']:+.2f} | Amb: {stats.get('ambiguous',0)} | Exp: {stats.get('expired',0)} | Confidence TB: {stats['avg_confidence']:.1f}")
        self.history_table.setUpdatesEnabled(False); self.history_table.blockSignals(True); self.history_table.setRowCount(len(payload["rows"])); self.history_table.blockSignals(False); self.history_table.setUpdatesEnabled(True)
        self._history_render_state={"generation":generation,"reason":reason,"rows":payload["rows"],"index":0,"chunk":0}
        self._record_gui_commit("history",generation,reason,started,0,0,not payload["rows"])
        QTimer.singleShot(0,self._commit_history_chunk)

    def _commit_history_chunk(self):
        st=self._history_render_state
        if (
            not st
            or st["generation"]
            != self._data_prepare_state["history"]["generation"]
            or self.is_closing
        ):
            return
        if not self._is_history_workspace_visible():
            return
        started = time.perf_counter()
        begin = st["index"]
        end = min(begin + 6, len(st["rows"]))
        self.history_table.setUpdatesEnabled(False)
        self.history_table.blockSignals(True)
        try:
            for row in range(begin, end):
                for col, value in enumerate(st["rows"][row]):
                    rendered = str(value)
                    item = self.history_table.item(row, col)
                    if item is None:
                        self.history_table.setItem(
                            row,
                            col,
                            QTableWidgetItem(rendered),
                        )
                    elif item.text() != rendered:
                        item.setText(rendered)
        finally:
            self.history_table.blockSignals(False)
            self.history_table.setUpdatesEnabled(True)
        st["index"] = end
        st["chunk"] += 1
        final = end >= len(st["rows"])
        if final:
            self._restore_table_symbol_selection(self.history_table,symbol_column=1); self.paint_scheduler.request(self.history_table.viewport(),priority=20); self._history_render_state=None
        self._record_gui_commit("history",st["generation"],st["reason"],started,end-begin,st["chunk"],final)
        if not final:
            QTimer.singleShot(12, self._commit_history_chunk)

    def _panel(self,title,widget):
        frame = QFrame(); frame.setObjectName("MetricCard")
        layout = QVBoxLayout(frame); layout.setContentsMargins(7,4,7,5); layout.setSpacing(2); lab = QLabel(f"<b>{title}</b>")
        lab.setStyleSheet("color:#cbd5e1;font-size:11px")
        layout.addWidget(lab); layout.addWidget(widget)
        return frame

    def toggle_auto_scan(self, checked):
        if checked:
            self._last_auto_tick_monotonic = time.monotonic()
            self.auto_scan_seconds = self.config.refresh_seconds
            self.auto_scan_btn.setText(
                f"Tự quét: {self.config.refresh_seconds}s"
            )
            self.auto_scan_timer.start()
            self.status.setText("Đã bật tự động quét mỗi 60 giây.")
        else:
            self.auto_scan_timer.stop()
            self.auto_scan_btn.setText(
                f"Tự quét {self.config.refresh_seconds}s"
            )
            self.status.setText("Đã tắt tự động quét.")

    @_audit_gui_callback("auto_scan_tick")
    def auto_scan_tick(self):
        now = time.monotonic()
        tick_gap = max(0.0, now - self._last_auto_tick_monotonic)
        self._last_auto_tick_monotonic = now
        if self.is_closing:
            self._record_scan_launch_decision(
                "BLOCKED_SHUTDOWN", rate_limit_seconds=30.0,
                source="auto_scan_tick",
            )
            return
        if not self.auto_scan_btn.isChecked():
            self._record_scan_launch_decision(
                "BLOCKED_AUTO_SCAN_DISABLED", rate_limit_seconds=30.0,
                source="auto_scan_tick",
            )
            return
        # A large timer gap normally means Windows sleep/hibernate or a
        # suspended process. Defer the next scan instead of treating the
        # elapsed sleep interval as an overdue countdown.
        if tick_gap >= 30.0:
            self._sleep_resume_events += 1
            self.auto_scan_seconds = self.config.refresh_seconds
            self.auto_scan_btn.setText(
                f"Tự quét: {self.auto_scan_seconds}s"
            )
            self.status.setText(
                "Phát hiện máy vừa resume; đã hoãn vòng quét kế tiếp "
                "để tài nguyên mạng ổn định."
            )
            logger.warning(
                "SYSTEM_RESUME_DETECTED confidence=HIGH tick_gap_seconds=%.3f "
                "active_scan=%s sleep_resume_events=%s",
                tick_gap,
                bool(self.thread is not None and self.thread.isRunning()),
                self._sleep_resume_events,
            )
            return
        if tick_gap >= 8.0:
            logger.info(
                "TIMER_GAP_OBSERVED confidence=LOW tick_gap_seconds=%.3f "
                "active_scan=%s action=none",
                tick_gap,
                bool(self.thread is not None and self.thread.isRunning()),
            )
        if self.thread is not None and self.thread.isRunning():
            self._record_scan_launch_decision(
                "BLOCKED_THREAD_RUNNING", rate_limit_seconds=10.0,
                source="auto_scan_tick",
            )
            self.auto_scan_btn.setText("Tự quét: đang quét")
            return
        self.auto_scan_seconds -= 1
        if self.auto_scan_seconds <= 0:
            self.auto_scan_seconds = self.config.refresh_seconds
            self.auto_scan_btn.setText("Tự quét: đang quét")
            self._record_scan_launch_decision(
                "AUTO_SCAN_LAUNCH_REQUESTED", source="auto_scan_tick",
            )
            self.start_scan()
        else:
            self.auto_scan_btn.setText(f"Tự quét: {self.auto_scan_seconds}s")

    def _refresh_symbol_controls(self):
        symbols = [
            symbol.replace(":USDT", "")
            for symbol in self.watchlist
        ]
        current = self.header_symbol.currentText()
        self.header_symbol.blockSignals(True)
        self.header_symbol.clear()
        self.header_symbol.addItems(symbols)
        if current in symbols:
            self.header_symbol.setCurrentText(current)
        self.header_symbol.blockSignals(False)

    def _sync_order_flow_symbols(self, symbols) -> bool:
        runtime = self.order_flow_runtime
        if runtime is None or self.is_closing:
            return False
        return bool(runtime.update_symbols(tuple(symbols)))

    def manage_coins(self):
        previous = list(self.watchlist)
        dialog = CoinManagerDialog(self.watchlist, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        coins = dialog.coins()
        if not coins:
            QMessageBox.warning(
                self, "Danh sách trống", "Cần ít nhất một coin."
            )
            return

        added = [symbol for symbol in coins if symbol not in previous]
        self.watchlist = coins
        self.market_universe = list(dict.fromkeys(
            [*self.market_universe, *coins]
        ))
        self.coin_count.setText(f"{len(coins)} coin ghim")
        self._refresh_symbol_controls()
        self._sync_order_flow_symbols(self.market_universe)

        path = Path("config.json")
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["watchlist"] = self.watchlist
        path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if not added:
            self.status.setText("Đã lưu danh sách coin.")
            return

        if self.thread and self.thread.isRunning():
            self.status.setText(
                f"Đã thêm {len(added)} coin; ưu tiên vòng quét kế tiếp."
            )
        else:
            self.status.setText(
                f"Đã thêm {len(added)} coin; đang quét ngay..."
            )
            self._launch_scan(tuple(added), clear=False)


    def load_market_universe(self, show_message=True, *, continue_scan=False):
        """Start one asynchronous universe load without blocking the GUI.

        Single-flight is enforced. Repeated clicks do not create competing
        provider operations. Identity checks reject late results from any load
        that is cancelled or superseded during shutdown/future extensions.
        """
        if self._active_universe_load_id is not None:
            if continue_scan:
                self._universe_load_pending_scan = True
            self.status.setText("Universe đang được nạp; vui lòng chờ...")
            UNIVERSE_LOADER_TELEMETRY.emit(
                "universe_loader_single_flight_rejected",
                universe_load_id=self._active_universe_load_id,
            )
            return False

        load_id = f"universe-{uuid.uuid4().hex}"
        self._active_universe_load_id = load_id
        self._universe_load_pending_scan = bool(continue_scan)
        self._universe_load_registry[load_id] = {
            "show_message": bool(show_message),
            "started_monotonic": time.monotonic(),
            "finalized": False,
        }
        self.universe_btn.setEnabled(False)
        self.status.setText("Đang nạp universe Binance Futures ở tác vụ nền...")
        UNIVERSE_LOADER_TELEMETRY.emit(
            "universe_loader_started",
            universe_load_id=load_id,
            limit=int(self.config.universe_size),
            min_quote_volume=float(self.config.min_quote_volume_24h),
        )
        self._universe_load_requested.emit(
            load_id,
            int(self.config.universe_size),
            float(self.config.min_quote_volume_24h),
        )
        return True

    @Slot(str, str, int)
    def _on_universe_load_progress(self, load_id, phase, percent):
        if load_id != self._active_universe_load_id:
            return
        self.status.setText(
            f"Đang nạp universe Binance Futures... {int(percent)}% ({phase})"
        )
        UNIVERSE_LOADER_TELEMETRY.emit(
            "universe_loader_progress",
            universe_load_id=load_id,
            phase=phase,
            percent=int(percent),
        )

    @Slot(str, object, float)
    def _on_universe_load_completed(self, load_id, universe, elapsed_ms):
        if load_id != self._active_universe_load_id:
            UNIVERSE_LOADER_TELEMETRY.emit(
                "universe_loader_late_result_discarded",
                universe_load_id=load_id,
                current_universe_load_id=self._active_universe_load_id,
                outcome="completed",
                elapsed_ms=float(elapsed_ms),
            )
            self._finalize_universe_load(load_id, "SUPERSEDED")
            return

        metadata = self._universe_load_registry.get(load_id, {})
        show_message = bool(metadata.get("show_message", False))
        continue_scan = bool(self._universe_load_pending_scan)
        try:
            self.market_universe = list(universe)
            self._sync_order_flow_symbols(self.market_universe)
            self.coin_count.setText(
                f"{len(universe)}U/{self.config.deep_scan_size}D"
            )
            self.status.setText(
                f"Đã nạp {len(universe)} hợp đồng; "
                f"quét sâu {self.config.deep_scan_size} coin mỗi vòng."
            )
            UNIVERSE_LOADER_TELEMETRY.emit(
                "universe_loader_finished",
                universe_load_id=load_id,
                outcome="completed",
                universe_size=len(universe),
                elapsed_ms=float(elapsed_ms),
            )
            if show_message:
                QMessageBox.information(
                    self,
                    "Expanded Universe",
                    f"Đã nạp {len(universe)} hợp đồng USDT perpetual.\n"
                    f"Mỗi vòng quét sâu {self.config.deep_scan_size} coin "
                    "theo cơ chế round-robin.",
                )
        finally:
            self._finalize_universe_load(load_id, "COMPLETED")

        if continue_scan and not self.is_closing:
            QTimer.singleShot(0, self.start_scan)

    @Slot(str, str, float)
    def _on_universe_load_failed(self, load_id, error, elapsed_ms):
        if load_id != self._active_universe_load_id:
            UNIVERSE_LOADER_TELEMETRY.emit(
                "universe_loader_late_result_discarded",
                universe_load_id=load_id,
                current_universe_load_id=self._active_universe_load_id,
                outcome="failed",
                error=error,
                elapsed_ms=float(elapsed_ms),
            )
            self._finalize_universe_load(load_id, "SUPERSEDED")
            return

        metadata = self._universe_load_registry.get(load_id, {})
        show_message = bool(metadata.get("show_message", False))
        try:
            friendly_error = self._friendly_provider_message(error)
            if "PROVIDER_CIRCUIT_OPEN" in error:
                circuit = GLOBAL_PROVIDER_CIRCUIT.snapshot()
                wait_text = self._format_wait_duration(circuit.get("remaining_seconds", 0.0))
                self.status.setText(
                    f"Binance đang backoff; nạp universe sẽ thử lại sau khoảng {wait_text}."
                )
            else:
                self.status.setText(f"Lỗi nạp universe: {friendly_error[:120]}")
            UNIVERSE_LOADER_TELEMETRY.emit(
                "universe_loader_failed",
                universe_load_id=load_id,
                outcome="failed",
                error=error,
                elapsed_ms=float(elapsed_ms),
            )
            if show_message:
                QMessageBox.warning(self, "Không nạp được Universe", friendly_error)
        finally:
            self._finalize_universe_load(load_id, "FAILED")

    def _finalize_universe_load(self, load_id: str, terminal_state: str) -> None:
        metadata = self._universe_load_registry.get(load_id)
        if metadata is None or metadata.get("finalized"):
            return
        metadata["finalized"] = True
        self._universe_load_registry.pop(load_id, None)
        if self._active_universe_load_id == load_id:
            self._active_universe_load_id = None
            self._universe_load_pending_scan = False
            if not self.is_closing:
                self.universe_btn.setEnabled(True)
        UNIVERSE_LOADER_TELEMETRY.emit(
            "universe_loader_finalized",
            universe_load_id=load_id,
            terminal_state=terminal_state,
            registry_size=len(self._universe_load_registry),
        )

    def _cancel_active_universe_load(self, reason="application_closing"):
        load_id = self._active_universe_load_id
        if load_id is None:
            return
        self._active_universe_load_id = None
        self._universe_load_pending_scan = False
        UNIVERSE_LOADER_TELEMETRY.emit(
            "universe_loader_cancelled",
            universe_load_id=load_id,
            reason=reason,
        )
        self._finalize_universe_load(load_id, "CANCELLED")

    @staticmethod
    def _format_wait_duration(seconds: float) -> str:
        total = max(0, int(math.ceil(float(seconds))))
        if total < 60:
            return f"{total} giây"
        minutes, secs = divmod(total, 60)
        if minutes < 60:
            return f"{minutes} phút" + (f" {secs} giây" if secs else "")
        hours, minutes = divmod(minutes, 60)
        return f"{hours} giờ" + (f" {minutes} phút" if minutes else "")

    @classmethod
    def _friendly_provider_message(cls, raw_message: str) -> str:
        message = str(raw_message or "")
        marker = "provider circuit unavailable for "
        if "PROVIDER_CIRCUIT_OPEN" in message and marker in message:
            try:
                value = message.split(marker, 1)[1].split("s", 1)[0]
                remaining = float(value)
            except (ValueError, IndexError):
                remaining = 0.0
            wait_text = cls._format_wait_duration(remaining)
            return (
                "Binance đang giới hạn tạm thời kết nối.\n\n"
                f"Hệ thống sẽ thử lại sau khoảng {wait_text}.\n"
                "Các request mới đã được dừng để bảo vệ IP.\n"
                "Không cần khởi động lại phần mềm."
            )
        if "PROVIDER_HALF_OPEN_PROBE_ALREADY_CLAIMED" in message:
            return (
                "Hệ thống đang thực hiện một lần kiểm tra phục hồi kết nối Binance.\n"
                "Vui lòng chờ kết quả; không cần bấm kiểm tra lại."
            )
        return message

    @Slot()
    def _refresh_provider_circuit_status(self):
        snapshot = GLOBAL_PROVIDER_CIRCUIT.snapshot()
        state = snapshot.get("state", "CLOSED")
        remaining = float(snapshot.get("remaining_seconds", 0.0) or 0.0)
        if state == "OPEN":
            wait_text = self._format_wait_duration(remaining)
            self.provider_badge.setText(f"Provider: BACKOFF {wait_text}")
            self.provider_badge.setToolTip(
                "Binance đang giới hạn kết nối. Circuit Breaker đang chặn "
                f"request mới và sẽ thử lại sau khoảng {wait_text}."
            )
        elif state == "HALF_OPEN":
            self.provider_badge.setText("Provider: PROBING")
            self.provider_badge.setToolTip(
                "Đang gửi đúng một probe để kiểm tra Binance đã phục hồi hay chưa."
            )
        else:
            self.provider_badge.setText("Provider: ONLINE")
            self.provider_badge.setToolTip("Kết nối Binance đang sẵn sàng.")

    def check_api(self):
        if self._active_api_health_check_id is not None:
            return
        circuit = GLOBAL_PROVIDER_CIRCUIT.snapshot()
        if circuit.get("state") == "OPEN" and float(circuit.get("remaining_seconds", 0.0) or 0.0) > 0:
            remaining = float(circuit["remaining_seconds"])
            QMessageBox.information(
                self,
                "API Health",
                self._friendly_provider_message(
                    f"PROVIDER_CIRCUIT_OPEN: provider circuit unavailable for {remaining:.3f}s"
                ),
            )
            return
        operation_id = uuid.uuid4().hex
        self._active_api_health_check_id = operation_id
        self.health_btn.setEnabled(False)
        self.health_btn.setText("Đang kiểm tra...")
        self._api_health_check_requested.emit(operation_id)

    @Slot(str, bool, str, float)
    def _on_api_health_check_completed(self, operation_id, ok, msg, elapsed_ms):
        if operation_id != self._active_api_health_check_id:
            PROVIDER_EVIDENCE.emit(
                "api_health_check_late_result_discarded", operation_id=operation_id,
                elapsed_ms=round(float(elapsed_ms), 3), outcome="discarded",
            )
            return
        self._active_api_health_check_id = None
        if not self.is_closing:
            self.health_btn.setEnabled(True)
            self.health_btn.setText("Kiểm tra API")
            friendly = self._friendly_provider_message(msg)
            QMessageBox.information(self, "API Health", ("✅ " if ok else "❌ ") + friendly)

    def ui_performance_diagnostics(self):
        if hasattr(self, "ui_profiler"):
            return self.ui_profiler.log_report("manual")
        return {}

    def ui_geometry_diagnostics(self):
        if hasattr(self, "ui_geometry"):
            self.ui_geometry.log_diagnostic("manual")
            return dict(self.ui_geometry.last_diagnostic)
        return {}


    def start_scan(self):
        self.auto_scan_seconds = self.config.refresh_seconds

        if self.config.universe_enabled:
            if not self.market_universe or len(self.market_universe) < 20:
                self.load_market_universe(
                    show_message=False,
                    continue_scan=True,
                )
                return
            coins = self.service.deep_scan_batch(
                self.market_universe,
                self.config.deep_scan_size,
                pinned=self.watchlist,
            )
            self.deep_scan_batch = list(coins)
            self.coin_count.setText(
                f"{len(self.market_universe)}U/{len(coins)}D"
            )
        else:
            coins = (
                "BTC/USDT:USDT",
                *(
                    x for x in self.watchlist
                    if x != "BTC/USDT:USDT"
                ),
            )
        self._launch_scan(tuple(coins), clear=True)

    def retry_failed(self):
        coins = tuple(self.failed.keys())
        if not coins: return
        self._launch_scan(coins, clear=False)

    def _launch_scan(self, coins, clear):
        if self.thread and self.thread.isRunning():
            self._record_scan_launch_decision(
                "BLOCKED_THREAD_RUNNING", source="_launch_scan",
                requested_coin_count=len(tuple(coins)),
            )
            return

        self._scan_ui_snapshot = (
            self.ui_geometry.capture_view_state()
            if hasattr(self, "ui_geometry")
            else None
        )

        self._scan_view_tab = self.tabs.currentIndex()
        self._scan_view_symbol = (
            self.current_analysis.symbol
            if self.current_analysis is not None
            else None
        )
        self._scan_view_timeframe = (
            self.tf_selector.currentText()
            if hasattr(self, "tf_selector")
            else "15m"
        )
        self._scan_detail_scroll = (
            self.detail_text.verticalScrollBar().value()
            if hasattr(self, "detail_text")
            else 0
        )
        self._scan_score_scroll = (
            self.score_explain.verticalScrollBar().value()
            if hasattr(self, "score_explain")
            else 0
        )
        self._scan_outer_scroll = (
            self.detail_scroll_area.verticalScrollBar().value()
            if hasattr(self, "detail_scroll_area")
            else 0
        )
        focus_widget = QApplication.focusWidget()
        self._scan_had_detail_focus = bool(
            focus_widget is not None
            and hasattr(self, "detail_scroll_area")
            and self.detail_scroll_area.isAncestorOf(focus_widget)
        )

        if clear and not self.config.universe_enabled:
            self.results.clear()
            self.failed.clear()
            self.table.setRowCount(0)
            self._row_by_symbol.clear()
            self.error_table.setRowCount(0)
        elif clear:
            # Round-robin universe: update in place, do not destroy view.
            self.failed.clear()
            self.error_table.setRowCount(0)

        self.table.setSortingEnabled(False)
        self.progress.setRange(0,len(coins)); self.progress.setValue(0)
        self.start_btn.setEnabled(False); self.stop_btn.setEnabled(True); self.retry_btn.setEnabled(False)
        self.status.setText("Đang khởi tạo quét..."); self.scan_info.setText(f"0/{len(coins)}")
        self.current_scan_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        self._scan_cycle_count += 1
        self._scan_started_monotonic = time.monotonic()
        if not self._scan_runtime_thread.isRunning():
            logger.error("Persistent scan runtime thread is not running")
            self.status.setText("Luồng quét nền không khả dụng")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.table.setSortingEnabled(True)
            self.table.sortItems(1, Qt.SortOrder.DescendingOrder)
            self._rebuild_row_index()
            self._record_scan_launch_decision(
                "BLOCKED_SCAN_RUNTIME_UNAVAILABLE", source="_launch_scan",
            )
            return

        self._scan_worker_generation += 1
        generation = self._scan_worker_generation
        self._active_scan_worker_generation = generation
        self._active_scan_id = str(self.current_scan_id)
        self._active_scan_cycle_index = int(self._scan_cycle_count)
        self.thread = self._scan_runtime_thread
        self.worker = Worker(
            self.service,
            coins,
            self.config.timeframes,
            max_workers=self.config.scan_workers,
            runtime_session_id=self._runtime_session_id,
            scan_id=self.current_scan_id,
            cycle_index=self._scan_cycle_count,
            generation=generation,
        )
        self.worker.moveToThread(self._scan_runtime_thread)
        self._scan_run_requested.connect(self.worker.run, Qt.QueuedConnection)
        self.worker.result.connect(self.on_result)
        self.worker.progress.connect(self.on_progress)
        self.worker.error.connect(self.on_error)
        self.worker.lifecycle.connect(self._on_scan_executor_lifecycle)

        # RC7.7 ownership protocol:
        # - GUI owns the Python wrapper reference.
        # - Worker completion carries immutable identity only.
        # - No worker-thread signal directly calls deleteLater().
        # - GUI schedules one deferred deletion after queued completion slots
        #   have drained, and releases the wrapper only after destroyed().
        self._scan_worker_retained[generation] = self.worker
        self.worker.destroyed.connect(
            lambda *_args, g=generation, sid=str(self.current_scan_id),
                   ci=int(self._scan_cycle_count):
                self._on_scan_worker_destroyed(g, sid, ci),
            Qt.ConnectionType.QueuedConnection,
        )
        self.worker.finished_with_identity.connect(self._cleanup_scan_worker)
        self.worker.finished.connect(self.on_finished)
        self._record_scan_liveness(
            "worker_ownership_registered",
            finished_generation=int(generation),
            finished_scan_id=str(self.current_scan_id),
            finished_cycle_index=int(self._scan_cycle_count),
            worker_object_id=hex(id(self.worker)),
            retained_count=len(self._scan_worker_retained),
        )
        self._record_scan_launch_decision(
            "LAUNCH_ACCEPTED", source="_launch_scan",
            worker_object_id=hex(id(self.worker)),
            launched_generation=generation,
            active_generation=self._active_scan_worker_generation,
            active_scan_id=self._active_scan_id,
            active_cycle_index=self._active_scan_cycle_index,
            requested_coin_count=len(tuple(coins)),
            clear=bool(clear),
        )
        self._scan_run_requested.emit()


    def _finalize_scan_worker_deletion(
        self, generation: int, scan_id: str, cycle_index: int,
    ):
        """Disconnect one completed Worker and schedule exactly one deletion.

        This method runs on the GUI thread after completion callbacks already
        queued by Worker.run(). It never releases the final Python reference;
        that occurs only in _on_scan_worker_destroyed().
        """
        generation = int(generation)
        worker = self._scan_worker_retained.get(generation)
        if worker is None:
            self._record_scan_liveness(
                "worker_delete_missing",
                finished_generation=generation,
                finished_scan_id=str(scan_id),
                finished_cycle_index=int(cycle_index),
            )
            return
        if generation in self._scan_worker_delete_scheduled:
            self._record_scan_liveness(
                "duplicate_delete_blocked",
                finished_generation=generation,
                finished_scan_id=str(scan_id),
                finished_cycle_index=int(cycle_index),
            )
            return

        self._scan_worker_delete_scheduled.add(generation)
        disconnect_results = []
        for label, signal_obj, target in (
            ("run_request", self._scan_run_requested, worker.run),
            ("result", worker.result, self.on_result),
            ("progress", worker.progress, self.on_progress),
            ("error", worker.error, self.on_error),
            ("lifecycle", worker.lifecycle, self._on_scan_executor_lifecycle),
            ("identity", worker.finished_with_identity, self._cleanup_scan_worker),
            ("finished", worker.finished, self.on_finished),
        ):
            try:
                signal_obj.disconnect(target)
                disconnect_results.append({"connection": label, "ok": True})
            except Exception as exc:
                # A connection may already be absent after shutdown/race
                # recovery. This is diagnostic, not a reason to abort delete.
                disconnect_results.append({
                    "connection": label,
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                })

        self._record_scan_liveness(
            "worker_signals_disconnected",
            finished_generation=generation,
            finished_scan_id=str(scan_id),
            finished_cycle_index=int(cycle_index),
            disconnect_results=disconnect_results,
        )

        queued = False
        error_payload = None
        try:
            queued = bool(
                QMetaObject.invokeMethod(
                    worker,
                    "deleteLater",
                    Qt.ConnectionType.QueuedConnection,
                )
            )
        except Exception as exc:
            error_payload = {
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

        self._record_scan_liveness(
            "worker_delete_later_scheduled",
            finished_generation=generation,
            finished_scan_id=str(scan_id),
            finished_cycle_index=int(cycle_index),
            invoke_return=bool(queued),
            error=error_payload,
            retained_count=len(self._scan_worker_retained),
        )

        if not queued:
            # Fail closed: retain the wrapper instead of releasing it while
            # QObject ownership is uncertain. A later shutdown path may retry.
            self._scan_worker_delete_scheduled.discard(generation)
            self._record_scan_liveness(
                "worker_delete_later_failed_retained",
                finished_generation=generation,
                finished_scan_id=str(scan_id),
                finished_cycle_index=int(cycle_index),
            )
            return

        self._scan_worker_validity_probe_attempts[generation] = 0
        self._record_scan_liveness(
            "worker_validity_probe_started",
            finished_generation=generation,
            finished_scan_id=str(scan_id),
            finished_cycle_index=int(cycle_index),
            retained_count=len(self._scan_worker_retained),
        )
        QTimer.singleShot(
            int(self._scan_worker_validity_probe_interval_ms),
            lambda g=generation, sid=str(scan_id), ci=int(cycle_index):
                self._probe_scan_worker_validity(g, sid, ci),
        )

    def _release_scan_worker_ownership(
        self, generation: int, scan_id: str, cycle_index: int, *,
        observation_source: str,
    ) -> None:
        """Release one retained wrapper only after destruction is observed."""
        generation = int(generation)
        if generation in self._scan_worker_destroyed_observed:
            self._record_scan_liveness(
                "duplicate_destroyed_ack_blocked",
                finished_generation=generation,
                finished_scan_id=str(scan_id),
                finished_cycle_index=int(cycle_index),
                observation_source=str(observation_source),
            )
            return

        self._scan_worker_destroyed_observed.add(generation)
        retained = self._scan_worker_retained.pop(generation, None)
        self._scan_worker_delete_scheduled.discard(generation)
        self._scan_worker_cleanup_started.discard(generation)
        self._scan_worker_validity_probe_attempts.pop(generation, None)

        self._record_scan_liveness(
            "worker_destroyed_observed",
            finished_generation=generation,
            finished_scan_id=str(scan_id),
            finished_cycle_index=int(cycle_index),
            observation_source=str(observation_source),
            had_retained_wrapper=retained is not None,
            retained_count=len(self._scan_worker_retained),
        )
        self._record_scan_liveness(
            "worker_ownership_released",
            finished_generation=generation,
            finished_scan_id=str(scan_id),
            finished_cycle_index=int(cycle_index),
            observation_source=str(observation_source),
            retained_count=len(self._scan_worker_retained),
        )

    def _probe_scan_worker_validity(
        self, generation: int, scan_id: str, cycle_index: int,
    ) -> None:
        """Observe QObject destruction without calling Worker/QObject methods."""
        generation = int(generation)
        worker = self._scan_worker_retained.get(generation)
        if worker is None or generation in self._scan_worker_destroyed_observed:
            return

        if _dvs_shiboken6 is None:
            self._record_scan_liveness(
                "worker_validity_probe_unavailable",
                finished_generation=generation,
                finished_scan_id=str(scan_id),
                finished_cycle_index=int(cycle_index),
                retained_count=len(self._scan_worker_retained),
            )
            return

        attempt = int(self._scan_worker_validity_probe_attempts.get(generation, 0)) + 1
        self._scan_worker_validity_probe_attempts[generation] = attempt
        try:
            is_valid = bool(_dvs_shiboken6.isValid(worker))
        except Exception as exc:
            self._record_scan_liveness(
                "worker_validity_probe_unavailable",
                finished_generation=generation,
                finished_scan_id=str(scan_id),
                finished_cycle_index=int(cycle_index),
                attempt=attempt,
                error_type=type(exc).__name__,
                error=str(exc),
                retained_count=len(self._scan_worker_retained),
            )
            return

        if not is_valid:
            self._record_scan_liveness(
                "worker_validity_probe_invalid",
                finished_generation=generation,
                finished_scan_id=str(scan_id),
                finished_cycle_index=int(cycle_index),
                attempt=attempt,
                retained_count=len(self._scan_worker_retained),
            )
            self._release_scan_worker_ownership(
                generation, scan_id, cycle_index,
                observation_source="shiboken_isValid_false",
            )
            return

        if attempt >= int(self._scan_worker_validity_probe_max_attempts):
            self._record_scan_liveness(
                "worker_validity_probe_timeout_retained",
                finished_generation=generation,
                finished_scan_id=str(scan_id),
                finished_cycle_index=int(cycle_index),
                attempts=attempt,
                retained_count=len(self._scan_worker_retained),
            )
            return

        QTimer.singleShot(
            int(self._scan_worker_validity_probe_interval_ms),
            lambda g=generation, sid=str(scan_id), ci=int(cycle_index):
                self._probe_scan_worker_validity(g, sid, ci),
        )

    @Slot()
    def _on_scan_worker_destroyed(
        self, generation: int, scan_id: str, cycle_index: int,
    ):
        """Legacy Qt destroyed acknowledgement; use one release authority."""
        self._release_scan_worker_ownership(
            int(generation), str(scan_id), int(cycle_index),
            observation_source="qt_destroyed_signal",
        )

    @Slot(object)
    def _on_scan_executor_lifecycle(self, payload):
        self._last_executor_lifecycle = dict(payload or {})
        logger.info(
            "Scan executor lifecycle drained=%s shutdown_ms=%s "
            "threads_before=%s threads_after=%s stop_requested=%s",
            self._last_executor_lifecycle.get("executor_drained"),
            self._last_executor_lifecycle.get("executor_shutdown_ms"),
            len(self._last_executor_lifecycle.get(
                "dvs_scan_threads_before_shutdown", ()
            )),
            len(self._last_executor_lifecycle.get(
                "dvs_scan_threads_after_shutdown", ()
            )),
            self._last_executor_lifecycle.get("stop_requested"),
        )

    @Slot(int, str, int)
    def _cleanup_scan_worker(
        self, finished_generation: int, finished_scan_id: str,
        finished_cycle_index: int,
    ):
        """Release the active one-shot Worker using stable generation identity.

        Correctness authority is the immutable generation payload copied into
        the queued signal. QObject sender()/Python wrapper identity is retained
        nowhere in the decision path. A stale completion can therefore never
        clear a newer active worker, while deferred QObject deletion cannot
        create a false mismatch for the current worker.
        """
        active_generation = self._active_scan_worker_generation
        active_scan_id = str(self._active_scan_id)
        active_cycle_index = int(self._active_scan_cycle_index)
        generation_matches = (
            active_generation is not None
            and int(finished_generation) == int(active_generation)
        )
        identity_payload_matches = (
            generation_matches
            and str(finished_scan_id) == active_scan_id
            and int(finished_cycle_index) == active_cycle_index
        )
        self._record_scan_liveness(
            "cleanup_slot_enter",
            finished_generation=int(finished_generation),
            active_generation=active_generation,
            finished_scan_id=str(finished_scan_id),
            active_scan_id=active_scan_id,
            finished_cycle_index=int(finished_cycle_index),
            active_cycle_index=active_cycle_index,
        )
        self._record_scan_liveness(
            "cleanup_generation_check",
            finished_generation=int(finished_generation),
            active_generation=active_generation,
            generation_matches=bool(generation_matches),
            identity_payload_matches=bool(identity_payload_matches),
            finished_scan_id=str(finished_scan_id),
            active_scan_id=active_scan_id,
            finished_cycle_index=int(finished_cycle_index),
            active_cycle_index=active_cycle_index,
        )
        if not identity_payload_matches:
            self._record_scan_liveness(
                "STALE_GENERATION_IGNORED",
                finished_generation=int(finished_generation),
                active_generation=active_generation,
                finished_scan_id=str(finished_scan_id),
                active_scan_id=active_scan_id,
                finished_cycle_index=int(finished_cycle_index),
                active_cycle_index=active_cycle_index,
            )
            logger.warning(
                "Ignoring stale scan-worker completion generation=%s active=%s "
                "scan_id=%s active_scan_id=%s cycle=%s active_cycle=%s",
                finished_generation, active_generation, finished_scan_id,
                active_scan_id, finished_cycle_index, active_cycle_index,
            )
            return

        duration_ms = 0.0
        if self._scan_started_monotonic is not None:
            duration_ms = max(
                0.0,
                (time.monotonic() - self._scan_started_monotonic) * 1000.0,
            )
        generation_key = int(finished_generation)
        if generation_key in self._scan_worker_cleanup_started:
            self._record_scan_liveness(
                "duplicate_cleanup_blocked",
                finished_generation=generation_key,
                active_generation=active_generation,
            )
            return
        self._scan_worker_cleanup_started.add(generation_key)

        # Public active-cycle state may be released now, but the Python wrapper
        # remains strongly owned by _scan_worker_retained until destroyed().
        try:
            self.worker = None
            # The private persistent runtime QThread remains alive and reused.
            self.thread = None
            self._active_scan_worker_generation = None
            self._active_scan_id = ""
            self._active_scan_cycle_index = 0
            self._record_scan_liveness(
                "cleanup_generation_match",
                finished_generation=generation_key,
                active_generation=active_generation,
                generation_matches=True,
            )
            self._record_scan_liveness(
                "cleanup_thread_reset",
                finished_generation=generation_key,
                active_generation=active_generation,
            )

            # Queue the actual disconnect/delete handoff after the already
            # emitted legacy finished() event has had an opportunity to invoke
            # on_finished on the GUI thread.
            QTimer.singleShot(
                0,
                lambda g=generation_key, sid=str(finished_scan_id),
                       ci=int(finished_cycle_index):
                    self._finalize_scan_worker_deletion(g, sid, ci),
            )
            self._record_scan_liveness(
                "worker_cleanup_deferred",
                finished_generation=generation_key,
                finished_scan_id=str(finished_scan_id),
                finished_cycle_index=int(finished_cycle_index),
            )
        finally:
            # Cleanup must remain idempotent and must never leave the scan
            # duration marker armed, even if future telemetry code fails.
            self._scan_started_monotonic = None
        dvs_scan_threads = tuple(
            thread.name
            for thread in threading.enumerate()
            if thread.name.startswith("dvs-scan")
        )
        self._last_thread_attribution = self._thread_attribution.snapshot(
            self._scan_cycle_count
        )
        new_thread_names = tuple(
            item.get("name", "")
            for item in self._last_thread_attribution.get("new_threads", ())
        )
        persistent_thread_names = tuple(
            item.get("name", "")
            for item in self._last_thread_attribution.get("persistent_threads", ())
        )
        self._record_scan_liveness(
            "cleanup_slot_exit",
            finished_generation=int(finished_generation),
            active_generation=active_generation,
            generation_matches=True,
        )
        self._scan_runtime_metrics = {
            "cycles_completed": self._scan_cycle_count,
            "last_duration_ms": round(duration_ms, 3),
            "python_threads": threading.active_count(),
            "dvs_scan_threads": dvs_scan_threads,
            "executor_drained": bool(
                self._last_executor_lifecycle.get(
                    "executor_drained", not dvs_scan_threads
                )
            ) and not dvs_scan_threads,
            "executor_shutdown_ms": self._last_executor_lifecycle.get(
                "executor_shutdown_ms", 0.0
            ),
            "worker_released": self.worker is None,
            "qthread_released": self.thread is None,
            "sleep_resume_events": self._sleep_resume_events,
            "thread_category_counts": dict(
                self._last_thread_attribution.get("category_counts", {})
            ),
            "new_thread_names": new_thread_names,
            "persistent_thread_names": persistent_thread_names,
            "thread_inventory": tuple(
                dict(item)
                for item in self._last_thread_attribution.get("inventory", ())
            ),
        }
        logger.info(
            "Scan lifecycle released cycle=%s duration_ms=%.3f "
            "python_threads=%s dvs_scan_threads=%s executor_drained=%s "
            "worker_released=%s qthread_released=%s sleep_resume_events=%s",
            self._scan_cycle_count,
            duration_ms,
            self._scan_runtime_metrics["python_threads"],
            len(self._scan_runtime_metrics["dvs_scan_threads"]),
            self._scan_runtime_metrics["executor_drained"],
            self._scan_runtime_metrics["worker_released"],
            self._scan_runtime_metrics["qthread_released"],
            self._scan_runtime_metrics["sleep_resume_events"],
        )
        logger.info(
            "PYTHON_THREAD_ATTRIBUTION cycle=%s count=%s categories=%s "
            "new=%s persistent=%s inventory=%s",
            self._scan_cycle_count,
            self._last_thread_attribution.get("thread_count", 0),
            json.dumps(
                self._last_thread_attribution.get("category_counts", {}),
                sort_keys=True,
            ),
            json.dumps(new_thread_names),
            json.dumps(persistent_thread_names),
            json.dumps(
                self._last_thread_attribution.get("inventory", ()),
                sort_keys=True,
            ),
        )

    def scan_runtime_diagnostics(self) -> dict:
        """Return a bounded, read-only snapshot of scan lifecycle telemetry."""
        metrics = dict(self._scan_runtime_metrics)
        metrics.update({
            "cycle_started": self._scan_started_monotonic is not None,
            "worker_present": self.worker is not None,
            "qthread_present": self.thread is not None,
        })
        return metrics

    def stop_scan(self):
        if self.worker: self.worker.stop()
        self.status.setText("Đang yêu cầu dừng...")

    def _enqueue_result_dispatch(self, kind: str, analysis, scan_id=None) -> bool:
        """O(1) GUI-thread handoff for recorder/capture submissions."""
        if self.is_closing or getattr(self, "_result_dispatch_stop", None) is None:
            return False
        try:
            self._result_dispatch_queue.put_nowait(
                (str(kind), analysis, scan_id, time.perf_counter_ns())
            )
            return True
        except queue.Full:
            self._record_scan_liveness(
                "result_dispatch_queue_full",
                dispatch_kind=str(kind),
                symbol=str(getattr(analysis, "symbol", "UNKNOWN")),
                queue_depth=int(self._result_dispatch_queue.qsize()),
            )
            return False

    def _result_dispatch_loop(self) -> None:
        """Background submitter only; never mutates GUI widgets."""
        while not self._result_dispatch_stop.is_set():
            try:
                item = self._result_dispatch_queue.get(timeout=0.10)
            except queue.Empty:
                continue
            if item is None:
                self._result_dispatch_queue.task_done()
                break
            kind, analysis, scan_id, queued_ns = item
            try:
                if kind == "record":
                    self._signal_record_requested.emit(analysis, scan_id)
                elif kind == "capture":
                    capture = getattr(self, "live_episode_capture", None)
                    if capture is not None:
                        submit = getattr(capture, "submit", None)
                        if submit is not None:
                            submit(analysis)
                        else:
                            capture.capture(analysis)
            except Exception:
                logger.exception(
                    "RESULT_DISPATCH_FAILED kind=%s symbol=%s",
                    kind,
                    str(getattr(analysis, "symbol", "UNKNOWN")),
                )
            finally:
                self._result_dispatch_queue.task_done()

    def _stop_result_dispatcher(self, timeout_s: float = 2.0) -> None:
        stop = getattr(self, "_result_dispatch_stop", None)
        thread = getattr(self, "_result_dispatch_thread", None)
        q = getattr(self, "_result_dispatch_queue", None)
        if stop is None or thread is None or q is None:
            return
        stop.set()
        try:
            q.put_nowait(None)
        except queue.Full:
            pass
        if thread.is_alive():
            thread.join(timeout=max(0.0, float(timeout_s)))

    @Slot(int,int,str)
    @_audit_gui_callback("scan_progress_callback", record_threshold_ms=10.0)
    def on_progress(self,i,total,symbol):
        callback_started_ns = time.perf_counter_ns()
        if self.is_closing:
            return
        prepare_started_ns = time.perf_counter_ns()
        progress_value = max(0, int(i) - 1)
        progress_total = max(0, int(total))
        status_text = f"Đang quét {symbol}"
        scan_info_text = f"{i}/{total}"
        data_prepare_ms = (time.perf_counter_ns() - prepare_started_ns) / 1_000_000.0

        item_update_started_ns = time.perf_counter_ns()
        # Geometry is restored once after scan completion, never per coin.
        self.progress.setMaximum(progress_total)
        self.progress.setValue(progress_value)
        self.status.setText(status_text)
        self.scan_info.setText(scan_info_text)
        item_update_ms = (time.perf_counter_ns() - item_update_started_ns) / 1_000_000.0
        total_callback_ms = (time.perf_counter_ns() - callback_started_ns) / 1_000_000.0
        GR01_GUI_FORENSICS.emit(
            "scan_progress_gui_commit",
            generation=int(getattr(self, "_scan_cycle_count", 0) or 0),
            queue_wait_ms=None,
            data_prepare_ms=data_prepare_ms,
            model_transform_ms=0.0,
            table_diff_ms=0.0,
            widget_create_ms=0.0,
            item_update_ms=item_update_ms,
            layout_ms=0.0,
            repaint_request_ms=0.0,
            total_callback_ms=total_callback_ms,
            symbol=str(symbol),
            progress_index=int(i),
            progress_total=progress_total,
            gui_thread_ident=threading.get_ident(),
        )

    def _schedule_aggregate_refresh(self):
        if self.is_closing:
            return
        self._aggregate_refresh_pending = True
        self.aggregate_refresh_timer.start()

    def _flush_aggregate_refresh(self):
        if self.is_closing or self._aggregate_refresh_running:
            return
        if not self._aggregate_refresh_pending:
            return

        self._aggregate_refresh_pending = False
        self._aggregate_refresh_running = True
        total_started = time.perf_counter()
        error_table_ms = 0.0
        summary_ms = 0.0
        try:
            context = (
                self.ui_profiler.section("aggregate_refresh_debounced")
                if hasattr(self, "ui_profiler")
                else nullcontext()
            )
            with context:
                phase_started = time.perf_counter()
                self._refresh_error_table()
                error_table_ms = (time.perf_counter() - phase_started) * 1000.0

                phase_started = time.perf_counter()
                self.refresh_summary()
                summary_ms = (time.perf_counter() - phase_started) * 1000.0
        finally:
            total_ms = (time.perf_counter() - total_started) * 1000.0
            self._record_gui_hotspot(
                "aggregate_refresh_debounced_total",
                total_ms,
                error_table_ms=round(error_table_ms, 3),
                summary_ms=round(summary_ms, 3),
                failed_count=len(self.failed),
                result_count=len(self.results),
            )
            self._aggregate_refresh_running = False

    def _on_learning_snapshot_cache_replaced(self, old_cache, new_cache, reason: str) -> None:
        telemetry = getattr(self, "_retention_owner_telemetry", None)
        if telemetry is not None:
            telemetry.record_container_replaced(
                "learning_observations",
                old_container=old_cache,
                new_container=new_cache,
                replacement_reason=str(reason),
                flatten_groups=True,
            )

    @Slot(str,str)
    @_audit_gui_callback("scan_error_callback")
    def on_error(self,symbol,message):
        if self.is_closing:
            return
        self.failed[symbol] = message
        self._schedule_aggregate_refresh()
        self.status.setText(f"Lỗi {symbol}: {message[:100]}")

    def _schedule_stream_table_update(self, analysis: CoinAnalysis) -> None:
        if self.is_closing:
            return
        self._stream_table_pending[analysis.symbol] = analysis
        self._gr01_stream_submit_ns[analysis.symbol] = time.perf_counter_ns()
        # Do not restart an active timer: this creates a bounded 100 ms batch
        # window even when results arrive continuously.
        if not self.stream_table_timer.isActive():
            self.stream_table_timer.start()

    @_audit_gui_callback("stream_table_flush")
    def _flush_stream_table_updates(self) -> None:
        callback_started_ns = time.perf_counter_ns()
        if self.is_closing or self._stream_table_flush_running:
            return
        if not self._stream_table_pending:
            return

        diff_started_ns = time.perf_counter_ns()
        max_rows = max(1, int(self._stream_table_max_rows_per_slice))
        symbols = list(self._stream_table_pending)[:max_rows]
        submit_times = [self._gr01_stream_submit_ns.pop(symbol, 0) for symbol in symbols]
        pending = [self._stream_table_pending.pop(symbol) for symbol in symbols]
        has_more = bool(self._stream_table_pending)
        table_diff_ms = (time.perf_counter_ns() - diff_started_ns) / 1_000_000.0
        valid_submit_times = [value for value in submit_times if value]
        queue_wait_ms = (
            max(0.0, (callback_started_ns - min(valid_submit_times)) / 1_000_000.0)
            if valid_submit_times else None
        )
        item_update_ms = 0.0
        layout_ms = 0.0
        repaint_request_ms = 0.0
        sorting_was_enabled = False
        self._stream_table_flush_running = True
        try:
            context = (
                self.ui_profiler.section("stream_table_batch_commit")
                if hasattr(self, "ui_profiler")
                else nullcontext()
            )
            with context:
                sorting_was_enabled = self.table.isSortingEnabled()
                layout_started_ns = time.perf_counter_ns()
                self.table.setUpdatesEnabled(False)
                self.table.blockSignals(True)
                if sorting_was_enabled:
                    self.table.setSortingEnabled(False)
                layout_ms += (time.perf_counter_ns() - layout_started_ns) / 1_000_000.0
                try:
                    update_started_ns = time.perf_counter_ns()
                    for analysis in pending:
                        self._upsert_row(analysis, manage_sorting=False)
                    item_update_ms = (time.perf_counter_ns() - update_started_ns) / 1_000_000.0
                    if not has_more:
                        layout_started_ns = time.perf_counter_ns()
                        if sorting_was_enabled:
                            self.table.setSortingEnabled(True)
                            self.table.sortItems(1, Qt.SortOrder.DescendingOrder)
                        self._rebuild_row_index()
                        layout_ms += (time.perf_counter_ns() - layout_started_ns) / 1_000_000.0
                finally:
                    layout_started_ns = time.perf_counter_ns()
                    if (
                        not has_more
                        and sorting_was_enabled
                        and not self.table.isSortingEnabled()
                    ):
                        self.table.setSortingEnabled(True)
                    self.table.blockSignals(False)
                    self.table.setUpdatesEnabled(True)
                    layout_ms += (time.perf_counter_ns() - layout_started_ns) / 1_000_000.0
                    repaint_started_ns = time.perf_counter_ns()
                    self.paint_scheduler.request(self.table.viewport(), priority=20)
                    repaint_request_ms = (time.perf_counter_ns() - repaint_started_ns) / 1_000_000.0
        finally:
            self._stream_table_flush_running = False
            if self._stream_table_pending and not self.is_closing:
                self.stream_table_timer.start(self._stream_table_slice_delay_ms)
            total_callback_ms = (time.perf_counter_ns() - callback_started_ns) / 1_000_000.0
            GR01_GUI_FORENSICS.emit(
                "stream_flush_chunk",
                generation=int(getattr(self, "_scan_cycle_count", 0) or 0),
                queue_wait_ms=queue_wait_ms,
                data_prepare_ms=0.0,
                model_transform_ms=0.0,
                table_diff_ms=table_diff_ms,
                widget_create_ms=0.0,
                item_update_ms=item_update_ms,
                layout_ms=layout_ms,
                repaint_request_ms=repaint_request_ms,
                total_callback_ms=total_callback_ms,
                rows_total=len(pending),
                rows_changed=len(pending),
                rows_remaining=len(self._stream_table_pending),
                chunk_index=None,
                is_final_chunk=not bool(self._stream_table_pending),
                gui_thread_ident=threading.get_ident(),
            )

    @Slot(object)
    @_audit_gui_callback("scan_result_callback")
    def on_result(self, a: CoinAnalysis):
        """Ingest one immutable result without performing secondary work."""
        if self.is_closing:
            return

        _previous = self.results.get(a.symbol)
        if _previous is not None and _previous is not a:
            COIN_ANALYSIS_TOKENS.owner_release(
                _previous, "MainWindow.results", cycle_index=self._scan_cycle_count,
                mutation_site="MainWindow.on_result:replace_symbol",
            )
        self.results[a.symbol] = a
        COIN_ANALYSIS_TOKENS.owner_enter(
            a, "MainWindow.results", cycle_index=self._scan_cycle_count,
            mutation_site="MainWindow.on_result:assign_symbol",
        )
        self.failed.pop(a.symbol, None)
        queue_before = len(self._scan_result_side_effect_queue)
        self._scan_result_side_effect_queue.append(
            (a, getattr(self, "current_scan_id", None))
        )
        COIN_ANALYSIS_TOKENS.owner_enter(
            a, "MainWindow._scan_result_side_effect_queue",
            cycle_index=self._scan_cycle_count,
            mutation_site="MainWindow.on_result:queue_append",
        )
        self._retention_owner_telemetry.record_mutation(
            "scan_result_side_effect_queue",
            operation="append",
            count_before=queue_before,
            count_after=len(self._scan_result_side_effect_queue),
            item_count=1,
        )

        if not self.scan_result_side_effect_timer.isActive():
            self.scan_result_side_effect_timer.start()

    @_audit_gui_callback(
        "scan_result_side_effect_drain",
        record_threshold_ms=10.0,
    )
    def _drain_scan_result_side_effects(self) -> None:
        if self.is_closing or self._scan_result_side_effect_running:
            return

        if not self._scan_result_side_effect_queue:
            if self._scan_finished_waiting_for_result_drain:
                self._complete_scan_after_result_drain()
            return

        self._scan_result_side_effect_running = True
        queue_before = len(self._scan_result_side_effect_queue)
        analysis, scan_id = self._scan_result_side_effect_queue.pop(0)
        COIN_ANALYSIS_TOKENS.owner_release(
            analysis, "MainWindow._scan_result_side_effect_queue",
            cycle_index=self._scan_cycle_count,
            mutation_site="MainWindow._drain_scan_result_side_effects:pop",
        )
        self._retention_owner_telemetry.record_mutation(
            "scan_result_side_effect_queue",
            operation="pop",
            count_before=queue_before,
            count_after=len(self._scan_result_side_effect_queue),
            item_count=1,
        )
        total_started = time.perf_counter()
        table_schedule_ms = 0.0
        recorder_enqueue_ms = 0.0
        capture_submit_ms = 0.0
        truth_seed_ms = 0.0
        aggregate_schedule_ms = 0.0

        failure = None
        try:
            if analysis.symbol != "BTC/USDT:USDT":
                phase_started = time.perf_counter()
                self._schedule_stream_table_update(analysis)
                table_schedule_ms = (
                    time.perf_counter() - phase_started
                ) * 1000.0

                phase_started = time.perf_counter()
                if not self._enqueue_result_dispatch("record", analysis, scan_id):
                    logger.warning(
                        "Signal recorder dispatch queue full for %s",
                        analysis.symbol,
                    )
                recorder_enqueue_ms = (
                    time.perf_counter() - phase_started
                ) * 1000.0

                if self.live_episode_capture is not None:
                    phase_started = time.perf_counter()
                    try:
                        capture_key = self._capture_key(analysis, scan_id)
                        analysis_object_id = id(analysis)
                        self._capture_key_by_analysis_id[analysis_object_id] = capture_key
                        self._analysis_id_by_capture_key[capture_key] = analysis_object_id
                        created_now = capture_key not in self._capture_latency_started_by_key
                        self._capture_latency_started_by_key.setdefault(
                            capture_key,
                            time.monotonic(),
                        )
                        self._rc647_capture_submitted_keys.add(capture_key)
                        self._record_identity_diagnostic(
                            "identity_capture_submitted",
                            capture_key,
                            created_new_tracker=bool(created_now),
                            analysis_object_id=hex(id(analysis)),
                        )
                        if not self._enqueue_result_dispatch(
                            "capture", analysis, scan_id
                        ):
                            logger.warning(
                                "Live episode capture dispatch queue full for %s",
                                analysis.symbol,
                            )
                    except Exception:
                        logger.exception(
                            "Live episode capture submit failed for %s",
                            analysis.symbol,
                        )
                    capture_submit_ms = (
                        time.perf_counter() - phase_started
                    ) * 1000.0

            if hasattr(self, "truth_dashboard") and self.current_analysis is None:
                phase_started = time.perf_counter()
                self._set_truth_pending_reference(analysis, mutation_site="scan_result_side_effect_drain")
                if (
                    self.tabs.currentWidget() is self.truth_dashboard
                    and not getattr(
                        self,
                        "_truth_dashboard_seed_pending",
                        False,
                    )
                ):
                    self._truth_dashboard_seed_pending = True
                    self._schedule_truth_dashboard_seed(
                        analysis, mutation_site="scan_result_side_effect_drain"
                    )
                truth_seed_ms = (
                    time.perf_counter() - phase_started
                ) * 1000.0

            phase_started = time.perf_counter()
            self._schedule_aggregate_refresh()
            aggregate_schedule_ms = (
                time.perf_counter() - phase_started
            ) * 1000.0
        except Exception as exc:
            failure = exc
            logger.exception(
                "SCAN_RESULT_SIDE_EFFECT_DRAIN_FAILED scan_id=%s symbol=%s queue_remaining=%s",
                scan_id,
                str(getattr(analysis, "symbol", "UNKNOWN")),
                len(self._scan_result_side_effect_queue),
            )
            log_gui_exception(
                context="scan_result_side_effect_drain",
                symbol=str(getattr(analysis, "symbol", "UNKNOWN")),
                exc=exc,
            )
            self._record_scan_liveness(
                "result_drain_exception",
                symbol=str(getattr(analysis, "symbol", "UNKNOWN")),
                queue_depth_after=len(self._scan_result_side_effect_queue),
                exception_type=type(exc).__name__,
                exception_message=str(exc),
            )
        finally:
            self._scan_result_side_effect_running = False
            total_ms = (time.perf_counter() - total_started) * 1000.0
            self._record_gui_hotspot(
                "scan_result_side_effect_pipeline",
                total_ms,
                symbol=str(getattr(analysis, "symbol", "UNKNOWN")),
                queue_remaining=len(self._scan_result_side_effect_queue),
                table_schedule_ms=round(table_schedule_ms, 3),
                recorder_enqueue_ms=round(recorder_enqueue_ms, 3),
                capture_submit_ms=round(capture_submit_ms, 3),
                truth_seed_ms=round(truth_seed_ms, 3),
                aggregate_schedule_ms=round(
                    aggregate_schedule_ms,
                    3,
                ),
                status="failed" if failure is not None else "completed",
            )
            GR01_GUI_FORENSICS.emit(
                "scan_result_side_effect_drain",
                generation=int(getattr(self, "_scan_cycle_count", 0) or 0),
                queue_wait_ms=None,
                data_prepare_ms=capture_submit_ms,
                model_transform_ms=truth_seed_ms,
                table_diff_ms=table_schedule_ms,
                widget_create_ms=0.0,
                item_update_ms=recorder_enqueue_ms,
                layout_ms=aggregate_schedule_ms,
                repaint_request_ms=0.0,
                total_callback_ms=total_ms,
                rows_total=1,
                rows_changed=1,
                queue_remaining=len(self._scan_result_side_effect_queue),
                symbol=str(getattr(analysis, "symbol", "UNKNOWN")),
                status="failed" if failure is not None else "completed",
                gui_thread_ident=threading.get_ident(),
            )
            self._reconcile_scan_result_drain_state()

    def _reconcile_scan_result_drain_state(self) -> None:
        """Re-arm result draining or complete the cycle exactly once.

        The guard prevents nested timer/callback entry.  Failures are always
        persisted through both the logger and GUI crash report; a bounded
        single-shot retry preserves liveness without hiding the failure.
        """
        if self._scan_result_reconcile_running:
            self._record_scan_liveness("result_drain_reconcile_reentrant_blocked")
            return
        self._scan_result_reconcile_running = True
        try:
            if self.is_closing:
                return
            if self._scan_result_side_effect_queue:
                if not self.scan_result_side_effect_timer.isActive():
                    self.scan_result_side_effect_timer.start(5)
                self._record_scan_liveness(
                    "result_drain_rearmed",
                    queue_depth=len(self._scan_result_side_effect_queue),
                )
            elif self._scan_finished_waiting_for_result_drain:
                self._record_scan_liveness("result_drain_completion_scheduled")
                QTimer.singleShot(0, self._complete_scan_after_result_drain)
        except Exception as exc:
            logger.exception("SCAN_RESULT_DRAIN_RECONCILE_FAILED")
            log_gui_exception(
                context="scan_result_drain_reconcile", exc=exc
            )
            self._record_scan_liveness(
                "result_drain_reconcile_exception",
                exception_type=type(exc).__name__,
                exception_message=str(exc),
            )
            QTimer.singleShot(50, self._reconcile_scan_result_drain_state)
        finally:
            self._scan_result_reconcile_running = False

    def _seed_truth_dashboard_once(self, analysis: CoinAnalysis) -> None:
        self._truth_dashboard_seed_pending = False
        if self.is_closing:
            return
        if not hasattr(self, "truth_dashboard"):
            return
        self._set_truth_pending_reference(analysis, mutation_site="truth_dashboard_refresh")
        # Hidden dashboards do no database/history/render work. The latest
        # analysis is committed lazily by _on_tab_changed when the tab opens.
        if not self._is_truth_workspace_visible():
            return
        selected = self.current_analysis or analysis
        started = time.perf_counter()
        self._set_truth_dashboard_analysis(selected, mutation_site="_seed_truth_dashboard_once:visible")
        self._set_truth_pending_reference(None, mutation_site="_seed_truth_dashboard_once:committed")
        self._record_callback_attribution(
            "truth_dashboard_initial_seed",
            (time.perf_counter() - started) * 1000.0,
            symbol=str(getattr(selected, "symbol", "UNKNOWN")),
        )

    @Slot(str, float)
    def _on_signal_record_completed(self, symbol: str, duration_ms: float) -> None:
        callback_started_ns = time.perf_counter_ns()
        if duration_ms >= 100.0:
            self._record_callback_attribution(
                "signal_record_worker",
                duration_ms,
                symbol=symbol,
                worker_thread=True,
                status="completed",
            )
        gui_execution_ms = (time.perf_counter_ns() - callback_started_ns) / 1_000_000.0
        GR01_GUI_FORENSICS.emit(
            "signal_record_gui_commit",
            generation=int(getattr(self, "_scan_cycle_count", 0) or 0),
            queue_wait_ms=None,
            data_prepare_ms=float(duration_ms),
            model_transform_ms=0.0,
            table_diff_ms=0.0,
            widget_create_ms=0.0,
            item_update_ms=gui_execution_ms,
            layout_ms=0.0,
            repaint_request_ms=0.0,
            total_callback_ms=gui_execution_ms,
            symbol=str(symbol),
            status="completed",
            gui_thread_ident=threading.get_ident(),
        )

    @Slot(str, str, float)
    def _on_signal_record_failed(
        self,
        symbol: str,
        message: str,
        duration_ms: float,
    ) -> None:
        callback_started_ns = time.perf_counter_ns()
        logger.error("Signal recorder failed for %s: %s", symbol, message)
        self._record_callback_attribution(
            "signal_record_worker",
            duration_ms,
            symbol=symbol,
            worker_thread=True,
            status="failed",
            error=message,
        )
        gui_execution_ms = (time.perf_counter_ns() - callback_started_ns) / 1_000_000.0
        GR01_GUI_FORENSICS.emit(
            "signal_record_gui_commit",
            generation=int(getattr(self, "_scan_cycle_count", 0) or 0),
            queue_wait_ms=None,
            data_prepare_ms=float(duration_ms),
            model_transform_ms=0.0,
            table_diff_ms=0.0,
            widget_create_ms=0.0,
            item_update_ms=gui_execution_ms,
            layout_ms=0.0,
            repaint_request_ms=0.0,
            total_callback_ms=gui_execution_ms,
            symbol=str(symbol),
            status="failed",
            error=str(message),
            gui_thread_ident=threading.get_ident(),
        )

    def _restore_scroll_value(self, scroll_bar, value):
        if scroll_bar is None:
            return
        maximum = max(0, scroll_bar.maximum())
        scroll_bar.setValue(max(0, min(int(value), maximum)))

    def _restore_detail_view_state(self):
        if self.is_closing:
            return
        if hasattr(self, "detail_scroll_area"):
            self._restore_scroll_value(
                self.detail_scroll_area.verticalScrollBar(),
                getattr(self, "_scan_outer_scroll", 0),
            )
        if hasattr(self, "detail_text"):
            self._restore_scroll_value(
                self.detail_text.verticalScrollBar(),
                getattr(self, "_scan_detail_scroll", 0),
            )
        if hasattr(self, "score_explain"):
            self._restore_scroll_value(
                self.score_explain.verticalScrollBar(),
                getattr(self, "_scan_score_scroll", 0),
            )
        if (
            getattr(self, "_scan_had_detail_focus", False)
            and hasattr(self, "detail_scroll_area")
        ):
            self.detail_scroll_area.setFocus(
                Qt.FocusReason.OtherFocusReason
            )

    def _schedule_detail_state_restore(self):
        for delay in (0, 40, 140):
            QTimer.singleShot(delay, self._restore_detail_view_state)

    @Slot()
    @_audit_gui_callback("scan_finished_callback")
    def on_finished(self):
        self._record_scan_liveness("on_finished_enter")
        if self.is_closing:
            self._record_scan_liveness("on_finished_blocked_shutdown")
            return

        self._scan_finished_waiting_for_result_drain = True
        if self._scan_result_side_effect_queue:
            if not self.scan_result_side_effect_timer.isActive():
                self.scan_result_side_effect_timer.start(0)
            self._record_scan_liveness(
                "result_drain_wait",
                queue_depth=len(self._scan_result_side_effect_queue),
            )
            self.status.setText(
                "Đang hoàn tất pipeline kết quả quét..."
            )
            return

        self._complete_scan_after_result_drain()

    def _complete_scan_after_result_drain(self) -> None:
        if self.is_closing:
            return
        if self._scan_result_side_effect_queue:
            if not self.scan_result_side_effect_timer.isActive():
                self.scan_result_side_effect_timer.start(0)
            return

        self._scan_finished_waiting_for_result_drain = False
        self._record_scan_liveness("result_drain_complete")
        if self.stream_table_timer.isActive():
            self.stream_table_timer.stop()
        self._flush_stream_table_updates()
        if self.aggregate_refresh_timer.isActive():
            self.aggregate_refresh_timer.stop()
        self._flush_aggregate_refresh()
        self.progress.setValue(self.progress.maximum())
        self._start_async_finalization()

    def _start_async_finalization(self):
        if (
            self.finalization_thread is not None
            and self.finalization_thread.isRunning()
        ):
            self._record_scan_launch_decision(
                "BLOCKED_FINALIZATION_RUNNING", source="_start_async_finalization",
            )
            return
        self._record_scan_liveness("finalization_start")

        self.status.setText("Đang tổng hợp, xếp hạng và xác nhận vi cấu trúc...")
        self.scan_info.setText("Finalizing…")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.retry_btn.setEnabled(False)

        self.finalization_thread = QThread(self)
        self.finalization_worker = FinalizationWorker(
            self.service,
            dict(self.results),
            confidence_calibration_max_boost=(
                self.config.confidence_calibration_max_boost
            ),
            opportunity_min_score=self.config.opportunity_min_score,
            microstructure_enabled=self.config.microstructure_enabled,
            microstructure_top_n=self.config.microstructure_top_n,
            microstructure_weight=self.config.microstructure_weight,
            microstructure_confirm_bonus=(
                self.config.microstructure_confirm_bonus
            ),
            microstructure_conflict_penalty=(
                self.config.microstructure_conflict_penalty
            ),
        )
        self.finalization_worker.moveToThread(self.finalization_thread)
        self.finalization_thread.started.connect(
            self.finalization_worker.run
        )
        self.finalization_worker.finished.connect(
            self._on_finalization_finished
        )
        self.finalization_worker.error.connect(
            self._on_finalization_error
        )
        # S4.1.2-r1 (corrected): quit() must be causally dependent on the
        # worker's actual C++ destruction, not merely posted from the same
        # signal. worker.deleteLater() (DirectConnection, posted to the
        # worker-thread's own queue) and thread.quit() (QueuedConnection,
        # posted to the GUI-thread's queue) are two independent queues with
        # no ordering guarantee between them when both are wired from
        # finished/error directly. Chaining through destroyed enforces:
        # deleteLater() -> worker-thread processes DeferredDelete -> C++
        # object destroyed -> destroyed signal fires -> only then is
        # thread.quit() requested.
        self.finalization_worker.finished.connect(
            self.finalization_worker.deleteLater
        )
        self.finalization_worker.error.connect(
            self.finalization_worker.deleteLater
        )
        self.finalization_worker.destroyed.connect(
            self.finalization_thread.quit
        )
        self.finalization_thread.finished.connect(
            self.finalization_thread.deleteLater
        )
        self.finalization_thread.finished.connect(
            self._cleanup_finalization_worker
        )
        self.finalization_thread.start()

    @Slot(object)
    @_audit_gui_callback("finalization_finished_callback", record_threshold_ms=100.0)
    def _on_finalization_finished(self, payload):
        if self.is_closing:
            return
        callback_started_ns = time.perf_counter_ns()
        worker_finished_ns = int(payload.get("worker_finished_monotonic_ns", 0) or 0) if isinstance(payload, dict) else 0
        queue_wait_ms = max(0.0, (callback_started_ns - worker_finished_ns) / 1_000_000.0) if worker_finished_ns else None
        if hasattr(self, "ui_profiler"):
            with self.ui_profiler.section("finalization_gui_commit"):
                self._commit_finalization_payload(payload)
            self.ui_profiler.log_report("finalization_finished")
        else:
            self._commit_finalization_payload(payload)
        execution_ms = (time.perf_counter_ns() - callback_started_ns) / 1_000_000.0
        self._append_rc63_jsonl("finalization_callback_forensics.jsonl", {
            "schema_version": "dvs.runtime.finalization_callback.v2",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "runtime_session_id": self._runtime_session_id,
            "event": "finalization_gui_callback",
            "scan_cycle_id": self._scan_cycle_count,
            "queue_wait_ms": None if queue_wait_ms is None else round(queue_wait_ms, 3),
            "execution_ms": round(execution_ms, 3),
            "post_commit_deferred": True,
            "commit_phase_telemetry": True,
        })
        GR01_GUI_FORENSICS.emit(
            "finalization_finished_callback",
            generation=int(getattr(self, "_scan_cycle_count", 0) or 0),
            queue_wait_ms=queue_wait_ms,
            data_prepare_ms=0.0,
            model_transform_ms=0.0,
            table_diff_ms=0.0,
            widget_create_ms=0.0,
            item_update_ms=execution_ms,
            layout_ms=0.0,
            repaint_request_ms=0.0,
            total_callback_ms=execution_ms,
            gui_thread_ident=threading.get_ident(),
        )

    def _commit_finalization_payload(self, payload):
        commit_started = time.perf_counter()
        self._finalization_commit_count += 1
        commit_id = self._finalization_commit_count
        results_before = len(self.results)
        table_rows_before = self.table.rowCount()
        pending_stream_count = len(self._stream_table_pending)
        diff_before = dict(self._table_diff_metrics)

        finalized_results = dict(payload.get("results", {}))
        previous_results = self.results
        for _analysis in previous_results.values():
            COIN_ANALYSIS_TOKENS.owner_release(
                _analysis, "MainWindow.results", cycle_index=self._scan_cycle_count,
                mutation_site="MainWindow._commit_finalization_payload:old_results_release",
            )
        self.results = finalized_results
        for _analysis in self.results.values():
            COIN_ANALYSIS_TOKENS.owner_enter(
                _analysis, "MainWindow.results", cycle_index=self._scan_cycle_count,
                mutation_site="MainWindow._commit_finalization_payload:new_results_enter",
            )
        self._retention_owner_telemetry.record_container_replaced(
            "scan_results",
            old_container=previous_results,
            new_container=self.results,
            replacement_reason="finalization_payload_commit",
        )
        # Preserve the user's *current* selection at commit time.  The user may
        # have navigated or selected another symbol while the scan was running;
        # restoring the launch-time selection caused visible UI "jumps".
        selected_symbol = None
        current_row = self.table.currentRow()
        if current_row >= 0:
            current_item = self.table.item(current_row, 0)
            if current_item is not None:
                selected_symbol = current_item.text()
        if not selected_symbol and self.current_analysis is not None:
            selected_symbol = self.current_analysis.symbol
        current_table_scroll = self.table.verticalScrollBar().value()
        timing_ms = {
            "lock_gui_ms": 0.0,
            "remove_stale_ms": 0.0,
            "build_rows_ms": 0.0,
            "sort_ms": 0.0,
            "row_index_rebuild_ms": 0.0,
            "restore_gui_ms": 0.0,
        }
        rows_removed = 0
        rows_considered = 0
        rows_updated = 0
        rows_unchanged = 0

        # RC5 delta-only finalization. Streaming updates have already projected
        # most scan results into the table. Finalization now removes stale rows
        # and upserts only visible projections that actually changed.
        phase_started = time.perf_counter()
        sorting_was_enabled = self.table.isSortingEnabled()
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        if sorting_was_enabled:
            GR01_GUI_FORENSICS.emit(
                "f3_r4_finalization_sort_disable_enter",
                generation=int(getattr(self, "_scan_cycle_count", 0) or 0),
                scan_id=str(getattr(self, "current_scan_id", "") or ""),
                sorting_was_enabled=bool(sorting_was_enabled),
            )
            self.table.setSortingEnabled(False)
            GR01_GUI_FORENSICS.emit(
                "f3_r4_finalization_sort_disable_exit",
                generation=int(getattr(self, "_scan_cycle_count", 0) or 0),
                scan_id=str(getattr(self, "current_scan_id", "") or ""),
                sorting_enabled_after=bool(self.table.isSortingEnabled()),
            )
        timing_ms["lock_gui_ms"] = (time.perf_counter() - phase_started) * 1000.0
        try:
            phase_started = time.perf_counter()
            valid_symbols = {symbol for symbol in finalized_results if symbol != "BTC/USDT:USDT"}
            stale_symbols = [symbol for symbol in tuple(self._row_by_symbol) if symbol not in valid_symbols]
            stale_rows = sorted((self._row_by_symbol[symbol] for symbol in stale_symbols), reverse=True)
            for row in stale_rows:
                if 0 <= row < self.table.rowCount():
                    self.table.removeRow(row)
                    rows_removed += 1
            for symbol in stale_symbols:
                self._row_by_symbol.pop(symbol, None)
                self._table_fingerprint_by_symbol.pop(symbol, None)
            if rows_removed:
                self._rebuild_row_index()
            timing_ms["remove_stale_ms"] = (time.perf_counter() - phase_started) * 1000.0

            phase_started = time.perf_counter()
            for symbol, analysis in finalized_results.items():
                if symbol == "BTC/USDT:USDT":
                    continue
                rows_considered += 1
                fingerprint = self._analysis_table_fingerprint(analysis)
                row = self._row_by_symbol.get(symbol, -1)
                if row >= 0 and row < self.table.rowCount() and self._table_fingerprint_by_symbol.get(symbol) == fingerprint:
                    rows_unchanged += 1
                    continue
                self._upsert_row(analysis, manage_sorting=False)
                rows_updated += 1
            timing_ms["build_rows_ms"] = (time.perf_counter() - phase_started) * 1000.0
        finally:
            phase_started = time.perf_counter()
            # V2.4.2: streaming projection normally leaves every final row
            # unchanged. Avoid a full Qt sort + index rebuild when the delta is
            # empty; these calls were the dominant hidden GUI cost.
            table_delta_changed = bool(rows_updated or rows_removed)
            GR01_GUI_FORENSICS.emit(
                "f3_r4_finalization_sort_restore_enter",
                generation=int(getattr(self, "_scan_cycle_count", 0) or 0),
                scan_id=str(getattr(self, "current_scan_id", "") or ""),
                rows_updated=int(rows_updated),
                rows_removed=int(rows_removed),
                table_delta_changed=bool(table_delta_changed),
                sorting_enabled_before=bool(self.table.isSortingEnabled()),
            )
            self.table.setSortingEnabled(True)
            GR01_GUI_FORENSICS.emit(
                "f3_r4_finalization_sort_restore_exit",
                generation=int(getattr(self, "_scan_cycle_count", 0) or 0),
                scan_id=str(getattr(self, "current_scan_id", "") or ""),
                sorting_enabled_after=bool(self.table.isSortingEnabled()),
            )
            if table_delta_changed:
                self.table.sortItems(1, Qt.SortOrder.DescendingOrder)
            timing_ms["sort_ms"] = (time.perf_counter() - phase_started) * 1000.0

            phase_started = time.perf_counter()
            if table_delta_changed:
                self._rebuild_row_index()
            timing_ms["row_index_rebuild_ms"] = (time.perf_counter() - phase_started) * 1000.0

            phase_started = time.perf_counter()
            restore_row = self._row_by_symbol.get(selected_symbol, -1)
            if restore_row >= 0:
                self.table.selectRow(restore_row)
            # Sorting and delta updates must not reset the operator's viewport.
            scroll_bar = self.table.verticalScrollBar()
            scroll_bar.setValue(min(current_table_scroll, scroll_bar.maximum()))
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)
            self.paint_scheduler.request(self.table.viewport(), priority=20)
            timing_ms["restore_gui_ms"] = (time.perf_counter() - phase_started) * 1000.0

        table_rows_after = self.table.rowCount()
        diff_after = dict(self._table_diff_metrics)
        metrics = {
            "session_id": self._runtime_session_id,
            "pid": os.getpid(),
            "scan_cycle_id": self._scan_cycle_count,
            "commit_id": commit_id,
            "commit_strategy": "delta_only",
            "results_before": results_before,
            "results_after": len(self.results),
            "table_rows_before": table_rows_before,
            "table_rows_after": table_rows_after,
            "pending_stream_count": pending_stream_count,
            "rows_considered": rows_considered,
            "rows_updated": rows_updated,
            "rows_unchanged": rows_unchanged,
            "rows_removed": rows_removed,
            "rows_inserted": diff_after["rows_inserted"] - diff_before["rows_inserted"],
            "cells_checked": diff_after["cells_checked"] - diff_before["cells_checked"],
            "cells_changed": diff_after["cells_changed"] - diff_before["cells_changed"],
            "items_created": diff_after["items_created"] - diff_before["items_created"],
            "style_changes": diff_after["style_changes"] - diff_before["style_changes"],
            **{key: round(value, 3) for key, value in timing_ms.items()},
            "total_commit_ms": round((time.perf_counter() - commit_started) * 1000.0, 3),
        }
        logger.info(
            "FINALIZATION_GUI_COMMIT_METRICS %s",
            json.dumps(metrics, sort_keys=True, ensure_ascii=False),
        )
        self._record_gui_hotspot(
            "finalization_gui_commit_total",
            metrics["total_commit_ms"],
            commit_id=commit_id,
            rows_considered=rows_considered,
            rows_updated=rows_updated,
            rows_unchanged=rows_unchanged,
            rows_removed=rows_removed,
            lock_gui_ms=metrics["lock_gui_ms"],
            remove_stale_ms=metrics["remove_stale_ms"],
            build_rows_ms=metrics["build_rows_ms"],
            sort_ms=metrics["sort_ms"],
            row_index_rebuild_ms=metrics["row_index_rebuild_ms"],
            restore_gui_ms=metrics["restore_gui_ms"],
        )
        if hasattr(self, "ui_profiler"):
            burn_in = self.ui_profiler.record_commit_metrics(metrics)
            if commit_id % self._burn_in_summary_interval == 0:
                burn_in_payload = {
                    "session_id": self._runtime_session_id,
                    "pid": os.getpid(),
                    "scan_cycle_id": self._scan_cycle_count,
                    **burn_in,
                    "table_rows": table_rows_after,
                    "fingerprint_cache_size": len(self._table_fingerprint_by_symbol),
                    "row_cache_size": len(self._row_by_symbol),
                }
                logger.info(
                    "PERFORMANCE_SUMMARY %s",
                    json.dumps(burn_in_payload, sort_keys=True, ensure_ascii=False),
                )
                if (
                    burn_in["rolling_window"] >= 20
                    and burn_in["slope_ms_per_commit"] > 1.0
                ):
                    logger.warning(
                        "PERFORMANCE_DRIFT_DETECTED %s",
                        json.dumps(burn_in_payload, sort_keys=True, ensure_ascii=False),
                    )
            if commit_id % self._display_integrity_interval == 0:
                self._audit_display_integrity(commit_id)

        # Navigation is user-owned state.  Scan/finalization refreshes must
        # never force the application back to the page that was active when the
        # scan started.  This previously caused the workspace to jump to another
        # board whenever a scan completed.

        if self.config.universe_enabled:
            self.status.setText(
                f"Quét sâu xong {len(self.results)}/"
                f"{len(self.market_universe)} universe; "
                f"lỗi {len(self.failed)}"
            )
        else:
            self.status.setText(
                f"Đã quét xong {len(self.results)} mã; "
                f"lỗi {len(self.failed)}"
            )

        self.scan_info.setText(
            f"Hoàn tất {datetime.now().strftime('%H:%M:%S')}"
        )
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.retry_btn.setEnabled(bool(self.failed))

        # Sprint A2 V1: eliminate the synchronous five-refresh burst. Each
        # refresh is coalesced and dispatched on a separate event-loop turn.
        self._schedule_standard_post_commit_refreshes("scan_finalization")

        post_state = {
            "selected_symbol": selected_symbol,
            "queue_scan_id": str(getattr(self, "current_scan_id", "")),
            "scheduled_ns": time.perf_counter_ns(),
            "commit_id": commit_id,
        }
        QTimer.singleShot(0, lambda state=post_state: self._run_finalization_post_commit(state))

        if self.auto_scan_btn.isChecked():
            self.auto_scan_seconds = self.config.refresh_seconds
            self.auto_scan_btn.setText(
                f"Tự quét: {self.config.refresh_seconds}s"
            )

    def _run_finalization_post_commit(self, state: dict) -> None:
        started_ns = time.perf_counter_ns()
        selected_symbol = state.get("selected_symbol")
        phase_ms = {}

        phase_started = time.perf_counter_ns()
        try:
            self._retention_owner_telemetry.snapshot(cycle_index=self._scan_cycle_count)
            COIN_ANALYSIS_TOKENS.cycle_snapshot(cycle_index=self._scan_cycle_count)
            PAYLOAD_FOOTPRINT_TELEMETRY.snapshot(
                cycle_index=self._scan_cycle_count,
                results=self.results,
                current_analysis=getattr(self, "current_analysis", None),
                pending_analysis=getattr(self, "_truth_dashboard_pending_analysis", None),
            )
        except Exception:
            logger.exception("RETENTION_OWNER_SNAPSHOT_FAILED cycle=%s", self._scan_cycle_count)
        phase_ms["retention_snapshot_ms"] = (time.perf_counter_ns() - phase_started) / 1_000_000.0

        phase_started = time.perf_counter_ns()
        restore_row = self._row_by_symbol.get(selected_symbol, -1)
        if restore_row >= 0 and selected_symbol in self.results:
            detail_widget = self.detail_scroll_area if hasattr(self, "detail_scroll_area") else self
            if hasattr(self, "ui_geometry"):
                with self.ui_geometry.freeze(detail_widget):
                    self.show_selected(preserve_timeframe=True, preserve_scroll=False)
            else:
                self.show_selected(preserve_timeframe=True, preserve_scroll=False)
            snapshot = getattr(self, "_scan_ui_snapshot", None)
            if snapshot is not None and hasattr(self, "ui_geometry"):
                self.ui_geometry.schedule_view_restore(snapshot)
            else:
                self._schedule_detail_state_restore()
        phase_ms["detail_projection_ms"] = (time.perf_counter_ns() - phase_started) / 1_000_000.0

        phase_started = time.perf_counter_ns()
        old_auto_paper_queue = self._auto_paper_queue
        self._auto_paper_queue = []
        self._retention_owner_telemetry.record_container_replaced(
            "auto_paper_queue", old_container=old_auto_paper_queue,
            new_container=self._auto_paper_queue, replacement_reason="new_finalization_batch",
            account_payload_delta=False,
        )
        self._auto_paper_prepare_state = {
            "items": list(self.results.items()), "index": 0,
            "queue_scan_id": state.get("queue_scan_id", ""),
            "queued_at": time.monotonic(), "commit_id": state.get("commit_id"),
            "started_ns": time.perf_counter_ns(), "turns": 0,
        }
        phase_ms["auto_paper_prepare_schedule_ms"] = (time.perf_counter_ns() - phase_started) / 1_000_000.0
        QTimer.singleShot(0, self._drain_auto_paper_prepare)
        QTimer.singleShot(0, self._submit_qualification_batch)

        total_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0
        self._append_rc63_jsonl("finalization_callback_forensics.jsonl", {
            "schema_version": "dvs.runtime.finalization_callback.v2",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "runtime_session_id": self._runtime_session_id,
            "event": "finalization_post_commit",
            "scan_cycle_id": self._scan_cycle_count,
            "commit_id": state.get("commit_id"),
            "queue_wait_ms": round((started_ns - int(state.get("scheduled_ns", started_ns))) / 1_000_000.0, 3),
            **{key: round(value, 3) for key, value in phase_ms.items()},
            "execution_ms": round(total_ms, 3),
        })

    def _drain_auto_paper_prepare(self) -> None:
        state = self._auto_paper_prepare_state
        if not state or self.is_closing:
            return
        turn_started = time.perf_counter_ns(); processed = 0
        items = state["items"]
        while state["index"] < len(items):
            symbol, analysis = items[state["index"]]; state["index"] += 1; processed += 1
            if symbol != "BTC/USDT:USDT":
                item_started_ns = time.perf_counter_ns()
                op_started_ns = item_started_ns
                capture_key = self._capture_key(analysis, state["queue_scan_id"])
                capture_key_ms = (time.perf_counter_ns() - op_started_ns) / 1_000_000.0
                membership_started_ns = time.perf_counter_ns()
                capture_submitted = (
                    capture_key in self._rc647_capture_submitted_keys
                )
                eligible = bool(self.auto_paper_enabled)
                membership_ms = (time.perf_counter_ns() - membership_started_ns) / 1_000_000.0
                append_ms = owner_ms = retention_ms = diagnostic_ms = 0.0
                if eligible:
                    before=len(self._auto_paper_queue)
                    _write_auto_paper_pipeline_event(
                        "queue_candidate",
                        symbol=str(symbol),
                        capture_key=str(capture_key),
                        cycle_index=int(self._scan_cycle_count),
                        commit_id=str(state.get("commit_id", "")),
                        capture_submitted=bool(capture_submitted),
                        queue_before=int(before),
                    )
                    op_started_ns = time.perf_counter_ns()
                    self._auto_paper_queue.append((analysis,capture_key,state["queued_at"]))
                    append_ms = (time.perf_counter_ns() - op_started_ns) / 1_000_000.0
                    op_started_ns = time.perf_counter_ns()
                    COIN_ANALYSIS_TOKENS.owner_enter(analysis,"MainWindow._auto_paper_queue",cycle_index=self._scan_cycle_count,mutation_site="MainWindow._drain_auto_paper_prepare:auto_paper_append")
                    owner_ms = (time.perf_counter_ns() - op_started_ns) / 1_000_000.0
                    op_started_ns = time.perf_counter_ns()
                    self._retention_owner_telemetry.record_mutation("auto_paper_queue",operation="append",count_before=before,count_after=len(self._auto_paper_queue),item_count=1)
                    retention_ms = (time.perf_counter_ns() - op_started_ns) / 1_000_000.0
                    op_started_ns = time.perf_counter_ns()
                    self._record_identity_diagnostic("auto_paper_queue_created",capture_key,first_deferred_monotonic=round(float(state["queued_at"]),6),analysis_object_id=hex(id(analysis)))
                    diagnostic_ms = (time.perf_counter_ns() - op_started_ns) / 1_000_000.0
                item_ms = (time.perf_counter_ns() - item_started_ns) / 1_000_000.0
                if item_ms >= 16.0:
                    self._append_rc63_jsonl("auto_paper_prepare_item_forensics.jsonl", {
                        "schema_version": "dvs.runtime.auto_paper_prepare_item.v2.4.2",
                        "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
                        "runtime_session_id": self._runtime_session_id,
                        "event": "slow_auto_paper_prepare_item",
                        "commit_id": state.get("commit_id"), "symbol": symbol,
                        "eligible": bool(eligible),
                        "capture_submitted": bool(capture_submitted),
                        "item_ms": round(item_ms, 3),
                        "capture_key_ms": round(capture_key_ms, 3),
                        "membership_ms": round(membership_ms, 3),
                        "append_ms": round(append_ms, 3), "owner_ms": round(owner_ms, 3),
                        "retention_ms": round(retention_ms, 3),
                        "diagnostic_ms": round(diagnostic_ms, 3),
                    })
            elapsed=(time.perf_counter_ns()-turn_started)/1_000_000.0
            if processed >= self._auto_paper_prepare_max_items_per_turn or elapsed >= self._auto_paper_prepare_budget_ms:
                break
        state["turns"] += 1
        self._append_rc63_jsonl("finalization_callback_forensics.jsonl", {
            "schema_version":"dvs.runtime.finalization_callback.v2.4.1","timestamp_utc":datetime.utcnow().isoformat(timespec="milliseconds")+"Z","runtime_session_id":self._runtime_session_id,
            "event":"auto_paper_prepare_turn","commit_id":state.get("commit_id"),"turn_index":state["turns"],"processed_items":processed,"remaining_items":len(items)-state["index"],"execution_ms":round((time.perf_counter_ns()-turn_started)/1_000_000.0,3),"budget_ms":self._auto_paper_prepare_budget_ms})
        if state["index"] < len(items):
            QTimer.singleShot(0, self._drain_auto_paper_prepare)
        else:
            total_ms=(time.perf_counter_ns()-state["started_ns"])/1_000_000.0
            self._append_rc63_jsonl("finalization_callback_forensics.jsonl", {"schema_version":"dvs.runtime.finalization_callback.v2.4.1","timestamp_utc":datetime.utcnow().isoformat(timespec="milliseconds")+"Z","runtime_session_id":self._runtime_session_id,"event":"auto_paper_prepare_complete","commit_id":state.get("commit_id"),"turns":state["turns"],"queue_size":len(self._auto_paper_queue),"elapsed_ms":round(total_ms,3)})
            self._auto_paper_prepare_state=None
            QTimer.singleShot(0,self._process_auto_paper_batch)

    @_audit_gui_callback("qualification_batch_submit")
    def _submit_qualification_batch(self) -> None:
        runner = self.core_qualification_batch_runner
        if self.is_closing or runner is None or not self.results:
            return
        batch_id = f"scan-{time.time_ns()}"
        items = []
        for index, (symbol, analysis) in enumerate(self.results.items()):
            if symbol == "BTC/USDT:USDT":
                continue
            request_id = f"{batch_id}:{symbol}"
            cycle = self._build_unified_cycle_request(
                analysis,
                pipeline_run_id=f"gui-batch-shadow:{batch_id}:{symbol}",
            )
            if cycle is None:
                continue
            items.append(
                QualificationBatchItem(
                    cycle=cycle,
                    legacy_action=self._legacy_action_for_shadow(analysis),
                    analysis_revision=index,
                    request_id=request_id,
                    confidence=float(getattr(analysis, "confidence_score", 0.0)),
                    regime=str(getattr(getattr(analysis, "regime", None), "regime", "UNKNOWN")),
                    phase=str(getattr(analysis, "phase_summary", "UNKNOWN")),
                    timeframe=str(getattr(analysis, "timeframe", "15m")),
                )
            )
        if not items:
            return
        accepted = runner.submit_batch(
            QualificationBatch.from_items(items, batch_id=batch_id)
        )
        if accepted:
            self.status.setText(
                f"Qualification batch đã xếp hàng: {len(items)} paired cycles"
            )

    @Slot(object)
    @_audit_gui_callback("qualification_batch_progress")
    def _on_qualification_batch_progress(
        self, progress: QualificationBatchProgress
    ) -> None:
        if self.is_closing:
            return
        self.status.setText(
            f"Shadow qualification {progress.processed}/{progress.total} · "
            f"{progress.symbol} · ghi mới {progress.inserted} · lỗi {progress.failures}"
        )

    @Slot(object)
    @_audit_gui_callback("qualification_batch_completed", record_threshold_ms=100.0)
    def _on_qualification_batch_completed(
        self, summary: QualificationBatchSummary
    ) -> None:
        self._qualification_batch_last_summary = summary
        self._append_rc63_jsonl("targeted_owner_counters.jsonl", {
            "schema_version": "dvs.runtime.targeted_owner_counters.v1",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "runtime_session_id": self._runtime_session_id,
            "event": "shadow_owner_counters_after_batch",
            "batch_id": summary.batch_id,
            "processed": int(summary.processed),
            "failures": int(summary.failures),
            "shadow_prepared_runs_count": int(summary.shadow_prepared_runs_count),
            "shadow_paper_orders_count": int(summary.shadow_paper_orders_count),
            "shadow_ledger_run_count": int(summary.shadow_ledger_run_count),
            "shadow_release_run_total": int(summary.shadow_release_run_total),
            "shadow_discard_run_total": int(summary.shadow_discard_run_total),
            "shadow_discarded_ledger_events_total": int(summary.shadow_discarded_ledger_events_total),
            "shadow_paper_orders_cleared_total": int(summary.shadow_paper_orders_cleared_total),
        })
        if self.is_closing:
            return
        self.status.setText(
            f"Qualification batch xong {summary.processed}/{summary.total} · "
            f"ghi mới {summary.inserted} · trùng {summary.duplicates} · "
            f"lỗi {summary.failures}"
        )
        if self.core_shadow_agreement_store is not None:
            self._qualification_metrics_generation += 1
            generation = self._qualification_metrics_generation
            submitted_ns = time.perf_counter_ns()
            self._qualification_metrics_submitted_ns[generation] = submitted_ns
            self._qualification_metrics_requested.emit(generation, {
                "batch_id": summary.batch_id,
                "submitted_monotonic_ns": submitted_ns,
            })

    @Slot(int, object, object)
    def _on_qualification_metrics_ready(self, generation: int, payload: object, timing: object) -> None:
        callback_started_ns = time.perf_counter_ns()
        submitted_ns = int(self._qualification_metrics_submitted_ns.pop(int(generation), callback_started_ns))
        stale = int(generation) != int(self._qualification_metrics_generation)
        render_ms = 0.0
        # Define callback telemetry for stale, closing, empty, and exception
        # paths. Previously render_counts only existed after a successful
        # render and the callback raised UnboundLocalError otherwise.
        render_counts = {"updated_widgets": 0, "unchanged_widgets": 0}
        if not stale and not self.is_closing and payload is not None:
            render_started_ns = time.perf_counter_ns()
            try:
                render_counts = self._render_shadow_qualification_dashboard(payload)
            except Exception as exc:
                logger.warning("Unable to refresh qualification dashboard: %s", exc)
            render_ms = (time.perf_counter_ns() - render_started_ns) / 1_000_000.0
        total_callback_ms = (time.perf_counter_ns() - callback_started_ns) / 1_000_000.0
        worker_timing = dict(timing or {})
        self._append_rc63_jsonl("qualification_callback_forensics.jsonl", {
            "schema_version": "dvs.runtime.qualification_callback.v2",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "runtime_session_id": self._runtime_session_id,
            "event": "qualification_metrics_ready",
            "generation": int(generation),
            "stale": bool(stale),
            "queue_wait_plus_worker_ms": round((callback_started_ns - submitted_ns) / 1_000_000.0, 3),
            "worker_execution_ms": worker_timing.get("execution_ms"),
            "gui_render_ms": round(render_ms, 3),
            "gui_callback_execution_ms": round(total_callback_ms, 3),
            "worker_thread_name": worker_timing.get("thread_name"),
            "error": worker_timing.get("error"),
            "updated_widgets": int(render_counts.get("updated_widgets", 0)),
            "unchanged_widgets": int(render_counts.get("unchanged_widgets", 0)),
            "delta_render": True,
            "analytics_fetched_on_worker": True,
        })

    @Slot(str, str)
    def _on_qualification_batch_failed(self, batch_id: str, message: str) -> None:
        logger.error("Qualification batch %s failed: %s", batch_id, message)
        if not self.is_closing:
            self.status.setText(
                f"Qualification batch lỗi; Legacy/Paper không bị ảnh hưởng: {message[:80]}"
            )

    @Slot(str, str)
    def _on_qualification_batch_rejected(self, batch_id: str, reason: str) -> None:
        logger.warning("Qualification batch %s rejected: %s", batch_id, reason)
        if not self.is_closing:
            self.status.setText(
                f"Qualification batch bỏ qua ({reason}); scan/Paper vẫn tiếp tục"
            )

    def _rc647b_prune_completed_identity_keys(self, now: float | None = None) -> int:
        """Bound duplicate-suppression state without racing the watchdog.

        Completion is inserted before capture-submission authority is removed.
        Expiry only affects already-completed keys and never keys still present
        in the active submission set.
        """
        current = time.monotonic() if now is None else float(now)
        removed = 0
        order = self._rc647_identity_completed_order
        completed = self._rc647_identity_completed_keys
        submitted = self._rc647_capture_submitted_keys
        while order:
            completed_at, key = order[0]
            expired = current - float(completed_at) >= self._rc647_identity_completed_ttl_seconds
            over_limit = len(completed) > self._rc647_identity_completed_max_entries
            if not expired and not over_limit:
                break
            order.popleft()
            if key in submitted:
                # Active authority wins; postpone deletion until a later pass.
                order.append((current, key))
                break
            if key in completed:
                completed.discard(key)
                removed += 1
        return removed

    def _rc647b_complete_identity_state(self, capture_key, analysis=None) -> None:
        """Commit completion first, then release all per-key transient state."""
        now = time.monotonic()
        self._rc647_identity_completed_keys.add(capture_key)
        self._rc647_identity_completed_order.append((now, capture_key))
        # Submission authority is removed only after completion is visible.
        self._rc647_capture_submitted_keys.discard(capture_key)
        self._capture_identity_by_key.pop(capture_key, None)
        self._auto_paper_identity_warned_keys.discard(capture_key)
        self._capture_latency_started_by_key.pop(capture_key, None)
        self._rc647_identity_deferred_seen.discard(capture_key)
        analysis_id = self._analysis_id_by_capture_key.pop(capture_key, None)
        if analysis_id is not None:
            self._capture_key_by_analysis_id.pop(analysis_id, None)
        # Defensive cleanup when a live analysis object is still available.
        if analysis is not None:
            self._capture_key_by_analysis_id.pop(id(analysis), None)
        self._rc647b_prune_completed_identity_keys(now)

    def _record_auto_paper_hang_probe(self, stage: str, **details) -> None:
        self._append_rc63_jsonl("auto_paper_hang_probe.jsonl", {
            "schema_version":"dvs.runtime.auto_paper_hang_probe.v1",
            "timestamp_utc":datetime.utcnow().isoformat(timespec="milliseconds")+"Z",
            "monotonic_ns":time.monotonic_ns(),
            "runtime_session_id":self._runtime_session_id,
            "pid":os.getpid(),
            "thread_id":threading.get_ident(),
            "stage":str(stage),
            "cycle_index":int(getattr(self, "_scan_cycle_count", 0)),
            "scan_id":str(getattr(self, "current_scan_id", "")),
            **details,
        })

    @_audit_gui_callback("auto_paper_batch")
    def _process_auto_paper_batch(self):
        """Dispatch at most one ready item to the persistent worker.

        GUI work is limited to identity bookkeeping and queue scheduling.  The
        expensive PaperTradeService.auto_consider call never runs on the GUI
        thread in RC6.4.7C.
        """
        if self.is_closing or self._auto_paper_inflight or not self._auto_paper_queue:
            return
        turn_started = time.monotonic()
        inspected = 0
        deferred = []
        now = time.monotonic()
        dispatched = False
        while self._auto_paper_queue and inspected < 8:
            queue_before = len(self._auto_paper_queue)
            queue_item = self._auto_paper_queue.pop(0)
            _queue_analysis = queue_item[0] if isinstance(queue_item, tuple) and queue_item else queue_item
            self._record_auto_paper_hang_probe(
                "before_owner_release", queue_before=queue_before,
                queue_after=len(self._auto_paper_queue),
                analysis_object_id=hex(id(_queue_analysis)),
            )
            COIN_ANALYSIS_TOKENS.owner_release(
                _queue_analysis, "MainWindow._auto_paper_queue",
                cycle_index=self._scan_cycle_count,
                mutation_site="MainWindow._process_auto_paper_queue:pop",
            )
            self._record_auto_paper_hang_probe(
                "after_owner_release_before_record_mutation",
                queue_before=queue_before, queue_after=len(self._auto_paper_queue),
                analysis_object_id=hex(id(_queue_analysis)),
            )
            mutation_started_ns = time.monotonic_ns()
            self._retention_owner_telemetry.record_mutation(
                "auto_paper_queue",
                operation="pop",
                count_before=queue_before,
                count_after=len(self._auto_paper_queue),
                item_count=1,
            )
            self._record_auto_paper_hang_probe(
                "after_record_mutation",
                mutation_duration_ms=round((time.monotonic_ns()-mutation_started_ns)/1_000_000.0, 6),
                telemetry_diagnostics=self._retention_owner_telemetry.diagnostics(),
            )
            inspected += 1
            if isinstance(queue_item, tuple) and len(queue_item) == 3:
                analysis, capture_key, first_deferred_at = queue_item
            else:
                analysis = queue_item
                capture_key = self._capture_key(analysis)
                first_deferred_at = now
            identity = self._capture_identity_by_key.get(capture_key)
            capture_was_submitted = (
                capture_key in self._rc647_capture_submitted_keys
            )
            shadow_only = not capture_was_submitted
            if shadow_only:
                identity = None
                self._record_identity_diagnostic(
                    "auto_paper_shadow_only_fallback",
                    capture_key,
                    analysis_object_id=hex(id(analysis)),
                    reason="NO_LIVE_CAPTURE_SUBMISSION",
                )
                self._append_rc63_jsonl(
                    "auto_paper_shadow_recovery.jsonl",
                    {
                        "schema_version": (
                            "dvs.runtime.auto_paper_shadow_recovery.v1"
                        ),
                        "timestamp_utc": (
                            datetime.utcnow()
                            .isoformat(timespec="milliseconds")
                            + "Z"
                        ),
                        "runtime_session_id": self._runtime_session_id,
                        "event": "shadow_only_dispatch_allowed",
                        "capture_key": str(capture_key),
                        "symbol": str(
                            getattr(analysis, "symbol", "UNKNOWN")
                        ),
                        "reason": "NO_LIVE_CAPTURE_SUBMISSION",
                    },
                )
            if (
                not shadow_only
                and self.live_episode_capture is not None
                and identity is None
                and capture_key not in self._capture_failed_keys
            ):
                elapsed = now - float(first_deferred_at)
                if capture_key not in self._rc647_identity_deferred_seen:
                    self._rc647_identity_deferred_seen.add(capture_key)
                    self._record_identity_diagnostic(
                        "identity_deferred_first_seen", capture_key,
                        elapsed_ms=round(elapsed * 1000.0, 3),
                        analysis_object_id=hex(id(analysis)),
                    )
                if elapsed >= self._auto_paper_identity_warning_seconds and capture_key not in self._auto_paper_identity_warned_keys:
                    self._auto_paper_identity_warned_keys.add(capture_key)
                    self._record_identity_diagnostic(
                        "identity_warning_emitted", capture_key,
                        elapsed_ms=round(elapsed * 1000.0, 3),
                        warning_reason="DELAYED_CAPTURE_AFTER_CONFIRMED_SUBMISSION",
                        analysis_object_id=hex(id(analysis)),
                    )
                deferred.append((analysis, capture_key, first_deferred_at))
                continue
            if (
                not shadow_only
                and capture_key in self._capture_failed_keys
            ):
                logger.error(
                    "Auto Paper skipped: Unified capture unavailable for "
                    "%s key=%s",
                    analysis.symbol,
                    capture_key,
                )
                continue
            _write_auto_paper_pipeline_event(
                "dispatch_selected",
                capture_key=str(capture_key),
                symbol=str(getattr(analysis, "symbol", "UNKNOWN")),
                cycle_index=int(self._scan_cycle_count),
                shadow_only=bool(shadow_only),
                identity_present=bool(identity is not None),
                capture_was_submitted=bool(capture_was_submitted),
                queue_remaining=int(len(self._auto_paper_queue) + len(deferred)),
            )
            self._auto_paper_inflight = True
            self._record_auto_paper_hang_probe("after_worker_emit")
            dispatched = True
            self._append_rc63_jsonl("allocator_samples.jsonl", {
                "schema_version": "dvs.runtime.auto_paper_dispatch.v2",
                "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
                "runtime_session_id": self._runtime_session_id,
                "section": "auto_paper_worker_dispatch",
                "symbol": str(getattr(analysis, "symbol", "UNKNOWN")),
                "queue_size_after": len(self._auto_paper_queue) + len(deferred),
                "gui_dispatch_ms": round((time.monotonic() - turn_started) * 1000.0, 3),
            })
            payload_key = str(capture_key)
            self._auto_paper_payload_dispatched_total += 1
            self._auto_paper_payload_pending[payload_key] = {
                "dispatched_monotonic": time.monotonic(),
                "analysis_object_id": hex(id(analysis)),
                "identity_object_id": None if identity is None else hex(id(identity)),
                "analysis_type": type(analysis).__name__,
                "identity_type": None if identity is None else type(identity).__name__,
                "symbol": str(getattr(analysis, "symbol", "UNKNOWN")),
                "shadow_only": bool(shadow_only),
            }
            self._record_auto_paper_hang_probe("before_worker_emit")
            if not self._queued_pipeline_enabled("auto_paper"):
                _write_auto_paper_pipeline_event(
                    "dispatch_blocked_pipeline_disabled",
                    capture_key=str(capture_key),
                    symbol=str(getattr(analysis, "symbol", "UNKNOWN")),
                    gate_scope="per_pipeline",
                    auto_paper_enabled=False,
                    enabled_states=dict(getattr(self, "_queued_signal_pipeline_enabled", {})),
                )
                self._auto_paper_inflight = False
                self._record_signal_path_event(
                    "auto_paper",
                    "pipeline_disabled_self_test_failed",
                    payload_id=str(capture_key),
                    gate_scope="per_pipeline",
                    enabled_states=dict(getattr(self, "_queued_signal_pipeline_enabled", {})),
                )
                break
            self._record_signal_path_event("auto_paper", "gui_before_emit",
                                           payload_id=str(capture_key),
                                           sender_class=type(self).__name__,
                                           receiver_class=type(self._auto_paper_worker).__name__)
            self._auto_paper_work_requested.emit(
                analysis,
                capture_key,
                identity,
                bool(shadow_only),
            )
            self._record_signal_path_event("auto_paper", "gui_after_emit",
                                           payload_id=str(capture_key))
            break
        if deferred:
            queue_before = len(self._auto_paper_queue)
            self._auto_paper_queue.extend(deferred)
            self._retention_owner_telemetry.record_mutation(
                "auto_paper_queue",
                operation="extend",
                count_before=queue_before,
                count_after=len(self._auto_paper_queue),
                item_count=len(deferred),
            )
        if not dispatched:
            if self._auto_paper_queue:
                QTimer.singleShot(100, self._process_auto_paper_batch)
            else:
                QTimer.singleShot(0, self._refresh_paper_outcomes_deferred)

    @Slot(object, bool, str, float)
    def _on_auto_paper_worker_completed(self, capture_key, ok, message, duration_ms):
        if str(capture_key).startswith("__queued_signal_probe__:"):
            token=str(capture_key).split(":",1)[1]
            self._record_signal_path_event("auto_paper", "worker_result_received", token=token,
                                           ok=bool(ok), message=str(message),
                                           worker_duration_ms=round(float(duration_ms),3))
            self._mark_queued_signal_probe_received("auto_paper", token,
                                                    payload_id=str(capture_key))
            return
        _write_auto_paper_pipeline_event(
            "gui_result_received",
            capture_key=str(capture_key),
            ok=bool(ok),
            message=" ".join(str(message).split())[:300],
            worker_duration_ms=round(float(duration_ms), 3),
        )
        self._record_signal_path_event("auto_paper", "gui_result_slot_entered",
                                       payload_id=str(capture_key), ok=bool(ok))
        self._auto_paper_inflight = False
        payload_state = self._auto_paper_payload_pending.pop(str(capture_key), None)
        symbol = str((payload_state or {}).get("symbol", "UNKNOWN"))
        identity_was_present = bool(
            (payload_state or {}).get("identity_object_id")
        )
        shadow_only = bool(
            (payload_state or {}).get("shadow_only", False)
        )
        self._record_identity_diagnostic(
            "identity_consumed", capture_key,
            identity_was_present=identity_was_present,
            analysis_object_id=(payload_state or {}).get("analysis_object_id"),
            worker_duration_ms=round(float(duration_ms), 3),
        )
        self._rc647b_complete_identity_state(capture_key)
        self._auto_paper_payload_released_total += 1
        payload_age_ms = None
        if payload_state is not None:
            payload_age_ms = round((time.monotonic() - float(payload_state["dispatched_monotonic"])) * 1000.0, 3)
        if ok:
            self.status.setText(str(message))
        normalized_reason = " ".join(str(message).split())[:240]
        self._append_rc63_jsonl("allocator_samples.jsonl", {
            "schema_version": "dvs.runtime.auto_paper_worker.v3",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "runtime_session_id": self._runtime_session_id,
            "section": "auto_paper_worker_completed",
            "symbol": symbol,
            "shadow_only": bool(shadow_only),
            "ok": bool(ok),
            "message": normalized_reason,
            "reason": normalized_reason, "worker_duration_ms": round(float(duration_ms), 3),
            "payload_age_ms": payload_age_ms,
            "payload_pending_count": len(self._auto_paper_payload_pending),
            "payload_dispatched_total": self._auto_paper_payload_dispatched_total,
            "payload_released_total": self._auto_paper_payload_released_total,
            "auto_paper_worker_object_id": self._auto_paper_worker_object_id,
            "queue_size_after": len(self._auto_paper_queue),
        })
        QTimer.singleShot(25, self._process_auto_paper_batch)

    @Slot(object, str, str, float)
    def _on_auto_paper_worker_failed(self, capture_key, error_type, error_message, duration_ms):
        if str(capture_key).startswith("__queued_signal_probe__:"):
            token=str(capture_key).split(":",1)[1]
            self._record_signal_path_event("auto_paper", "worker_result_failed", token=token,
                                           error_type=str(error_type), error_message=str(error_message))
            return
        self._record_signal_path_event("auto_paper", "gui_result_slot_entered",
                                       payload_id=str(capture_key), ok=False,
                                       error_type=str(error_type))
        self._auto_paper_inflight = False
        payload_state = self._auto_paper_payload_pending.pop(str(capture_key), None)
        symbol = str((payload_state or {}).get("symbol", "UNKNOWN"))
        try:
            self.recorder.record_error(
                symbol=symbol, direction="UNKNOWN", error_type=str(error_type),
                error_message=str(error_message),
                stack_trace="AutoPaperWorker failure (worker traceback unavailable)",
                context={"source_method": "auto_paper_worker", "worker_duration_ms": duration_ms},
                source="AUTO_PAPER_WORKER",
            )
        except Exception:
            logger.exception("Unable to persist Auto Paper worker failure")
        self._record_identity_diagnostic(
            "identity_consumed", capture_key,
            identity_was_present=bool((payload_state or {}).get("identity_object_id")),
            analysis_object_id=(payload_state or {}).get("analysis_object_id"),
            worker_failed=True, worker_duration_ms=round(float(duration_ms), 3),
        )
        self._rc647b_complete_identity_state(capture_key)
        self._auto_paper_payload_released_total += 1
        self._append_rc63_jsonl("allocator_samples.jsonl", {
            "schema_version": "dvs.runtime.auto_paper_worker.v3",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "runtime_session_id": self._runtime_session_id,
            "section": "auto_paper_worker_failed", "symbol": symbol,
            "error_type": str(error_type), "message": " ".join(str(error_message).split())[:240],
            "worker_duration_ms": round(float(duration_ms), 3),
            "payload_pending_count": len(self._auto_paper_payload_pending),
            "payload_dispatched_total": self._auto_paper_payload_dispatched_total,
            "payload_released_total": self._auto_paper_payload_released_total,
            "auto_paper_worker_object_id": self._auto_paper_worker_object_id,
        })
        self.status.setText(f"Auto Paper lỗi {symbol}: {error_type}: {str(error_message)[:120]}")
        QTimer.singleShot(25, self._process_auto_paper_batch)

    @Slot(object)
    @_audit_gui_callback("outcome_resolution_completed")
    def _on_outcome_resolution_completed(self, summary) -> None:
        if self.is_closing:
            return
        self.status.setText(
            f"Outcome/Paper: kiểm tra {summary.checked}, "
            f"cập nhật {summary.updated}, lỗi {summary.errors}."
        )
        # Render only after the worker has committed database changes.
        # Coalesce with any scan-finalization refreshes already queued.
        self._schedule_coalesced_gui_refresh("refresh_paper_trade_tab", "outcome_resolution_completed")
        self._schedule_coalesced_gui_refresh("refresh_learning_center", "outcome_resolution_completed")

    @Slot(str, str)
    def _on_outcome_resolution_failed(self, run_id: str, message: str) -> None:
        logger.error("Outcome resolution failed run_id=%s: %s", run_id, message)
        if not self.is_closing:
            self.status.setText(f"Outcome/Paper lỗi: {message[:90]}")

    @_audit_gui_callback("paper_outcomes_deferred")
    def _refresh_paper_outcomes_deferred(self):
        if self.is_closing:
            return
        # Coalesced persistent worker; this call is O(1) on the GUI thread.
        self.outcome_resolution_coordinator.request_resolution()

    def _schedule_coalesced_gui_refresh(self, refresh_name: str, reason: str) -> None:
        """Queue one named refresh without allowing duplicate bursts.

        The actual widget refresh remains on the GUI thread, but only one
        refresh is executed per event-loop turn. Duplicate requests are
        collapsed until the queued refresh has run.
        """
        if self.is_closing:
            return
        name = str(refresh_name)
        if name in self._gui_refresh_pending:
            if name == "refresh_learning_center":
                try:
                    from dvs_ai.runtime.learning_dispatch_forensics import record_learning_dispatch
                    record_learning_dispatch(
                        "coalesced_request_collapsed",
                        window=self,
                        source="coalesced_gui_refresh_scheduler",
                        reason=str(reason),
                        refresh_name=name,
                    )
                except Exception:
                    pass
            self._append_rc63_jsonl("gui_refresh_dispatch.jsonl", {
                "schema_version": "dvs.runtime.gui_refresh_dispatch.v1",
                "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
                "runtime_session_id": self._runtime_session_id,
                "pid": os.getpid(),
                "event": "refresh_coalesced",
                "refresh_name": name,
                "reason": str(reason),
                "queue_size": len(self._gui_refresh_queue),
            })
            return
        self._gui_refresh_pending.add(name)
        self._gui_refresh_queue.append((name, str(reason)))
        if name == "refresh_learning_center":
            try:
                from dvs_ai.runtime.learning_dispatch_forensics import record_learning_dispatch
                record_learning_dispatch(
                    "coalesced_request_queued",
                    window=self,
                    source="coalesced_gui_refresh_scheduler",
                    reason=str(reason),
                    refresh_name=name,
                )
            except Exception:
                pass
        self._append_rc63_jsonl("gui_refresh_dispatch.jsonl", {
            "schema_version": "dvs.runtime.gui_refresh_dispatch.v1",
            "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "runtime_session_id": self._runtime_session_id,
            "pid": os.getpid(),
            "event": "refresh_queued",
            "refresh_name": name,
            "reason": str(reason),
            "queue_size": len(self._gui_refresh_queue),
        })
        if not self._gui_refresh_running and not self.gui_refresh_dispatch_timer.isActive():
            self.gui_refresh_dispatch_timer.start()

    def _schedule_standard_post_commit_refreshes(self, reason: str) -> None:
        for refresh_name in (
            "refresh_summary",
            "refresh_microstructure_tab",
            "refresh_history",
            "refresh_paper_trade_tab",
            "refresh_learning_center",
        ):
            self._schedule_coalesced_gui_refresh(refresh_name, reason)

    def _drain_coalesced_gui_refresh(self) -> None:
        if self.is_closing or self._gui_refresh_running:
            return
        if not self._gui_refresh_queue:
            return
        self._gui_refresh_running = True
        refresh_name, reason = self._gui_refresh_queue.popleft()
        self._gui_refresh_pending.discard(refresh_name)
        self._gui_refresh_tick_index += 1
        started = time.perf_counter()
        outcome = "done"
        failure_type = None
        try:
            refresh_fn = getattr(self, refresh_name, None)
            if callable(refresh_fn):
                if refresh_name == "refresh_learning_center":
                    self._learning_dispatch_context = {
                        "source": "coalesced_gui_refresh",
                        "reason": str(reason),
                        "refresh_name": str(refresh_name),
                    }
                    try:
                        from dvs_ai.runtime.learning_dispatch_forensics import record_learning_dispatch
                        record_learning_dispatch(
                            "coalesced_dispatch_enter",
                            window=self,
                            source="coalesced_gui_refresh",
                            reason=str(reason),
                            refresh_name=str(refresh_name),
                        )
                    except Exception:
                        pass
                try:
                    refresh_fn()
                finally:
                    if refresh_name == "refresh_learning_center":
                        try:
                            from dvs_ai.runtime.learning_dispatch_forensics import record_learning_dispatch
                            record_learning_dispatch(
                                "coalesced_dispatch_exit",
                                window=self,
                                source="coalesced_gui_refresh",
                                reason=str(reason),
                                refresh_name=str(refresh_name),
                            )
                        except Exception:
                            pass
                        self._learning_dispatch_context = {}
            else:
                outcome = "missing"
        except Exception as exc:
            outcome = "failed"
            failure_type = type(exc).__name__
            logger.exception("GUI_REFRESH_DISPATCH_FAILED name=%s", refresh_name)
        finally:
            measurement_ms = (time.perf_counter() - started) * 1000.0
            self._append_rc63_jsonl("gui_refresh_dispatch.jsonl", {
                "schema_version": "dvs.runtime.gui_refresh_dispatch.v1",
                "timestamp_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
                "runtime_session_id": self._runtime_session_id,
                "pid": os.getpid(),
                "event": "refresh_executed",
                "tick_index": self._gui_refresh_tick_index,
                "refresh_name": refresh_name,
                "reason": reason,
                "outcome": outcome,
                "failure_type": failure_type,
                "measurement_ms": round(measurement_ms, 3),
                "budget_ms": self._gui_refresh_budget_ms,
                "budget_exceeded": measurement_ms > self._gui_refresh_budget_ms,
                "queue_size_after": len(self._gui_refresh_queue),
            })
            self._gui_refresh_running = False
        if self._gui_refresh_queue and not self.is_closing:
            self.gui_refresh_dispatch_timer.start()

    @Slot(str)
    def _on_finalization_error(self, stack_trace):
        logger.error("ASYNC_FINALIZATION_ERROR\n%s", stack_trace)
        self.status.setText("Finalization lỗi; giữ kết quả quét thô.")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.retry_btn.setEnabled(bool(self.failed))
        self.refresh_summary()

    def _cleanup_finalization_worker(self):
        # S4.1.2-r1 (corrected): thread.deleteLater() is already scheduled
        # via thread.finished -> thread.deleteLater() at launch time. Do not
        # call deleteLater() a second time here; only clear Python refs.
        self.finalization_worker = None
        self.finalization_thread = None

    def _rebuild_row_index(self):
        self._row_by_symbol.clear()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            symbol = item.data(Qt.ItemDataRole.UserRole)
            if symbol:
                self._row_by_symbol[str(symbol)] = row

    def table_diff_diagnostics(self) -> dict:
        """Return a copy of cell-diff counters for diagnostics/overlay use."""
        return dict(self._table_diff_metrics)

    @staticmethod
    def _item_display_value(item):
        return item.data(Qt.ItemDataRole.DisplayRole)

    def _ensure_table_item(self, row: int, col: int):
        item = self.table.item(row, col)
        if item is None:
            item = QTableWidgetItem()
            self.table.setItem(row, col, item)
            self._table_diff_metrics["items_created"] += 1
        return item

    def _set_cell_display(self, item, value) -> bool:
        self._table_diff_metrics["cells_checked"] += 1
        if self._item_display_value(item) == value:
            return False
        item.setData(Qt.ItemDataRole.DisplayRole, value)
        self._table_diff_metrics["cells_changed"] += 1
        return True

    def _set_cell_alignment(self, item, alignment) -> bool:
        if item.textAlignment() == int(alignment):
            return False
        item.setTextAlignment(alignment)
        self._table_diff_metrics["style_changes"] += 1
        return True

    def _set_cell_background(self, item, color: QColor) -> bool:
        if item.background().color() == color:
            return False
        item.setBackground(color)
        self._table_diff_metrics["style_changes"] += 1
        return True

    def _set_cell_foreground(self, item, color: QColor) -> bool:
        if item.foreground().color() == color:
            return False
        item.setForeground(color)
        self._table_diff_metrics["style_changes"] += 1
        return True

    def _set_cell_bold(self, item, bold: bool) -> bool:
        font = item.font()
        if font.bold() == bool(bold):
            return False
        font.setBold(bool(bold))
        item.setFont(font)
        self._table_diff_metrics["style_changes"] += 1
        return True

    @staticmethod
    def _display_values_equivalent(actual, expected) -> bool:
        if actual == expected:
            return True
        try:
            if actual is None or expected is None:
                return False
            return math.isclose(float(str(actual)), float(str(expected)), rel_tol=1e-12, abs_tol=1e-12)
        except (TypeError, ValueError):
            return False

    def _audit_display_integrity(self, commit_id: int, sample_size: int = 5) -> dict:
        """Audit a deterministic sample of visible rows for stale display.

        The check is read-only and intentionally bounded. It validates both
        the row index/cache and the exact text projection currently displayed.
        """
        symbols = sorted(
            symbol for symbol in self.results
            if symbol != "BTC/USDT:USDT"
        )
        if not symbols:
            report = {"commit_id": commit_id, "checked": 0, "failures": []}
            logger.info("DISPLAY_INTEGRITY_OK %s", json.dumps(report, sort_keys=True))
            return report
        if len(symbols) <= sample_size:
            sampled = symbols
        else:
            indexes = {0, len(symbols) - 1}
            for offset in range(1, sample_size - 1):
                indexes.add(round(offset * (len(symbols) - 1) / (sample_size - 1)))
            sampled = [symbols[index] for index in sorted(indexes)]
        failures = []
        for symbol in sampled:
            analysis = self.results.get(symbol)
            row = self._row_by_symbol.get(symbol, -1)
            expected = self._analysis_table_fingerprint(analysis) if analysis is not None else None
            cached = self._table_fingerprint_by_symbol.get(symbol)
            if analysis is None or row < 0 or row >= self.table.rowCount():
                failures.append({"symbol": symbol, "reason": "missing_row_or_analysis"})
                continue
            actual_values = []
            for column in range(17):
                item = self.table.item(row, column)
                actual_values.append(None if item is None else item.text())
            expected_values = [
                symbol.replace(":USDT", ""), expected[1], *expected[2:17]
            ]
            normalized_expected = [str(value) for value in expected_values]
            projection_equal = all(
                self._display_values_equivalent(actual, expected)
                for actual, expected in zip(actual_values, normalized_expected)
            )
            if not projection_equal:
                header = self.table.horizontalHeader()
                sort_column = int(header.sortIndicatorSection())
                sort_order = int(header.sortIndicatorOrder().value)
                failures.append({
                    "symbol": symbol,
                    "reason": "visible_projection_mismatch",
                    "row_at_check": row,
                    "sort_column_at_check": sort_column,
                    "sort_order_at_check": sort_order,
                    "sorting_enabled_at_check": bool(self.table.isSortingEnabled()),
                    "actual_values": actual_values,
                    "expected_values": normalized_expected,
                    "cached_fingerprint": list(cached) if isinstance(cached, tuple) else cached,
                    "analysis_object_id": hex(id(analysis)),
                })
            if cached != expected:
                failures.append({"symbol": symbol, "reason": "fingerprint_cache_mismatch"})
        report = {
            "session_id": self._runtime_session_id,
            "commit_id": commit_id,
            "checked": len(sampled),
            "failures": failures,
            "table_rows": self.table.rowCount(),
            "fingerprint_cache_size": len(self._table_fingerprint_by_symbol),
            "row_cache_size": len(self._row_by_symbol),
        }
        event = "DISPLAY_INTEGRITY_FAILED" if failures else "DISPLAY_INTEGRITY_OK"
        log = logger.error if failures else logger.info
        log(event + " %s", json.dumps(report, sort_keys=True, ensure_ascii=False))
        return report

    @staticmethod
    def _analysis_table_fingerprint(a) -> tuple:
        """Return the exact visible table projection for delta commits."""
        r15 = a.timeframes["15m"]
        snapshot = a.snapshot
        return (
            a.symbol,
            round(float(a.confidence_score), 1),
            f"{snapshot.last_price:.8g}",
            f"{snapshot.change_24h_pct:+.2f}",
            f"{snapshot.oi_change_15m_pct:+.2f}",
            f"{snapshot.oi_change_1h_pct:+.2f}",
            f"{snapshot.funding_pct:+.4f}",
            f"{r15.cmf:+.3f}",
            f"{r15.rsi:.1f}",
            f"{r15.adx:.1f}",
            f"x{r15.relative_volume:.2f}",
            a.phase_summary,
            f"{a.long_trend_score:.0f}",
            f"{a.long_entry_score:.0f}",
            f"{a.short_trend_score:.0f}",
            f"{a.short_entry_score:.0f}",
            a.entry_status.value,
            a.direction,
        )

    @_audit_gui_callback("table_row_upsert", record_threshold_ms=20.0)
    def _upsert_row(self, a, manage_sorting=True):
        started = time.perf_counter()

        # RC7.10: skip all QTableWidgetItem work when the full visible/style
        # projection is unchanged and the row identity still matches.
        fingerprint = self._analysis_table_fingerprint(a)
        row = self._row_by_symbol.get(a.symbol, -1)
        if 0 <= row < self.table.rowCount():
            symbol_item = self.table.item(row, 0)
            if (
                symbol_item is not None
                and symbol_item.data(Qt.ItemDataRole.UserRole) == a.symbol
                and self._table_fingerprint_by_symbol.get(a.symbol) == fingerprint
            ):
                self._table_diff_metrics["rows_unchanged_skipped"] += 1
                self._table_diff_metrics["last_update_ms"] = round(
                    (time.perf_counter() - started) * 1000.0, 3
                )
                return

        sorting_was_enabled = (
            self.table.isSortingEnabled()
            if manage_sorting
            else False
        )
        if sorting_was_enabled:
            self.table.setSortingEnabled(False)

        if row < 0 or row >= self.table.rowCount():
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._row_by_symbol[a.symbol] = row
            self._table_diff_metrics["rows_inserted"] += 1

        r15 = a.timeframes["15m"]
        snapshot = a.snapshot
        values = [
            a.symbol.replace(":USDT", ""),
            round(float(a.confidence_score), 1),
            f"{snapshot.last_price:.8g}",
            f"{snapshot.change_24h_pct:+.2f}",
            f"{snapshot.oi_change_15m_pct:+.2f}",
            f"{snapshot.oi_change_1h_pct:+.2f}",
            f"{snapshot.funding_pct:+.4f}",
            f"{r15.cmf:+.3f}",
            f"{r15.rsi:.1f}",
            f"{r15.adx:.1f}",
            f"x{r15.relative_volume:.2f}",
            a.phase_summary,
            f"{a.long_trend_score:.0f}",
            f"{a.long_entry_score:.0f}",
            f"{a.short_trend_score:.0f}",
            f"{a.short_entry_score:.0f}",
            a.entry_status.value,
        ]

        for col, value in enumerate(values):
            item = self._ensure_table_item(row, col)
            self._set_cell_display(item, value)
            if col != 0:
                self._set_cell_alignment(
                    item, Qt.AlignmentFlag.AlignCenter
                )

        symbol_item = self.table.item(row, 0)
        if symbol_item.data(Qt.ItemDataRole.UserRole) != a.symbol:
            symbol_item.setData(Qt.ItemDataRole.UserRole, a.symbol)
            self._table_diff_metrics["style_changes"] += 1

        # Base palette first; semantic highlights are applied afterwards.
        self._apply_row_palette(row, a)

        status_item = self.table.item(row, 16)
        status_colors = {
            EntryStatus.READY: ("#14532d", "#dcfce7"),
            EntryStatus.SETUP: ("#713f12", "#fef3c7"),
            EntryStatus.RUNNING: ("#1e3a8a", "#dbeafe"),
        }
        if a.entry_status in status_colors:
            background, foreground = status_colors[a.entry_status]
            self._set_cell_background(status_item, QColor(background))
            self._set_cell_foreground(status_item, QColor(foreground))

        if a.direction == "LONG":
            for column in (12, 13):
                self._set_cell_foreground(
                    self.table.item(row, column),
                    QColor("#4ade80"),
                )
        else:
            for column in (14, 15):
                self._set_cell_foreground(
                    self.table.item(row, column),
                    QColor("#f87171"),
                )

        self._table_fingerprint_by_symbol[a.symbol] = fingerprint

        cell_elapsed_ms = (time.perf_counter() - started) * 1000.0
        self._table_diff_metrics["last_update_ms"] = round(cell_elapsed_ms, 3)
        if hasattr(self, "ui_profiler"):
            self.ui_profiler.record("table_cell_diff", cell_elapsed_ms)

        if sorting_was_enabled:
            sort_started = time.perf_counter()
            self.table.setSortingEnabled(True)
            self.table.sortItems(1, Qt.SortOrder.DescendingOrder)
            if hasattr(self, "ui_profiler"):
                self.ui_profiler.record(
                    "table_sort",
                    (time.perf_counter() - sort_started) * 1000.0,
                )
            index_started = time.perf_counter()
            self._rebuild_row_index()
            if hasattr(self, "ui_profiler"):
                self.ui_profiler.record(
                    "row_index_rebuild",
                    (time.perf_counter() - index_started) * 1000.0,
                )


    @staticmethod
    def _semantic_background(
        value: float,
        *,
        positive: str = "#0b2b22",
        negative: str = "#35151a",
        neutral: str = "#111c2e",
        deadband: float = 0.0,
    ) -> QColor:
        if value > deadband:
            return QColor(positive)
        if value < -deadband:
            return QColor(negative)
        return QColor(neutral)

    @staticmethod
    def _phase_palette(phase: str) -> tuple[QColor, QColor]:
        normalized = str(phase or "").upper()
        if "MARKUP" in normalized or "ACCUMULATION" in normalized:
            return QColor("#0b2b22"), QColor("#86efac")
        if "MARKDOWN" in normalized or "DISTRIBUTION" in normalized:
            return QColor("#35151a"), QColor("#fca5a5")
        if "SPRING" in normalized:
            return QColor("#102a43"), QColor("#7dd3fc")
        if "UPTHRUST" in normalized:
            return QColor("#3b1d35"), QColor("#f0abfc")
        if "OVERHEAT" in normalized:
            return QColor("#3a270b"), QColor("#fcd34d")
        return QColor("#172033"), QColor("#cbd5e1")

    def _apply_semantic_cell_palette(self, row, analysis) -> None:
        snapshot = analysis.snapshot
        r15 = analysis.timeframes["15m"]

        semantic = {
            3: (
                float(snapshot.change_24h_pct),
                0.05,
            ),
            4: (
                float(snapshot.oi_change_15m_pct),
                0.02,
            ),
            5: (
                float(snapshot.oi_change_1h_pct),
                0.02,
            ),
            6: (
                float(snapshot.funding_pct),
                0.0001,
            ),
            7: (
                float(r15.cmf),
                0.015,
            ),
        }
        for column, (value, deadband) in semantic.items():
            item = self.table.item(row, column)
            if item is None:
                continue
            background = self._semantic_background(
                value,
                deadband=deadband,
            )
            foreground = (
                QColor("#86efac")
                if value > deadband
                else QColor("#fca5a5")
                if value < -deadband
                else QColor("#cbd5e1")
            )
            self._set_cell_background(item, background)
            self._set_cell_foreground(item, foreground)

        rsi_item = self.table.item(row, 8)
        if rsi_item is not None:
            rsi = float(r15.rsi)
            if rsi >= 70:
                bg, fg = QColor("#3a1616"), QColor("#fca5a5")
            elif rsi <= 30:
                bg, fg = QColor("#102a43"), QColor("#7dd3fc")
            else:
                bg, fg = QColor("#172033"), QColor("#e2e8f0")
            self._set_cell_background(rsi_item, bg)
            self._set_cell_foreground(rsi_item, fg)

        adx_item = self.table.item(row, 9)
        if adx_item is not None:
            adx = float(r15.adx)
            if adx >= 30:
                bg, fg = QColor("#1f2d12"), QColor("#bef264")
            elif adx >= 20:
                bg, fg = QColor("#30250e"), QColor("#fcd34d")
            else:
                bg, fg = QColor("#172033"), QColor("#94a3b8")
            self._set_cell_background(adx_item, bg)
            self._set_cell_foreground(adx_item, fg)

        volume_item = self.table.item(row, 10)
        if volume_item is not None:
            relative_volume = float(r15.relative_volume)
            if relative_volume >= 1.5:
                bg, fg = QColor("#2e1a47"), QColor("#d8b4fe")
            elif relative_volume >= 1.0:
                bg, fg = QColor("#142b3b"), QColor("#7dd3fc")
            else:
                bg, fg = QColor("#172033"), QColor("#94a3b8")
            self._set_cell_background(volume_item, bg)
            self._set_cell_foreground(volume_item, fg)

        phase_item = self.table.item(row, 11)
        if phase_item is not None:
            bg, fg = self._phase_palette(analysis.phase_summary)
            self._set_cell_background(phase_item, bg)
            self._set_cell_foreground(phase_item, fg)
            self._set_cell_bold(phase_item, True)
            phase_text = str(analysis.phase_summary or "UNKNOWN")
            if phase_item.toolTip() != phase_text:
                phase_item.setToolTip(phase_text)

        score_columns = {
            12: (float(analysis.long_trend_score), True),
            13: (float(analysis.long_entry_score), True),
            14: (float(analysis.short_trend_score), False),
            15: (float(analysis.short_entry_score), False),
        }
        for column, (score, is_long) in score_columns.items():
            item = self.table.item(row, column)
            if item is None:
                continue
            if score >= 70:
                bg = QColor("#0b2b22") if is_long else QColor("#35151a")
                fg = QColor("#4ade80") if is_long else QColor("#f87171")
            elif score >= 50:
                bg, fg = QColor("#30250e"), QColor("#fcd34d")
            else:
                bg, fg = QColor("#172033"), QColor("#94a3b8")
            self._set_cell_background(item, bg)
            self._set_cell_foreground(item, fg)
            self._set_cell_bold(item, score >= 50)

    @_audit_gui_callback("table_row_palette", record_threshold_ms=20.0)
    def _apply_row_palette(self, row, analysis):
        if analysis.entry_status == EntryStatus.READY:
            base = (
                QColor("#10281f")
                if analysis.direction == "LONG"
                else QColor("#32161a")
            )
        elif analysis.entry_status == EntryStatus.SETUP:
            base = QColor("#2b2414")
        elif analysis.entry_status == EntryStatus.RUNNING:
            base = QColor("#12213d")
        else:
            base = QColor("#0f172a") if row % 2 == 0 else QColor("#111c2e")

        protected_colors = {1, 11, 12, 13, 14, 15, 16}

        # RC7.10: columns 3..15 are immediately owned by
        # _apply_semantic_cell_palette(). Do not write a temporary base
        # background/foreground that is overwritten in the same callback.
        semantic_owned_columns = set(range(3, 16))
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item is None:
                continue

            if col not in semantic_owned_columns:
                self._set_cell_background(item, base)
            else:
                self._table_diff_metrics["palette_base_writes_avoided"] += 1

            if col not in protected_colors and col not in semantic_owned_columns:
                self._set_cell_foreground(item, QColor("#e5e7eb"))

        # Confidence luôn nằm ở cột thứ hai và có heat color nổi bật.
        conf = float(analysis.confidence_score)
        conf_item = self.table.item(row, 1)
        if conf_item is not None:
            self._set_cell_bold(conf_item, True)

            if conf >= 85:
                self._set_cell_foreground(conf_item, QColor("#4ade80"))
            elif conf >= 70:
                self._set_cell_foreground(conf_item, QColor("#a3e635"))
            elif conf >= 50:
                self._set_cell_foreground(conf_item, QColor("#facc15"))
            elif conf >= 35:
                self._set_cell_foreground(conf_item, QColor("#fb923c"))
            else:
                self._set_cell_foreground(conf_item, QColor("#94a3b8"))

        coin_item = self.table.item(row, 0)
        if coin_item is not None:
            self._set_cell_bold(coin_item, True)
            self._set_cell_foreground(coin_item, QColor("#f8fafc"))

        self._apply_semantic_cell_palette(row, analysis)

    @_audit_gui_callback("error_table_render")
    def _refresh_error_table(self):
        self.error_table.setUpdatesEnabled(False)
        self.error_table.blockSignals(True)
        try:
            self.error_table.setRowCount(0)
            for symbol,message in self.failed.items():
                row = self.error_table.rowCount()
                self.error_table.insertRow(row)
                self.error_table.setItem(
                    row, 0,
                    QTableWidgetItem(symbol.replace(":USDT", "")),
                )
                self.error_table.setItem(
                    row, 1,
                    QTableWidgetItem(message),
                )
                self.error_table.setItem(
                    row, 2,
                    QTableWidgetItem("Chờ quét lại"),
                )
        finally:
            self.error_table.blockSignals(False)
            self.error_table.setUpdatesEnabled(True)
            self.paint_scheduler.request(self.error_table.viewport(), priority=15)

        self.error_card.set_data(
            str(len(self.failed)),
            "Coin chưa lấy đủ dữ liệu",
        )

        btc = self.results.get("BTC/USDT:USDT")
        if btc:
            b15 = btc.timeframes["15m"]
            b1 = btc.timeframes["1h"]
            self.btc_pulse.set_data(
                f"{btc.direction} {btc.confidence_score:.0f}",
                f"15m {b15.market_phase} | 1h {b1.market_phase}"
            )
            flow_text = "VÀO" if b15.cmf > 0 and b1.cmf > 0 else ("RÚT" if b15.cmf < 0 and b1.cmf < 0 else "MÂU THUẪN")
            self.flow_pulse.set_data(
                flow_text,
                f"CMF 15m {b15.cmf:+.3f} | 1h {b1.cmf:+.3f}"
            )
            momentum = "MẠNH" if b15.adx >= 25 else ("VỪA" if b15.adx >= 18 else "YẾU")
            self.momentum_pulse.set_data(
                momentum,
                f"RSI {b15.rsi:.1f} | ADX {b15.adx:.1f} | Vol x{b15.relative_volume:.2f}"
            )
            self.oi_pulse.set_data(
                btc.oi_state,
                f"OI15m {btc.snapshot.oi_change_15m_pct:+.2f}% | "
                f"OI1h {btc.snapshot.oi_change_1h_pct:+.2f}% | "
                f"Funding {btc.snapshot.funding_pct:+.4f}%"
            )
        self.retry_btn.setEnabled(bool(self.failed) and not (self.thread and self.thread.isRunning()))

    def export_csv(self):
        if not self.results:
            QMessageBox.warning(self,"Chưa có dữ liệu","Hãy quét trước khi xuất CSV."); return
        default=f"dvs_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path,_=QFileDialog.getSaveFileName(self,"Xuất kết quả",default,"CSV (*.csv)")
        if not path: return
        fields=["symbol","price","change24h","oi15m","oi1h","funding",
                "cmf15m","rsi15m","adx15m","vol15m",
                "cmf1h","rsi1h","adx1h","vol1h",
                "phase","long_trend","long_entry","short_trend","short_entry",
                "confidence","direction","entry_status",
                "maturity_score","maturity_lifecycle","maturity_gate",
                "direction_confirmation_score","direction_confirmation_gate",
                "confidence_before_context","confidence_context_adjustment",
                "opportunity_score","opportunity_rank","opportunity_gate",
                "microstructure_gate","micro_cos","micro_bias",
                "micro_ofi","micro_absorption","micro_book_imbalance",
                "market_bias_code","market_bias_gate",
                "smart_money_probability","risk_score",
                "support","resistance"]
        with open(path,"w",newline="",encoding="utf-8-sig") as f:
            writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader()
            for a in self.results.values():
                if a.symbol=="BTC/USDT:USDT": continue
                r15=a.timeframes["15m"]; r1=a.timeframes["1h"]; s=a.snapshot
                writer.writerow(dict(
                    symbol=a.symbol,price=s.last_price,change24h=s.change_24h_pct,
                    oi15m=s.oi_change_15m_pct,oi1h=s.oi_change_1h_pct,funding=s.funding_pct,
                    cmf15m=r15.cmf,rsi15m=r15.rsi,adx15m=r15.adx,vol15m=r15.relative_volume,
                    cmf1h=r1.cmf,rsi1h=r1.rsi,adx1h=r1.adx,vol1h=r1.relative_volume,
                    phase=a.phase_summary,long_trend=a.long_trend_score,long_entry=a.long_entry_score,
                    short_trend=a.short_trend_score,short_entry=a.short_entry_score,
                    confidence=a.confidence_score,direction=a.direction,
                    entry_status=a.entry_status.value,
                    maturity_score=a.trend_maturity_score,
                    maturity_lifecycle=a.trend_lifecycle,
                    maturity_gate=a.maturity_gate,
                    direction_confirmation_score=a.direction_confirmation_score,
                    direction_confirmation_gate=a.direction_confirmation_gate,
                    confidence_before_context=a.confidence_before_context,
                    confidence_context_adjustment=a.confidence_context_adjustment,
                    opportunity_score=a.opportunity_score,
                    opportunity_rank=a.opportunity_rank,
                    opportunity_gate=a.opportunity_gate,
                    microstructure_gate=a.microstructure_gate,
                    micro_cos=(a.microstructure.composite_operator_score if a.microstructure else 0.0),
                    micro_bias=(a.microstructure.operator_bias if a.microstructure else "N/A"),
                    micro_ofi=(a.microstructure.ofi_score if a.microstructure else 0.0),
                    micro_absorption=(a.microstructure.absorption_score if a.microstructure else 0.0),
                    micro_book_imbalance=(a.microstructure.book_imbalance if a.microstructure else 0.0),
                    market_bias_code=a.market_bias_code,
                    market_bias_gate=a.market_bias_gate,
                    smart_money_probability=a.smart_entry.smart_money_probability,
                    risk_score=a.risk.risk_score,
                    support=r15.support,resistance=r15.resistance
                ))
        QMessageBox.information(self,"Đã xuất",f"Đã lưu:\n{path}")

    def refresh_summary(self, *args, **kwargs):
        if hasattr(self, "ui_profiler"):
            with self.ui_profiler.section("refresh_summary"):
                return self._refresh_summary_impl(*args, **kwargs)
        return self._refresh_summary_impl(*args, **kwargs)

    @_audit_gui_callback("summary_render_impl")
    def _refresh_summary_impl(self):
        brief=self.service.build_market_brief(self.results)
        alts=[x for k,x in self.results.items() if k!="BTC/USDT:USDT"]
        ready = sum(x.entry_status==EntryStatus.READY for x in alts)
        setup = sum(x.entry_status==EntryStatus.SETUP for x in alts)
        long_bias = sum(x.direction=="LONG" for x in alts)
        short_bias = sum(x.direction=="SHORT" for x in alts)
        self.brief.setPlainText(
            f"{brief.summary}\n\n"
            f"Risk: {brief.risk_level}\n"
            f"Long bias: {long_bias} | Short bias: {short_bias}\n"
            f"READY: {ready} | SETUP: {setup}\n\n"
            "Khuyến nghị: chỉ hành động khi Entry đạt SETUP/READY. "
            "Không đuổi Short khi RSI 15m quá thấp và không đuổi Long khi RSI quá cao. "
            "Ưu tiên Trend không mâu thuẫn, 15m + 1h đồng pha.\n"
            "Lưu ý: chỉ hỗ trợ phân tích."
        )
        ranked_longs=sorted(alts,key=lambda x:(x.long_entry_score,x.long_trend_score,x.confidence_score),reverse=True)
        ranked_shorts=sorted(alts,key=lambda x:(x.short_entry_score,x.short_trend_score,x.confidence_score),reverse=True)
        longs=[x for x in ranked_longs if (
            x.direction=="LONG" and x.long_trend_score>=50 and
            x.long_entry_score>=55 and x.confidence_score>=50 and
            x.entry_status in (EntryStatus.SETUP,EntryStatus.READY)
        )][:self.config.top_n]
        shorts=[x for x in ranked_shorts if (
            x.direction=="SHORT" and x.short_trend_score>=50 and
            x.short_entry_score>=55 and x.confidence_score>=50 and
            x.entry_status in (EntryStatus.SETUP,EntryStatus.READY)
        )][:self.config.top_n]

        if longs:
            long_text="\n".join(
                f"{i}. {x.symbol.replace(':USDT','')} | Trend {x.long_trend_score:.0f} | "
                f"Entry {x.long_entry_score:.0f} | Conf {x.confidence_score:.0f} | {x.entry_status.value}"
                for i,x in enumerate(longs,1)
            )
        elif ranked_longs:
            x=ranked_longs[0]
            long_text=(
                "Chưa có Long đủ tiêu chuẩn.\n"
                f"Gần đạt nhất: {x.symbol.replace(':USDT','')} | "
                f"Trend {x.long_trend_score:.0f} | Entry {x.long_entry_score:.0f} | "
                f"Conf {x.confidence_score:.0f} | {x.entry_status.value}"
            )
        else:
            long_text="Chưa có dữ liệu"

        if shorts:
            short_text="\n".join(
                f"{i}. {x.symbol.replace(':USDT','')} | Trend {x.short_trend_score:.0f} | "
                f"Entry {x.short_entry_score:.0f} | Conf {x.confidence_score:.0f} | {x.entry_status.value}"
                for i,x in enumerate(shorts,1)
            )
        elif ranked_shorts:
            x=ranked_shorts[0]
            short_text=(
                "Chưa có Short đủ tiêu chuẩn.\n"
                f"Gần đạt nhất: {x.symbol.replace(':USDT','')} | "
                f"Trend {x.short_trend_score:.0f} | Entry {x.short_entry_score:.0f} | "
                f"Conf {x.confidence_score:.0f} | {x.entry_status.value}"
            )
        else:
            short_text="Chưa có dữ liệu"

        self.top_long.setPlainText(long_text)
        self.top_short.setPlainText(short_text)
        ready=sum(x.entry_status==EntryStatus.READY for x in alts)
        self.market_bias_card.set_data(brief.market_bias,f"BTC: {brief.btc_bias}")
        self.risk_card.set_data(brief.risk_level,"Đánh giá sơ bộ")
        self.breadth_card.set_data(f"{brief.alt_breadth_long_pct:.0f}%","Watchlist nghiêng Long")
        self.hot_card.set_data(str(ready),"Entry READY")
        self.error_card.set_data(str(len(self.failed)),"Coin chưa lấy đủ dữ liệu")

    def show_selected(self, *args, **kwargs):
        """Coalesced incremental selected-detail renderer."""
        if self._selection_render_active:
            self._selection_render_pending = True
            return None
        self._selection_render_active = True
        self._selection_render_started_ns = time.monotonic_ns()
        try:
            return self._show_selected_impl(*args, **kwargs)
        except Exception as exc:
            symbol = getattr(self.current_analysis, "symbol", "")
            logger.exception("Incremental selection dispatch failed for %s", symbol)
            log_gui_exception(context="show_selected_dispatch", symbol=symbol, exc=exc)
            if hasattr(self, "status"):
                self.status.setText("Lỗi hiển thị coin đã được chặn; xem logs/gui_crash.log")
            self._finish_incremental_detail_render()
            return None

    @_audit_gui_callback("selected_detail_render_dispatch")
    def _show_selected_impl(self, preserve_timeframe=False, preserve_scroll=False):
        row = self.table.currentRow()
        if row < 0:
            self._finish_incremental_detail_render(); return None
        first_item = self.table.item(row, 0)
        if first_item is None:
            self._finish_incremental_detail_render(); return None
        symbol = first_item.data(Qt.ItemDataRole.UserRole)
        if not self.results.get(symbol):
            self._finish_incremental_detail_render(); return None
        generation = int(getattr(self, "_detail_render_generation", 0) or 0) + 1
        self._detail_render_generation = generation
        self._detail_render_iterator = self._detail_render_steps(
            preserve_timeframe=preserve_timeframe,
            preserve_scroll=preserve_scroll,
        )
        self._detail_render_stage = "scheduled"
        QTimer.singleShot(0, lambda g=generation: self._advance_incremental_detail_render(g))
        return None

    def _advance_incremental_detail_render(self, generation: int) -> None:
        if generation != int(getattr(self, "_detail_render_generation", 0) or 0):
            return
        if getattr(self, "is_closing", False):
            self._finish_incremental_detail_render(); return
        iterator = getattr(self, "_detail_render_iterator", None)
        if iterator is None:
            self._finish_incremental_detail_render(); return
        try:
            self._detail_render_stage = str(next(iterator))
        except StopIteration:
            self._detail_render_stage = "complete"
            self._finish_incremental_detail_render(); return
        except Exception as exc:
            symbol = getattr(self.current_analysis, "symbol", "")
            logger.exception("Incremental detail stage failed stage=%s symbol=%s", getattr(self, "_detail_render_stage", "unknown"), symbol)
            log_gui_exception(context=f"incremental_detail:{getattr(self, '_detail_render_stage', 'unknown')}", symbol=symbol, exc=exc)
            if hasattr(self, "status"):
                self.status.setText("Lỗi hiển thị chi tiết đã được chặn; xem logs/gui_crash.log")
            self._finish_incremental_detail_render(); return
        QTimer.singleShot(0, lambda g=generation: self._advance_incremental_detail_render(g))

    def _finish_incremental_detail_render(self) -> None:
        self._selection_render_active = False
        self._detail_render_iterator = None
        if self._selection_render_pending and not getattr(self, "is_closing", False):
            self._selection_render_pending = False
            QTimer.singleShot(0, self.show_selected)

    def _detail_render_steps(
        self,
        preserve_timeframe=False,
        preserve_scroll=False,
    ):
        row = self.table.currentRow()
        if row < 0:
            return
        first_item = self.table.item(row, 0)
        if first_item is None:
            return
        symbol = first_item.data(Qt.ItemDataRole.UserRole)
        a = self.results.get(symbol)
        if not a:
            return
        gr01_callback_started_ns = time.perf_counter_ns()
        gr01_context_started_ns = time.perf_counter_ns()

        previous_symbol = (
            self.current_analysis.symbol
            if self.current_analysis is not None
            else None
        )
        selected_tf = (
            self.tf_selector.currentText()
            if preserve_timeframe and previous_symbol == symbol
            else "15m"
        )
        detail_scroll = (
            self.detail_text.verticalScrollBar().value()
            if preserve_scroll
            else 0
        )
        score_scroll = (
            self.score_explain.verticalScrollBar().value()
            if preserve_scroll
            else 0
        )
        outer_scroll = (
            self.detail_scroll_area.verticalScrollBar().value()
            if preserve_scroll
            and hasattr(self, "detail_scroll_area")
            else 0
        )

        self._set_selected_analysis_context(
            a,
            source="dashboard",
            sync_main_table=False,
            timeframe=selected_tf,
        )
        gr01_context_ms = (time.perf_counter_ns() - gr01_context_started_ns) / 1_000_000.0
        gr01_widget_started_ns = time.perf_counter_ns()
        self._set_label_text_if_changed(
            self.detail_title,
            f"<h2>{symbol.replace(':USDT','')} — {a.direction} — {a.priority_status}</h2>",
        )
        yield "header_context"
        if selected_tf not in a.timeframes:
            selected_tf = "15m"
        self.tf_selector.blockSignals(True)
        self.tf_selector.setCurrentText(selected_tf)
        self.tf_selector.blockSignals(False)
        self.market_chart.set_candidate_visibility(
            self.long_zone_btn.isChecked(),
            self.short_zone_btn.isChecked(),
        )
        self.market_chart.set_signal_markers_visible(
            self.signal_marker_btn.isChecked()
        )
        self.market_chart.set_analysis(
            a.timeframes[selected_tf],
            selected_tf,
            a.trade_plan,
            a.direction,
            a,
        )
        self.update_score_explanation(selected_tf)
        self._update_pro_panels(selected_tf)
        yield "chart_and_pro_panels"

        table_updates_enabled = self.tf_table.updatesEnabled()
        table_sorting_enabled = self.tf_table.isSortingEnabled()
        self.tf_table.setUpdatesEnabled(False)
        self.tf_table.setSortingEnabled(False)
        self.tf_table.setRowCount(4)
        selected_row = 0
        try:
            for rr, tf in enumerate(("15m", "1h", "4h", "1d")):
                r = a.timeframes[tf]
                vals = [
                    tf, f"{r.cmf:+.3f}", f"{r.rsi:.1f}", f"{r.adx:.1f}",
                    f"x{r.relative_volume:.2f}", r.market_phase,
                    "Có" if r.spring else "-", "Có" if r.upthrust else "-",
                    f"{r.long_entry_score:.0f}", f"{r.short_entry_score:.0f}",
                ]
                for c, value in enumerate(vals):
                    foreground = None
                    if c == 1:
                        foreground = (
                            QColor("#4ade80")
                            if r.cmf >= 0
                            else QColor("#f87171")
                        )
                    elif c == 2:
                        foreground = (
                            QColor("#facc15")
                            if r.rsi >= 70 or r.rsi <= 30
                            else QColor("#e2e8f0")
                        )
                    self._set_table_item_value(
                        self.tf_table,
                        rr,
                        c,
                        value,
                        foreground,
                    )
                if tf == selected_tf:
                    selected_row = rr
        finally:
            self.tf_table.setSortingEnabled(table_sorting_enabled)
            self.tf_table.setUpdatesEnabled(table_updates_enabled)
        self.tf_table.selectRow(selected_row)
        self.tf_table.viewport().update()
        self._render_smart_entry_for_analysis(a)
        yield "timeframe_table_and_smart_entry"
        gr01_widget_ms = (time.perf_counter_ns() - gr01_widget_started_ns) / 1_000_000.0
        gr01_text_started_ns = time.perf_counter_ns()

        self._set_label_text_if_changed(
            self.core_title,
            f"<h3>{symbol.replace(':USDT','')} — {a.action}</h3>",
        )
        plain_view = self.plain_language_presenter.build(a)
        self._set_html_if_changed(
            self.core_summary,
            self._plain_view_html(plain_view, "Kết luận giao dịch"),
        )
        core_text_value = (
            f"QUYẾT ĐỊNH\n{a.action}\n\n"
            f"THỜI ĐIỂM\n{a.timing}\n\n"
            f"MARKET REGIME\n"
            f"{a.regime.regime} | Direction {a.regime.direction} | "
            f"Strength {a.regime.strength:.0f}/100 | Volatility {a.regime.volatility_state}\n"
            f"{a.regime.description}\n\n"
            f"MULTI-TIMEFRAME\n"
            f"{a.alignment.label}\n"
            f"Long {a.alignment.long_score:.0f}/100 | "
            f"Short {a.alignment.short_score:.0f}/100\n"
            f"Đồng thuận: {', '.join(a.alignment.aligned_timeframes) or '-'}\n"
            f"Mâu thuẫn: {', '.join(a.alignment.conflicting_timeframes) or '-'}\n\n"
            f"RISK ENGINE\n"
            f"Risk Score: {a.risk.risk_score:.0f}/100 — {a.risk.risk_level}\n"
            f"Volatility: {a.risk.volatility_risk:.1f}\n"
            f"Funding: {a.risk.funding_risk:.1f}\n"
            f"OI: {a.risk.oi_risk:.1f}\n"
            f"Extension: {a.risk.extension_risk:.1f}\n"
            f"Conflict: {a.risk.conflict_risk:.1f}\n"
            f"Position size factor tham khảo: x{a.risk.size_factor:.2f}\n"
            f"Leverage cấu hình: {a.risk.leverage:.1f}x\n"
            f"Giá thanh lý ước tính: {a.risk.liquidation_price:.8g}\n"
            f"Khoảng cách thanh lý: {a.risk.liquidation_distance_pct:.2f}%\n"
            f"Đòn bẩy tối đa an toàn: {a.risk.max_safe_leverage:.1f}x\n"
            f"Dynamic buffer: "
            f"{getattr(a.risk, 'dynamic_buffer_used', 0.0):.4f} "
            f"({getattr(a.risk, 'dynamic_buffer_used', 0.0) * 100:.2f}%)\n"
            f"Effective stop distance: "
            f"{getattr(a.risk, 'effective_stop_distance', 0.0):.8g}\n"
            f"Leverage constraint: "
            f"{getattr(a.risk, 'leverage_constraint_state', 'UNKNOWN')}\n"
            f"Notional đề xuất: {a.risk.position_notional:.2f} USDT\n"
            f"Margin cần dùng: {a.risk.margin_required:.2f} USDT\n"
            f"Rủi ro tiền: {a.risk.risk_amount:.2f} USDT\n"
            f"Thanh lý an toàn: {'CÓ' if a.risk.liquidation_safe else 'KHÔNG'}\n\n"
            f"CẢNH BÁO\n- " +
            ("\n- ".join(a.risk.warnings) if a.risk.warnings else "Chưa có cảnh báo rủi ro nổi bật")
            + ("\n\nDECISION PATH · EXPLAINABLE AI\n" + "\n↓\n".join(getattr(getattr(a, "explainable_narrative", None), "decision_path", ())) if getattr(a, "explainable_narrative", None) else "")
            + ("\n\nDECISION BLOCKERS\n- " + "\n- ".join(getattr(a, "explainable_blockers", ())) if getattr(a, "explainable_blockers", ()) else "")
            + "\n\nObserve-only: narrative không thay đổi quyết định, confidence, risk hoặc execution."
        )
        self._set_plain_text_if_changed(self.core_text, core_text_value)

        yield "core_decision_text"

        sdata=a.structure
        self._set_label_text_if_changed(
            self.structure_title,
            f"<h3>{symbol.replace(':USDT','')} — Liquidity & Wyckoff</h3>",
        )
        structure_text_value = (
            f"MỐC THANH KHOẢN\n"
            f"Đỉnh/đáy ngày: {sdata.daily_high:.8g} / {sdata.daily_low:.8g}\n"
            f"Đỉnh/đáy tuần: {sdata.weekly_high:.8g} / {sdata.weekly_low:.8g}\n"
            f"Đỉnh/đáy tháng: {sdata.monthly_high:.8g} / {sdata.monthly_low:.8g}\n\n"
            f"SỰ KIỆN THANH KHOẢN\n{sdata.liquidity_event}\n"
            f"Liquidity Score: {sdata.liquidity_score:.0f}/100\n"
            f"Sweep Volume State: "
            f"{getattr(sdata, 'sweep_volume_state', 'NONE')}\n\n"
            f"WYCKOFF / EFFORT-vs-RESULT\n{sdata.wyckoff_signal}\n"
            f"{sdata.effort_result}\n"
            f"Wyckoff Score: {sdata.wyckoff_score:.0f}/100\n"
            f"Structure Test: "
            f"{getattr(sdata, 'wyckoff_test', 'NONE')}\n"
            f"Test Score: "
            f"{getattr(sdata, 'wyckoff_test_score', 0.0):.0f}/100\n\n"
            f"CẢNH BÁO\n- " + ("\n- ".join(sdata.warnings) if sdata.warnings else "Chưa có cảnh báo nổi bật")
        )
        self._set_plain_text_if_changed(
            self.structure_text,
            structure_text_value,
        )
        p=a.trade_plan
        detail_text_value = (
            f"ACTION: {a.action}\n"
            f"SMART ENTRY: {a.smart_entry.state}\n"
            f"LOI/SOI: {a.smart_entry.long_opportunity_index:.0f}/{a.smart_entry.short_opportunity_index:.0f}\n"
            f"SMP: {a.smart_entry.smart_money_probability:.0f}/100\n"
            f"TIMING: {a.timing}\n"
            f"CONFIDENCE: {a.confidence_score:.1f}/100\n"
            f"RISK: {a.risk.risk_score:.1f}/100 ({a.risk.risk_level})\n"
            f"Dynamic Buffer: "
            f"{getattr(a.risk, 'dynamic_buffer_used', 0.0):.4f} "
            f"({getattr(a.risk, 'dynamic_buffer_used', 0.0) * 100:.2f}%)\n"
            f"Effective Stop: "
            f"{getattr(a.risk, 'effective_stop_distance', 0.0):.8g}\n"
            f"Leverage Constraint: "
            f"{getattr(a.risk, 'leverage_constraint_state', 'UNKNOWN')}\n"
            f"MTF: {a.alignment.label}\n"
            f"REGIME: {a.regime.regime} {a.regime.direction}\n"
            f"Long Trend / Entry: {a.long_trend_score:.1f} / {a.long_entry_score:.1f}\n"
            f"Short Trend / Entry: {a.short_trend_score:.1f} / {a.short_entry_score:.1f}\n"
            f"Entry Status: {a.entry_status.value}\n"
            f"OI: {a.oi_state}\n"
            f"OI 15m / 1h: {a.snapshot.oi_change_15m_pct:+.2f}% / {a.snapshot.oi_change_1h_pct:+.2f}%\n"
            f"Funding: {a.snapshot.funding_pct:+.4f}%\n"
            f"Pha: {a.phase_summary}\n"
            f"Liquidity: {a.structure.liquidity_event}\n"
            f"Sweep Volume: "
            f"{getattr(a.structure, 'sweep_volume_state', 'NONE')}\n"
            f"Wyckoff: {a.structure.wyckoff_signal}\n"
            f"Structure Test: "
            f"{getattr(a.structure, 'wyckoff_test', 'NONE')} "
            f"({getattr(a.structure, 'wyckoff_test_score', 0.0):.0f}/100)\n"
            f"Hỗ trợ 15m: {a.timeframes['15m'].support:.8g}\n"
            f"Kháng cự 15m: {a.timeframes['15m'].resistance:.8g}\n"
            f"ATR 15m: {a.timeframes['15m'].atr:.8g}\n"
            f"Vol 15m / 1h: x{a.timeframes['15m'].relative_volume:.2f} / x{a.timeframes['1h'].relative_volume:.2f}\n\n"
            f"KẾ HOẠCH {p.direction}\nEntry Zone: {p.entry_low:.8g} – {p.entry_high:.8g}\n"
            f"Invalidation: {p.invalidation:.8g}\nTP1: {p.tp1:.8g}\nTP2: {p.tp2:.8g}\nR:R TP2: {p.rr_to_tp2:.2f}\n"
            f"Plan repaired: "
            f"{'CÓ' if getattr(p, 'plan_repaired', False) else 'KHÔNG'}\n"
            f"Repair reason: "
            f"{getattr(p, 'plan_repair_reason', '') or '-'}\n\n"
            "ĐIỀU KIỆN XÁC NHẬN\n- "+"\n- ".join(p.confirmations)+
            "\n\nĐIỀU KIỆN HỦY\n- "+"\n- ".join(p.cancellation_rules)+
            "\n\nAI REASONING & MARKET NARRATIVE\n"
            + (getattr(a, "reasoning_text", "") or "Chưa có narrative.")
            + "\n\nLÝ DO PHÂN TÍCH GỐC\n- "
            + "\n- ".join(a.reasons)
        )
        self._set_plain_text_if_changed(self.detail_text, detail_text_value)

        yield "structure_and_detail_text"

        if preserve_scroll:
            def restore_local_scrolls():
                if hasattr(self, "detail_scroll_area"):
                    self._restore_scroll_value(
                        self.detail_scroll_area.verticalScrollBar(),
                        outer_scroll,
                    )
                self._restore_scroll_value(
                    self.detail_text.verticalScrollBar(),
                    detail_scroll,
                )
                self._restore_scroll_value(
                    self.score_explain.verticalScrollBar(),
                    score_scroll,
                )

            for delay in (0, 40, 140):
                QTimer.singleShot(delay, restore_local_scrolls)
        gr01_text_ms = (time.perf_counter_ns() - gr01_text_started_ns) / 1_000_000.0
        gr01_total_ms = (time.perf_counter_ns() - gr01_callback_started_ns) / 1_000_000.0
        GR01_GUI_FORENSICS.emit(
            "selected_detail_commit",
            generation=int(getattr(self, "_scan_cycle_count", 0) or 0),
            queue_wait_ms=None,
            data_prepare_ms=gr01_context_ms,
            model_transform_ms=0.0,
            table_diff_ms=0.0,
            widget_create_ms=gr01_widget_ms,
            item_update_ms=gr01_text_ms,
            layout_ms=0.0,
            repaint_request_ms=0.0,
            total_callback_ms=gr01_total_ms,
            symbol=str(symbol),
            timeframe=str(selected_tf),
            gui_thread_ident=threading.get_ident(),
        )
