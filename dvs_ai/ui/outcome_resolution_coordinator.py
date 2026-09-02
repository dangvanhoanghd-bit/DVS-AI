from __future__ import annotations

import json
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot

from dvs_ai.services.outcome_infrastructure import OutcomeInfrastructureStore
from dvs_ai.services.candidate_outcome_resolver import CandidateOutcomeResolver

_TELEMETRY_PATH = Path("artifacts/runtime/outcome_resolution_lifecycle.jsonl")


def _write_event(event: str, **fields) -> None:
    try:
        _TELEMETRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {"timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "event": event, **fields}
        with _TELEMETRY_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _cancelled(cancel_event: threading.Event, deadline_monotonic: float | None) -> bool:
    return cancel_event.is_set() or (deadline_monotonic is not None and time.monotonic() >= deadline_monotonic)


@dataclass(frozen=True)
class ResolutionSummary:
    run_id: str
    checked: int
    updated: int
    errors: int
    scan: dict
    paper: dict


class _OutcomeResolutionWorker(QObject):
    completed = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal(str, str)

    def __init__(self, outcome_tracker, paper_trade_service, store: OutcomeInfrastructureStore,
                 cancel_event: threading.Event) -> None:
        super().__init__()
        self.outcome_tracker = outcome_tracker
        self.paper_trade_service = paper_trade_service
        self.store = store
        self.cancel_event = cancel_event
        self.candidate_resolver = CandidateOutcomeResolver(outcome_tracker.provider, store)
        self.deadline_monotonic: float | None = None
        self.active_stage: str | None = None
        self.active_run_id: str | None = None
        self.cycle_started_ns: int | None = None
        self.stage_started_ns: int | None = None

    def request_cancel(self, deadline_monotonic: float | None) -> None:
        self.deadline_monotonic = deadline_monotonic
        self.cancel_event.set()
        try:
            from dvs_ai.runtime.outcome_resolution_forensics import (
                record_outcome_resolution,
            )
            record_outcome_resolution(
                "worker_cancel_requested",
                deadline_monotonic=deadline_monotonic,
                active_stage=self.active_stage,
                active_run_id=self.active_run_id,
            )
        except Exception:
            pass

    def _is_cancelled(self) -> bool:
        return _cancelled(self.cancel_event, self.deadline_monotonic)

    @Slot()
    def run_cycle(self) -> None:
        # Cancellation is cleared by the coordinator immediately before dispatch.
        # Never clear it here: shutdown may race with queued slot delivery.
        run_id = self.store.start_run()
        checked = updated = errors = 0
        scan = paper = candidate = {}
        active_stage = "START"
        self.active_run_id = run_id
        self.active_stage = active_stage
        self.cycle_started_ns = time.monotonic_ns()
        self.stage_started_ns = self.cycle_started_ns
        _write_event("outcome_resolution_cycle_started", run_id=run_id)
        try:
            from dvs_ai.runtime.outcome_resolution_forensics import (
                record_outcome_resolution,
            )
            record_outcome_resolution(
                "worker_cycle_enter",
                active_run_id=run_id,
                active_stage=active_stage,
            )
        except Exception:
            pass
        try:
            if self._is_cancelled():
                raise InterruptedError("cancelled before first stage")
            active_stage = "SCAN_SIGNALS"
            self.active_stage = active_stage
            self.stage_started_ns = time.monotonic_ns()
            _write_event("outcome_resolution_stage_started", run_id=run_id, stage=active_stage)
            try:
                from dvs_ai.runtime.outcome_resolution_forensics import (
                    record_outcome_resolution,
                )
                record_outcome_resolution(
                    "worker_stage_enter",
                    active_run_id=run_id,
                    active_stage=active_stage,
                )
            except Exception:
                pass
            try:
                scan = self.outcome_tracker.evaluate_pending(
                    limit=100, cancel_event=self.cancel_event,
                    deadline_monotonic=lambda: self.deadline_monotonic,
                )
                checked += int(scan.get("checked", 0)); updated += int(scan.get("updated", 0)); errors += int(scan.get("errors", 0))
            except InterruptedError:
                raise
            except Exception as exc:
                errors += 1
                self.store.record_failure(run_id=run_id, source_type="SCAN_SIGNALS", source_record_id=None,
                                          symbol=None, exc=exc, traceback_text=traceback.format_exc())
            if self._is_cancelled():
                raise InterruptedError("cancelled after scan signals")

            active_stage = "PAPER_TRADES"
            self.active_stage = active_stage
            self.stage_started_ns = time.monotonic_ns()
            _write_event("outcome_resolution_stage_started", run_id=run_id, stage=active_stage)
            try:
                from dvs_ai.runtime.outcome_resolution_forensics import (
                    record_outcome_resolution,
                )
                record_outcome_resolution(
                    "worker_stage_enter",
                    active_run_id=run_id,
                    active_stage=active_stage,
                )
            except Exception:
                pass
            try:
                paper = self.paper_trade_service.update_open_trades(
                    limit=100, cancel_event=self.cancel_event,
                    deadline_monotonic=lambda: self.deadline_monotonic,
                )
                checked += int(paper.get("checked", 0)); updated += int(paper.get("updated", paper.get("closed", 0))); errors += int(paper.get("errors", 0))
            except InterruptedError:
                raise
            except Exception as exc:
                errors += 1
                self.store.record_failure(run_id=run_id, source_type="PAPER_TRADES", source_record_id=None,
                                          symbol=None, exc=exc, traceback_text=traceback.format_exc())
            if self._is_cancelled():
                raise InterruptedError("cancelled after paper trades")

            active_stage = "CANDIDATE_OUTCOMES"
            self.active_stage = active_stage
            self.stage_started_ns = time.monotonic_ns()
            _write_event("outcome_resolution_stage_started", run_id=run_id, stage=active_stage)
            try:
                from dvs_ai.runtime.outcome_resolution_forensics import (
                    record_outcome_resolution,
                )
                record_outcome_resolution(
                    "worker_stage_enter",
                    active_run_id=run_id,
                    active_stage=active_stage,
                )
            except Exception:
                pass
            try:
                candidate = self.candidate_resolver.resolve_pending(
                    limit=100, run_id=run_id, cancel_event=self.cancel_event,
                    deadline_monotonic=lambda: self.deadline_monotonic,
                )
                checked += int(candidate.get("checked", 0)); updated += int(candidate.get("updated", 0)); errors += int(candidate.get("errors", 0))
            except InterruptedError:
                raise
            except Exception as exc:
                errors += 1
                self.store.record_failure(run_id=run_id, source_type="CANDIDATE_OUTCOMES", source_record_id=None,
                                          symbol=None, exc=exc, traceback_text=traceback.format_exc())
            if self._is_cancelled():
                raise InterruptedError("cancelled after candidate outcomes")

            status = "COMPLETED_WITH_ERRORS" if errors else "COMPLETED"
            self.store.finish_run(run_id, status=status, checked=checked, updated=updated, errors=errors)
            _write_event("outcome_resolution_cycle_completed", run_id=run_id, status=status,
                         checked=checked, updated=updated, errors=errors)
            try:
                from dvs_ai.runtime.outcome_resolution_forensics import (
                    record_outcome_resolution,
                )
                record_outcome_resolution(
                    "worker_cycle_completed",
                    active_run_id=run_id,
                    active_stage=active_stage,
                    checked=checked,
                    updated=updated,
                    errors=errors,
                    status=status,
                )
            except Exception:
                pass
            self.completed.emit(ResolutionSummary(run_id, checked, updated, errors, scan, paper))
        except InterruptedError as exc:
            self.store.finish_run(run_id, status="CANCELLED_ON_SHUTDOWN", checked=checked,
                                  updated=updated, errors=errors, error_message=str(exc))
            _write_event("outcome_resolution_cycle_cancelled", run_id=run_id, stage=active_stage,
                         checked=checked, updated=updated, errors=errors, reason=str(exc))
            try:
                from dvs_ai.runtime.outcome_resolution_forensics import (
                    record_outcome_resolution,
                )
                record_outcome_resolution(
                    "worker_cycle_cancelled",
                    active_run_id=run_id,
                    active_stage=active_stage,
                    checked=checked,
                    updated=updated,
                    errors=errors,
                    reason=str(exc),
                )
            except Exception:
                pass
            self.cancelled.emit(run_id, str(exc))
        except Exception as exc:
            self.store.finish_run(run_id, status="FAILED", checked=checked, updated=updated,
                                  errors=errors + 1, error_message=f"{type(exc).__name__}: {exc}")
            _write_event("outcome_resolution_cycle_failed", run_id=run_id, stage=active_stage,
                         error=f"{type(exc).__name__}: {exc}")
            try:
                from dvs_ai.runtime.outcome_resolution_forensics import (
                    record_outcome_resolution,
                )
                record_outcome_resolution(
                    "worker_cycle_failed",
                    active_run_id=run_id,
                    active_stage=active_stage,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            except Exception:
                pass
            self.failed.emit(run_id, f"{type(exc).__name__}: {exc}")
        finally:
            self.active_stage = None
            self.active_run_id = None
            self.cycle_started_ns = None
            self.stage_started_ns = None


class OutcomeResolutionCoordinator(QObject):
    """Persistent QThread with bounded cooperative cancellation on shutdown."""

    cycle_completed = Signal(object)
    cycle_failed = Signal(str, str)
    _dispatch = Signal()

    def __init__(self, outcome_tracker, paper_trade_service,
                 store: OutcomeInfrastructureStore, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._cancel_event = threading.Event()
        self._thread = QThread(self)
        self._thread.setObjectName("dvs-outcome-resolution")
        self._worker = _OutcomeResolutionWorker(outcome_tracker, paper_trade_service, store, self._cancel_event)
        self._worker.moveToThread(self._thread)
        self._dispatch.connect(self._worker.run_cycle)
        self._worker.completed.connect(self._on_completed)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(self._on_cancelled)
        self._thread.finished.connect(self._worker.deleteLater)
        self._active = False
        self._pending_refresh = False
        self._shutdown_requested = False
        self._closed = False
        self._forensic_dispatch_count = 0
        try:
            from dvs_ai.runtime.outcome_resolution_forensics import (
                record_outcome_resolution,
            )
            self._thread.started.connect(
                lambda: record_outcome_resolution(
                    "qthread_started",
                    coordinator=self,
                )
            )
            self._thread.finished.connect(
                lambda: record_outcome_resolution(
                    "qthread_finished",
                    coordinator=self,
                )
            )
            record_outcome_resolution(
                "coordinator_created",
                coordinator=self,
            )
        except Exception:
            pass
        self._thread.start()

    def request_resolution(self) -> bool:
        try:
            from dvs_ai.runtime.outcome_resolution_forensics import (
                record_outcome_resolution,
            )
            record_outcome_resolution(
                "dispatch_attempt",
                coordinator=self,
            )
        except Exception:
            pass
        if self._closed or self._shutdown_requested:
            try:
                record_outcome_resolution(
                    "dispatch_rejected_closing",
                    coordinator=self,
                )
            except Exception:
                pass
            raise RuntimeError("OutcomeResolutionCoordinator is closing or closed")
        if self._active:
            self._pending_refresh = True
            try:
                record_outcome_resolution(
                    "dispatch_coalesced_pending",
                    coordinator=self,
                )
            except Exception:
                pass
            return False
        self._cancel_event.clear()
        self._worker.deadline_monotonic = None
        self._active = True
        self._forensic_dispatch_count += 1
        try:
            record_outcome_resolution(
                "dispatch_accepted",
                coordinator=self,
                dispatch_index=self._forensic_dispatch_count,
            )
        except Exception:
            pass
        self._dispatch.emit()
        try:
            record_outcome_resolution(
                "dispatch_signal_emitted",
                coordinator=self,
                dispatch_index=self._forensic_dispatch_count,
            )
        except Exception:
            pass
        return True

    @Slot(object)
    def _on_completed(self, summary: ResolutionSummary) -> None:
        self.cycle_completed.emit(summary)
        self._advance()

    @Slot(str, str)
    def _on_failed(self, run_id: str, message: str) -> None:
        self.cycle_failed.emit(run_id, message)
        self._advance()

    @Slot(str, str)
    def _on_cancelled(self, run_id: str, message: str) -> None:
        self._advance()

    def _advance(self) -> None:
        try:
            from dvs_ai.runtime.outcome_resolution_forensics import (
                record_outcome_resolution,
            )
            record_outcome_resolution(
                "advance_enter",
                coordinator=self,
            )
        except Exception:
            pass
        self._active = False
        if self._pending_refresh and not self._shutdown_requested and not self._closed:
            self._pending_refresh = False
            try:
                record_outcome_resolution(
                    "advance_releasing_pending",
                    coordinator=self,
                )
            except Exception:
                pass
            self.request_resolution()
        else:
            try:
                record_outcome_resolution(
                    "advance_idle",
                    coordinator=self,
                )
            except Exception:
                pass

    def close(self, timeout_ms: int = 5000) -> bool:
        try:
            from dvs_ai.runtime.outcome_resolution_forensics import (
                record_outcome_resolution,
            )
            record_outcome_resolution(
                "close_enter",
                coordinator=self,
                timeout_ms=int(timeout_ms),
            )
        except Exception:
            pass
        if self._closed:
            try:
                record_outcome_resolution(
                    "close_already_closed",
                    coordinator=self,
                    timeout_ms=int(timeout_ms),
                )
            except Exception:
                pass
            return True
        self._shutdown_requested = True
        self._pending_refresh = False
        started = time.monotonic()
        deadline = started + max(0, int(timeout_ms)) / 1000.0
        _write_event("outcome_resolution_shutdown_requested", timeout_ms=int(timeout_ms),
                     thread_running=bool(self._thread.isRunning()), active=bool(self._active))
        self._worker.request_cancel(deadline)
        try:
            record_outcome_resolution(
                "request_interruption_begin",
                coordinator=self,
            )
        except Exception:
            pass
        self._thread.requestInterruption()
        try:
            record_outcome_resolution(
                "qthread_quit_begin",
                coordinator=self,
            )
        except Exception:
            pass
        self._thread.quit()
        remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
        try:
            record_outcome_resolution(
                "qthread_wait_begin",
                coordinator=self,
                remaining_ms=remaining_ms,
            )
        except Exception:
            pass
        finished = bool(self._thread.wait(remaining_ms))
        waited_ms = round((time.monotonic() - started) * 1000.0, 3)
        if not finished or self._thread.isRunning():
            _write_event("outcome_resolution_shutdown_timeout", timeout_ms=int(timeout_ms),
                         waited_ms=waited_ms, thread_running=bool(self._thread.isRunning()),
                         thread_finished=bool(self._thread.isFinished()), active=bool(self._active))
            try:
                record_outcome_resolution(
                    "qthread_wait_timeout",
                    coordinator=self,
                    timeout_ms=int(timeout_ms),
                    waited_ms=waited_ms,
                    finished=bool(finished),
                )
            except Exception:
                pass
            return False
        self._closed = True
        _write_event("outcome_resolution_shutdown_completed", waited_ms=waited_ms,
                     thread_running=False, thread_finished=True)
        try:
            record_outcome_resolution(
                "qthread_wait_completed",
                coordinator=self,
                timeout_ms=int(timeout_ms),
                waited_ms=waited_ms,
                finished=bool(finished),
            )
            record_outcome_resolution(
                "close_completed",
                coordinator=self,
                waited_ms=waited_ms,
            )
        except Exception:
            pass
        return True
