from PySide6.QtWidgets import QApplication
from PySide6.QtCore import qInstallMessageHandler, QCoreApplication, QEvent, QObject
from dvs_ai.runtime.gui_event_loop_forensics import InstrumentedApplication


def _forensic_mode_enabled() -> bool:
    return str(os.environ.get("DVS_FORENSIC_MODE", "0")).strip().lower() in {
        "1", "true", "yes", "on",
    }
from dvs_ai.runtime.qthread_lifecycle_registry import install_qthread_registry
from dvs_ai.runtime.mainwindow_wrapper_forensics import (
    install_application_exit_trace,
    install_mainwindow_wrapper_trace,
    record_mainwindow_wrapper_state,
)
from dvs_ai.runtime.qt_shutdown_forensics import (
    install_qt_shutdown_forensics,
    record_phase as record_qt_shutdown_phase,
    snapshot_shutdown_state,
)
from dvs_ai.runtime.shiboken_wrapper_forensics import (
    install_wrapper_forensics,
    record_wrapper_boundary,
    snapshot_wrappers,
)
from dvs_ai.runtime.safe_wrapper_snapshot_forensics import (
    record_safe_wrapper_checkpoint,
)
install_qthread_registry()
from dvs_ai.config import load_config
from dvs_ai.logging_setup import configure_logging
from dvs_ai.data.binance_provider import BinanceFuturesProvider
from dvs_ai.engines.indicator_engine import IndicatorEngine
from dvs_ai.engines.decision_engine import DecisionEngine
from dvs_ai.services.scanner import ScannerService
from dvs_ai.ui.main_window import MainWindow
from dvs_ai.services.signal_recorder import SignalRecorder
from dvs_ai.services.history_service import HistoryService
from dvs_ai.services.outcome_tracker import OutcomeTracker
from dvs_ai.services.paper_trade_service import PaperTradeService
from dvs_ai.services.learning_service import LearningService
from dvs_ai.services.microstructure_service import MicrostructureService
from dvs_ai.services.order_flow_runtime import OrderFlowRuntime
from dvs_ai.services.probability_calibration_service import ProbabilityCalibrationService
from dvs_ai.services.shadow_observation_service import ShadowObservationRuntime, ShadowObservationStore
from dvs_ai.ui.core_runtime_adapter import CoreRuntimeAdapter
from dvs_ai.ui.core_qualification_batch_runner import CoreQualificationBatchRunner
from dvs_ai.ui.shadow_core_runtime import build_gui_shadow_core_runtime
from dvs_ai.services.core_shadow_agreement_service import CoreShadowAgreementStore
from dvs_ai.services.outcome_infrastructure import OutcomeInfrastructureStore
from dvs_ai.services.live_episode_capture import LiveEpisodeCapture
from dvs_ai.ui.crash_reporting import install_global_exception_reporting
from dvs_ai.ui.live_episode_capture_runner import LiveEpisodeCaptureRunner
from dvs_ai.diagnostics.shutdown_probe import install_shutdown_probe
from dvs_ai.services.runtime_telemetry import RuntimeTelemetryExporter
from dvs_ai.version import APP_VERSION, BUILD_ID
from pathlib import Path
import hashlib
import json
import os
import time
from datetime import datetime, timezone

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_valid_wrapper(obj):
    # S4.1.2-r2A (instrumentation only, no behavior change): report whether
    # the underlying C++ QObject behind a Python wrapper is still alive.
    # shiboken6.isValid() is the public, documented way to ask this without
    # touching the object itself. Any failure (object not a QObject wrapper,
    # shiboken6 unavailable, etc.) is reported as None rather than raising,
    # so this can never change control flow or crash the shutdown path.
    if obj is None:
        return None
    try:
        import shiboken6
        return bool(shiboken6.isValid(obj))
    except Exception:
        return None


def _qobject_class_name(obj):
    # S4.1.2-r2C (instrumentation only): best-effort class name lookup.
    # metaObject().className() is the accurate Qt name; falls back to the
    # Python type name if the wrapper is not a live QObject.
    if obj is None:
        return None
    try:
        return obj.metaObject().className()
    except Exception:
        try:
            return type(obj).__name__
        except Exception:
            return None


def _qobject_cpp_address(obj):
    # S4.1.2-r2C (instrumentation only): read the underlying C++ pointer
    # address behind a Python wrapper via shiboken6.getCppPointer(), the
    # public Shiboken API for this. This is captured up front (Phase 1/2,
    # before deleteLater()) specifically so it can later be correlated
    # against the `this`/register values seen in a WinDbg session for the
    # same crash, since Python id() only identifies the Python wrapper and
    # does not match any C++-side address. Returns None on any failure
    # (object not a QObject wrapper, API unavailable, multiple-inheritance
    # pointer tuple empty, etc.) rather than raising.
    if obj is None:
        return None
    try:
        import shiboken6
        pointers = shiboken6.getCppPointer(obj)
        if pointers:
            return hex(pointers[0])
    except Exception:
        pass
    return None


def _qobject_tree_snapshot(root, out_path):
    # S4.1.2-r2C Phase 1 (instrumentation only, read-only): static snapshot
    # of the entire QObject tree rooted at `root`, taken immediately before
    # window.deleteLater() is posted. findChildren()/metaObject()/
    # objectName()/parent() are all read-only Qt introspection calls; none
    # of them mutate ownership, parenting, or timing of the tree.
    try:
        descendants = list(root.findChildren(QObject))
    except Exception:
        descendants = []
    all_objects = [root] + descendants

    entries = []
    for obj in all_objects:
        try:
            parent_obj = obj.parent()
        except Exception:
            parent_obj = None
        depth = 0
        try:
            cursor = obj
            while cursor is not None and cursor is not root:
                cursor = cursor.parent()
                depth += 1
                if depth > 10_000:
                    break
        except Exception:
            pass
        try:
            object_name = obj.objectName()
        except Exception:
            object_name = None
        entries.append({
            "python_id": hex(id(obj)),
            "cpp_address": _qobject_cpp_address(obj),
            "class_name": _qobject_class_name(obj),
            "object_name": object_name,
            "parent_class": _qobject_class_name(parent_obj),
            "parent_python_id": hex(id(parent_obj)) if parent_obj is not None else None,
            "parent_cpp_address": _qobject_cpp_address(parent_obj),
            "depth": depth,
            "shiboken_valid": _is_valid_wrapper(obj),
        })

    checksum_source = "|".join(
        f"{e['class_name']}:{e['object_name']}:{e['depth']}" for e in entries
    )
    tree_checksum = hashlib.sha256(
        checksum_source.encode("utf-8", errors="replace")
    ).hexdigest()

    payload = {
        "schema_version": "dvs.runtime.qobject_tree_snapshot.v1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "root_class": _qobject_class_name(root),
        "tree_count": len(entries),
        "tree_checksum": tree_checksum,
        "entries": entries,
    }
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass

    return all_objects, entries, tree_checksum


def _install_qobject_destroy_trace(objects, entries, out_path):
    # S4.1.2-r2C Phase 2/3 (instrumentation only): connect destroyed() for
    # every QObject captured in the Phase 1 snapshot, appending a
    # monotonically increasing sequence number to a dedicated jsonl file as
    # each one actually fires. This only observes destruction order; it
    # does not call deleteLater(), close(), or alter any existing
    # connection made elsewhere (e.g. r2A's window/telemetry destroyed
    # marks continue to fire independently of this trace).
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    counter = {"n": 0}
    depth_by_python_id = {
        e["python_id"]: e.get("depth") for e in entries
    }

    def _make_logger(class_name, object_name, python_id, cpp_address, depth):
        def _logger(*_args):
            counter["n"] += 1
            record = {
                "ts_utc": datetime.now(timezone.utc).isoformat(),
                "sequence": counter["n"],
                "class_name": class_name,
                "object_name": object_name,
                "python_id": python_id,
                "cpp_address": cpp_address,
                "depth": depth,
            }
            try:
                with out_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            except Exception:
                pass
        return _logger

    connected = 0
    for obj in objects:
        try:
            class_name = _qobject_class_name(obj)
            try:
                object_name = obj.objectName()
            except Exception:
                object_name = None
            python_id = hex(id(obj))
            # Captured now, before destruction begins, since
            # shiboken6.getCppPointer() may no longer be reliable once the
            # object is mid-destruction when destroyed() actually fires.
            cpp_address = _qobject_cpp_address(obj)
            depth = depth_by_python_id.get(python_id)
            obj.destroyed.connect(
                _make_logger(class_name, object_name, python_id, cpp_address, depth)
            )
            connected += 1
        except Exception:
            continue
    return connected


def _write_runtime_code_identity() -> None:
    project_root = Path(__file__).resolve().parent.parent
    relative_files = (
        "dvs_ai/ui/main_window.py",
        "dvs_ai/ui/crash_reporting.py",
        "dvs_ai/services/runtime_telemetry.py",
        "dvs_ai/runtime/payload_footprint_telemetry.py",
        "dvs_ai/runtime/qthread_lifecycle_registry.py",
        "dvs_ai/runtime/gui_event_loop_forensics.py",
        "dvs_ai/runtime/mainwindow_wrapper_forensics.py",
        "dvs_ai/runtime/shutdown_blocker_registry.py",
        "dvs_ai/runtime/learning_refresh_lifecycle.py",
        "dvs_ai/runtime/learning_dispatch_forensics.py",
        "dvs_ai/runtime/learning_refresh_stabilization.py",
        "dvs_ai/runtime/learning_cooperative_return.py",
        "dvs_ai/runtime/outcome_resolution_forensics.py",
        "dvs_ai/runtime/qt_shutdown_forensics.py",
        "dvs_ai/runtime/shiboken_wrapper_forensics.py",
        "dvs_ai/runtime/safe_wrapper_snapshot_forensics.py",
        "dvs_ai/app.py",
        "run.py",
        "dvs_ai/version.py",
        "dvs_ai/engines/decision_engine.py",
    )
    hashes = {}
    for relative in relative_files:
        path = project_root / relative
        hashes[relative] = _sha256(path) if path.is_file() else None
    payload = {
        "schema_version": "dvs.runtime.code_identity.v1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "monotonic_ns": time.monotonic_ns(),
        "pid": os.getpid(),
        "build_id": BUILD_ID,
        "app_version": APP_VERSION,
        "entry_point": str(Path(__file__).resolve()),
        "source_sha256": hashes,
    }
    target = Path("artifacts/runtime/code_identity.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )



def _install_qt_message_capture() -> None:
    target = Path("artifacts/runtime/qt_messages.jsonl")
    def handler(mode, context, message):
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            payload={"schema_version":"dvs.runtime.qt_message.v1","timestamp_utc":datetime.now(timezone.utc).isoformat(),"mode":str(mode),"category":getattr(context,"category",None),"file":getattr(context,"file",None),"line":getattr(context,"line",None),"message":str(message)}
            with target.open("a",encoding="utf-8") as h: h.write(json.dumps(payload,ensure_ascii=False,sort_keys=True)+"\n")
        except Exception:
            pass
    qInstallMessageHandler(handler)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as h:
            h.write(json.dumps({
                "schema_version": "dvs.runtime.qt_message.v2.4.2",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "event": "qt_message_handler_installed",
            }, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        pass

def main():
    configure_logging()
    install_global_exception_reporting()
    _install_qt_message_capture()
    shutdown_probe = install_shutdown_probe(Path("artifacts/runtime"))
    shutdown_probe.mark("app_main_enter")
    _write_runtime_code_identity()
    # QApplication must exist before any QObject/QThread/QEventLoop-backed
    # runtime is constructed. Creating it later caused the Windows launcher
    # warning: "QEventLoop: Cannot be used without QCoreApplication".
    existing_app = QApplication.instance()
    if existing_app is not None:
        app = existing_app
    elif _forensic_mode_enabled():
        app = InstrumentedApplication([])
    else:
        # RC6.20-TRUE-CLEAN: preserve native Qt event dispatch. The Python
        # QApplication.notify() forensic override is explicit opt-in only.
        app = QApplication([])
    shutdown_probe.attach_application(app)
    shutdown_probe.register_object("qapplication", app)
    config=load_config()
    provider=BinanceFuturesProvider()
    order_flow_runtime = OrderFlowRuntime(
        provider,
        config.watchlist,
        enabled=bool(getattr(config, "microstructure_enabled", True)),
    )
    microstructure = MicrostructureService(
        provider,
        order_flow_store=order_flow_runtime.store,
        collector_diagnostics_provider=order_flow_runtime.diagnostics,
    )
    service=ScannerService(
        provider, IndicatorEngine(), DecisionEngine(config), config.ohlcv_limit,
        microstructure_service=microstructure,
        probability_calibrator=ProbabilityCalibrationService(),
    )
    # One canonical PAPER database path for Paper, Learning, Quantum and Shadow
    # observations. Constructing the store here also runs the idempotency migration
    # before scanner/runtime threads start.
    paper_db_path = "data/dvs_paper_trades.db"
    shadow_store = ShadowObservationStore(paper_db_path)
    outcome_store = OutcomeInfrastructureStore(paper_db_path)
    live_episode_capture = LiveEpisodeCapture(outcome_store, service.decision, config)
    live_episode_capture_runner = LiveEpisodeCaptureRunner(live_episode_capture)
    shadow_observation_runtime = ShadowObservationRuntime(store=shadow_store)
    paper_trade_service = PaperTradeService(
        provider, service.decision, db_path=paper_db_path, config=config,
        observation_runtime=shadow_observation_runtime
    )
    core_runtime_adapter = CoreRuntimeAdapter(build_gui_shadow_core_runtime())
    core_shadow_agreement_store = CoreShadowAgreementStore(
        "data/core_shadow_agreement.sqlite3"
    )
    core_qualification_batch_runner = CoreQualificationBatchRunner(
        build_gui_shadow_core_runtime(),
        core_shadow_agreement_store,
    )
    window=MainWindow(
        config, service, SignalRecorder(), HistoryService(),
        OutcomeTracker(provider),
        paper_trade_service,
        LearningService(paper_db_path),
        order_flow_runtime=order_flow_runtime,
        shadow_observation_runtime=shadow_observation_runtime,
        core_runtime_adapter=core_runtime_adapter,
        core_shadow_agreement_store=core_shadow_agreement_store,
        core_qualification_batch_runner=core_qualification_batch_runner,
        live_episode_capture=live_episode_capture_runner,
    )
    shutdown_probe.register_object("main_window", window)
    _rc2_mainwindow_trace = install_mainwindow_wrapper_trace(
        window,
        out_path=Path("artifacts/runtime/mainwindow_wrapper_trace.jsonl"),
        build_id=BUILD_ID,
    )
    install_application_exit_trace(
        app,
        _rc2_mainwindow_trace,
        window,
    )
    install_qt_shutdown_forensics(app, window)
    install_wrapper_forensics(app, window)
    snapshot_wrappers(
        "startup_after_window_instrumentation",
        app=app,
        window=window,
    )
    record_safe_wrapper_checkpoint(
        "startup_snapshot_completed",
        observer_mode="snapshot_only",
    )
    # S4.1.2-r2A (instrumentation only): record the moment window's C++
    # object is actually destroyed, if it ever is, before interpreter exit.
    try:
        window.destroyed.connect(
            lambda *_: shutdown_probe.mark("main_window_destroyed_signal")
        )
    except Exception as _exc:
        shutdown_probe.mark(
            "main_window_destroyed_probe_failed", error=repr(_exc)
        )
    for _name in (
        "_history_prepare_thread", "_history_prepare_worker",
        "_paper_prepare_thread", "_paper_prepare_worker",
        "_auto_paper_worker_thread", "_auto_paper_worker",
        "_signal_record_thread", "_signal_record_worker",
        "_qualification_metrics_thread", "_qualification_metrics_worker",
        "_learning_thread", "_learning_worker",
        "finalization_thread", "finalization_worker",
        "_scan_runtime_thread", "_scan_runtime",
    ):
        _obj = getattr(window, _name, None)
        if _obj is not None:
            try:
                shutdown_probe.register_object(f"main_window.{_name}", _obj)
            except Exception as _exc:
                shutdown_probe.mark("probe_registration_failed", name=_name, error=repr(_exc))
    # IR-01A-r5: static forensic relations only. These calls do not alter
    # QObject ownership, signal wiring, or thread affinity.
    for _thread_attr, _worker_attr in (
        ("_history_prepare_thread", "_history_prepare_worker"),
        ("_paper_prepare_thread", "_paper_prepare_worker"),
        ("_auto_paper_worker_thread", "_auto_paper_worker"),
        ("_signal_record_thread", "_signal_record_worker"),
        ("_qualification_metrics_thread", "_qualification_metrics_worker"),
        ("_learning_thread", "_learning_worker"),
        ("finalization_thread", "finalization_worker"),
        ("_scan_runtime_thread", "_scan_runtime"),
    ):
        if getattr(window, _thread_attr, None) is not None and getattr(window, _worker_attr, None) is not None:
            shutdown_probe.register_relation(f"main_window.{_thread_attr}", f"main_window.{_worker_attr}")

    _truth = getattr(window, "truth_dashboard", None)
    if _truth is not None:
        try:
            shutdown_probe.register_object("truth_dashboard", _truth)
            for _name in (
                "_scientific_thread", "_scientific_worker",
                "_history_thread", "_history_worker",
                "_operational_thread", "_operational_worker",
                "_observation_thread", "_observation_worker",
            ):
                _obj = getattr(_truth, _name, None)
                if _obj is not None:
                    shutdown_probe.register_object(f"truth_dashboard.{_name}", _obj)
        except Exception as _exc:
            shutdown_probe.mark("probe_registration_failed", name="truth_dashboard", error=repr(_exc))
    if _truth is not None:
        for _thread_attr, _worker_attr in (
            ("_scientific_thread", "_scientific_worker"),
            ("_history_thread", "_history_worker"),
            ("_operational_thread", "_operational_worker"),
            ("_observation_thread", "_observation_worker"),
        ):
            if getattr(_truth, _thread_attr, None) is not None and getattr(_truth, _worker_attr, None) is not None:
                shutdown_probe.register_relation(f"truth_dashboard.{_thread_attr}", f"truth_dashboard.{_worker_attr}")

    # V2.4 startup gate: make the shell visible and paintable before starting
    # the order-flow runtime, whose provider/WMI/filesystem initialization may
    # otherwise delay Windows message processing.
    window.defer_until_first_paint(order_flow_runtime.start)
    window.showMaximized()
    telemetry = RuntimeTelemetryExporter(
        root=Path("artifacts/runtime"),
        version=APP_VERSION,
        window=window,
        build_label="G2_AB_CANDIDATE",
        parent=window,
    )
    shutdown_probe.register_object("runtime_telemetry_exporter", telemetry)
    # S4.1.2-r2A (instrumentation only): record the moment telemetry's C++
    # object is actually destroyed, if it ever is, before interpreter exit.
    # Guarded because we have not independently confirmed
    # RuntimeTelemetryExporter is a QObject subclass with a destroyed signal.
    try:
        telemetry.destroyed.connect(
            lambda *_: shutdown_probe.mark("runtime_telemetry_destroyed_signal")
        )
    except Exception as _exc:
        shutdown_probe.mark(
            "runtime_telemetry_destroyed_probe_failed", error=repr(_exc)
        )
    telemetry.start()
    shutdown_probe.mark("qt_event_loop_enter")
    try:
        record_mainwindow_wrapper_state(
            _rc2_mainwindow_trace,
            "app_exec_enter",
            window,
            app_closing_down=bool(QCoreApplication.closingDown()),
        )
        exit_code = app.exec()
        record_mainwindow_wrapper_state(
            _rc2_mainwindow_trace,
            "app_exec_returned",
            window,
            exit_code=exit_code,
            app_closing_down=bool(QCoreApplication.closingDown()),
        )
        shutdown_probe.mark("qt_event_loop_exit", exit_code=int(exit_code))
        shutdown_probe.snapshot_application_qobjects("qt_event_loop_exit")
        return exit_code
    finally:
        record_mainwindow_wrapper_state(
            _rc2_mainwindow_trace,
            "main_finally_enter",
            window,
            app_closing_down=bool(QCoreApplication.closingDown()),
        )
        shutdown_probe.mark("app_finally_enter")
        # S4.1.2-r2A (instrumentation only): snapshot whether window/telemetry
        # C++ objects are still alive at the moment we enter finally, i.e.
        # immediately after app.exec() returns and before any teardown here.
        shutdown_probe.mark(
            "root_wrapper_validity_finally_enter",
            window_valid=_is_valid_wrapper(window),
            telemetry_valid=_is_valid_wrapper(telemetry),
        )
        shutdown_probe.snapshot_threads("app_finally_enter")
        shutdown_probe.snapshot_tracked_objects("app_finally_enter")
        shutdown_probe.snapshot_application_qobjects("app_finally_enter")
        record_safe_wrapper_checkpoint("app_finally_enter")
        record_qt_shutdown_phase("app_finally_enter")
        snapshot_shutdown_state(
            "app_finally_enter",
            app=app,
            window=window,
        )
        record_wrapper_boundary(
            "app_finally_enter_wrapper_state",
            window,
            label="main_window",
        )
        snapshot_wrappers(
            "app_finally_enter",
            app=app,
            window=window,
        )
        shutdown_probe.mark("telemetry_stop_begin")
        telemetry.stop()
        shutdown_probe.mark("telemetry_stop_end")
        shutdown_probe.mark("order_flow_close_begin")
        order_flow_runtime.close()
        shutdown_probe.mark("order_flow_close_end")

        # S4.1.2-r2B: deterministic root wrapper shutdown.
        #
        # r2A proved (RUNTIME VERIFIED) that window/telemetry are still
        # valid Shiboken wrappers at both finally_enter and finally_exit,
        # with application_qobject_census showing zero objects freed across
        # the whole finally block, and no destroyed signal ever firing for
        # either object. This block closes that gap.
        #
        # window.close() is intentionally NOT called here: MainWindow's
        # closeEvent already ran earlier (qt_last_window_closed /
        # qt_about_to_quit / qt_event_loop_exit already observed by the time
        # we reach finally), and re-entering that complex closeEvent path
        # would introduce a second, uncontrolled lifecycle variable. This
        # block only schedules and drains the actual C++ destruction.
        #
        # telemetry is a genuine QObject child of window (parent=window),
        # with its four QTimers parented to telemetry itself. Qt's
        # parent-child ownership means destroying window's C++ object
        # cascades to telemetry and its timers automatically; telemetry is
        # therefore NOT deleted separately here.
        shutdown_probe.mark(
            "root_wrapper_delete_begin",
            window_valid=_is_valid_wrapper(window),
            telemetry_valid=_is_valid_wrapper(telemetry),
        )
        record_wrapper_boundary(
            "root_wrapper_delete_begin",
            window,
            label="main_window",
            telemetry_python_id=hex(id(telemetry)) if telemetry is not None else None,
            telemetry_valid=_is_valid_wrapper(telemetry),
        )
        snapshot_wrappers(
            "root_wrapper_delete_begin",
            app=app,
            window=window,
        )

        # S4.1.2-r2C (instrumentation only): take a static snapshot of the
        # entire QObject tree rooted at window, then connect destroyed()
        # for every object in it with an increasing sequence number. This
        # runs strictly before window.deleteLater() below and does not
        # change when or how deletion happens; it only records what exists
        # right now and what actually gets destroyed, in what order,
        # before the process potentially crashes mid-teardown.
        _r2c_tree_objects, _r2c_tree_entries, _r2c_tree_checksum = _qobject_tree_snapshot(
            window, Path("artifacts/runtime/qobject_tree_snapshot.json")
        )
        shutdown_probe.mark(
            "qobject_tree_snapshot_taken",
            tree_count=len(_r2c_tree_entries),
            tree_checksum=_r2c_tree_checksum,
        )
        _r2c_connected_count = _install_qobject_destroy_trace(
            _r2c_tree_objects,
            _r2c_tree_entries,
            Path("artifacts/runtime/qobject_destroy_trace.jsonl"),
        )
        shutdown_probe.mark(
            "qobject_destroy_trace_installed",
            connected_count=_r2c_connected_count,
        )

        # DVS AI v2.4.3 RC5 — Root Deletion Strategy Isolation.
        #
        # CONTROL is RC4, where window.deleteLater() is posted and a bounded
        # DeferredDelete drain is executed after app.exec() returns.
        #
        # EXPERIMENT RC5 changes exactly one controlled variable:
        # do NOT explicitly delete the MainWindow C++ object and do NOT pump
        # DeferredDelete events here. Strong Python references remain intact
        # through finally so cleanup is delegated to the normal Qt/Python
        # ownership/finalization path.
        #
        # No close policy, worker shutdown, telemetry stop, order-flow close,
        # QObject parenting, Decision Engine, or application logic is changed.
        record_mainwindow_wrapper_state(
            _rc2_mainwindow_trace,
            "root_delete_strategy_selected",
            window,
            strategy="NO_EXPLICIT_DELETE_LATER",
            control_release="RC4",
        )
        shutdown_probe.mark(
            "root_delete_strategy_selected",
            strategy="NO_EXPLICIT_DELETE_LATER",
            control_release="RC4",
            window_valid=_is_valid_wrapper(window),
            telemetry_valid=_is_valid_wrapper(telemetry),
        )

        _window_valid_after_drain = _is_valid_wrapper(window)
        _telemetry_valid_after_drain = _is_valid_wrapper(telemetry)

        record_mainwindow_wrapper_state(
            _rc2_mainwindow_trace,
            "root_delete_strategy_complete",
            window,
            strategy="NO_EXPLICIT_DELETE_LATER",
            explicit_delete_posted=False,
            manual_deferred_delete_drain=False,
            python_references_released=False,
            window_valid=_window_valid_after_drain,
            telemetry_valid=_telemetry_valid_after_drain,
        )
        shutdown_probe.mark(
            "root_delete_strategy_complete",
            strategy="NO_EXPLICIT_DELETE_LATER",
            explicit_delete_posted=False,
            manual_deferred_delete_drain=False,
            python_references_released=False,
            window_valid=_window_valid_after_drain,
            telemetry_valid=_telemetry_valid_after_drain,
        )
        record_wrapper_boundary(
            "root_delete_strategy_complete",
            window,
            label="main_window",
            strategy="NO_EXPLICIT_DELETE_LATER",
            window_valid=_window_valid_after_drain,
            telemetry_valid=_telemetry_valid_after_drain,
        )
        snapshot_wrappers(
            "root_delete_strategy_complete",
            app=app,
            window=window,
        )

        shutdown_probe.snapshot_threads("app_finally_exit")
        shutdown_probe.snapshot_tracked_objects("app_finally_exit")
        shutdown_probe.snapshot_application_qobjects("app_finally_exit")
        record_safe_wrapper_checkpoint("app_finally_exit")
        record_qt_shutdown_phase("app_finally_exit")
        snapshot_shutdown_state(
            "app_finally_exit",
            app=app,
            window=window,
        )
        record_wrapper_boundary(
            "app_finally_exit_wrapper_state",
            window,
            label="main_window",
        )
        snapshot_wrappers(
            "app_finally_exit",
            app=app,
            window=window,
        )
        # S4.1.2-r2A (instrumentation only): snapshot again right before we
        # actually leave main() / finally and control returns to run.py,
        # which is the last point before CPython begins Py_FinalizeEx.
        # Reuses the values already captured after the r2B drain loop above
        # (not re-checked here) because window/telemetry may already be None
        # locally at this point if root_python_references_released fired.
        shutdown_probe.mark(
            "root_wrapper_validity_finally_exit",
            window_valid=_window_valid_after_drain,
            telemetry_valid=_telemetry_valid_after_drain,
        )

        # F3-R4-R2L — minimal root-wrapper lifetime remediation candidate.
        telemetry = None
        window = None

        shutdown_probe.mark("app_finally_exit")
