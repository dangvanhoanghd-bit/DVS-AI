from __future__ import annotations

"""Sequential, observe-only qualification runner for completed scan batches.

The runner owns an isolated Unified Core runtime on one persistent QThread. It
processes every submitted batch item exactly once (subject to SQLite request-id
idempotency) and never exposes execution capabilities to the GUI.
"""

from dataclasses import dataclass
from typing import Iterable, Optional
from uuid import uuid4

from PySide6.QtCore import QObject, QThread, Signal, Slot

from dvs_ai.application import UnifiedCycleRequest
from dvs_ai.governance.paper_authority_handover import (
    FROZEN_PAPER_AUTHORITY_HANDOVER_PROFILE,
)
from dvs_ai.services.core_shadow_agreement_service import (
    CoreShadowAgreementStore,
    ShadowAgreementObservation,
    classify_agreement_result,
)
from dvs_ai.ui.shadow_core_runtime import GuiShadowCoreRuntime


from dvs_ai.services.qualification_batch_diagnostics import (
    LOGGER,
    QualificationBatchFailureJournal,
    QualificationBatchItemFailure,
    build_item_failure,
)


@dataclass(frozen=True, slots=True)
class QualificationBatchItem:
    cycle: UnifiedCycleRequest
    legacy_action: str
    analysis_revision: int
    request_id: str
    confidence: float = 0.0
    regime: str = "UNKNOWN"
    phase: str = "UNKNOWN"
    timeframe: str = "UNKNOWN"

    @property
    def symbol(self) -> str:
        return self.cycle.snapshot.symbol


@dataclass(frozen=True, slots=True)
class QualificationBatch:
    batch_id: str
    items: tuple[QualificationBatchItem, ...]

    @classmethod
    def from_items(
        cls,
        items: Iterable[QualificationBatchItem],
        *,
        batch_id: str = "",
    ) -> "QualificationBatch":
        return cls(batch_id=batch_id or uuid4().hex, items=tuple(items))


@dataclass(frozen=True, slots=True)
class QualificationBatchProgress:
    batch_id: str
    processed: int
    total: int
    inserted: int
    failures: int
    symbol: str


@dataclass(frozen=True, slots=True)
class QualificationBatchSummary:
    batch_id: str
    processed: int
    total: int
    inserted: int
    duplicates: int
    failures: int
    qualification_status: str
    total_cycles: int
    full_agreement_ratio: float
    unsafe_divergences: int
    shadow_prepared_runs_count: int = 0
    shadow_paper_orders_count: int = 0
    shadow_ledger_run_count: int = 0
    shadow_release_run_total: int = 0
    shadow_discard_run_total: int = 0
    shadow_discarded_ledger_events_total: int = 0
    shadow_paper_orders_cleared_total: int = 0


class _QualificationBatchWorker(QObject):
    progress = Signal(object)
    completed = Signal(object)
    failed = Signal(str, str)
    item_failed = Signal(object)

    def __init__(
        self,
        runtime: GuiShadowCoreRuntime,
        store: CoreShadowAgreementStore,
        failure_journal: Optional[QualificationBatchFailureJournal] = None,
    ) -> None:
        super().__init__()
        self._runtime = runtime
        self._store = store
        self._stop_requested = False
        self._failure_journal = failure_journal or QualificationBatchFailureJournal()

    @Slot(object)
    def run_batch(self, batch: QualificationBatch) -> None:
        processed = inserted = duplicates = failures = 0
        total = len(batch.items)
        try:
            for item_index, item in enumerate(batch.items):
                if self._stop_requested:
                    break
                symbol = item.symbol
                try:
                    result = self._runtime.run_cycle(item.cycle)
                    unified = str(result.decision.final_action.value).upper()
                    agreement = classify_agreement_result(
                        item.legacy_action,
                        unified,
                    )
                    ledger_events = self._runtime.ledger.read_run(item.cycle.pipeline_run_id)
                    ledger_hash = ledger_events[-1].event_hash if ledger_events else ""
                    reason_codes = tuple(dict.fromkeys((
                        *tuple(result.decision.reason_codes),
                        *tuple(result.order.reason_codes),
                        *tuple(result.fused_signal.reason_codes),
                    )))
                    was_inserted = self._store.append(
                        ShadowAgreementObservation(
                            request_id=item.request_id,
                            symbol=symbol,
                            analysis_revision=item.analysis_revision,
                            legacy_action=item.legacy_action,
                            unified_action=unified,
                            agreement=agreement.code,
                            ledger_verified=bool(self._runtime.ledger.verify_run(item.cycle.pipeline_run_id)),
                            synthetic_lifecycle=True,
                            confidence=item.confidence,
                            regime=item.regime,
                            phase=item.phase,
                            timeframe=item.timeframe,
                            reason_codes=reason_codes,
                            ledger_hash=ledger_hash,
                            authorized=bool(result.decision.authorized),
                            risk_allowed=bool(result.order.status.value == "FILLED"),
                            quantity=0.0,
                            event_names=tuple(result.event_names),
                        )
                    )
                    if was_inserted:
                        inserted += 1
                    else:
                        duplicates += 1
                except Exception as exc:
                    failures += 1
                    failure = build_item_failure(
                        batch_id=batch.batch_id,
                        request_id=item.request_id,
                        symbol=symbol,
                        item_index=item_index,
                        exc=exc,
                    )
                    LOGGER.exception(
                        "Qualification batch item failed: batch_id=%s request_id=%s symbol=%s item_index=%s",
                        batch.batch_id, item.request_id, symbol, item_index,
                    )
                    try:
                        self._failure_journal.append(failure)
                    except Exception:
                        LOGGER.exception("Qualification failure journal write failed")
                    self.item_failed.emit(failure)
                finally:
                    release_run = getattr(self._runtime, "release_run", None)
                    if callable(release_run):
                        release_run(item.cycle.pipeline_run_id)
                processed += 1
                self.progress.emit(
                    QualificationBatchProgress(
                        batch_id=batch.batch_id,
                        processed=processed,
                        total=total,
                        inserted=inserted,
                        failures=failures,
                        symbol=symbol,
                    )
                )
            metrics = self._store.metrics(
                FROZEN_PAPER_AUTHORITY_HANDOVER_PROFILE
            )
            owner = self._runtime.owner_retention_snapshot()
            self.completed.emit(
                QualificationBatchSummary(
                    batch_id=batch.batch_id,
                    processed=processed,
                    total=total,
                    inserted=inserted,
                    duplicates=duplicates,
                    failures=failures,
                    qualification_status=metrics.qualification_status,
                    total_cycles=metrics.total_cycles,
                    full_agreement_ratio=metrics.full_agreement_ratio,
                    unsafe_divergences=metrics.unsafe_divergences,
                    **owner,
                )
            )
        except Exception as exc:
            self.failed.emit(batch.batch_id, f"{type(exc).__name__}: {exc}")

    @Slot()
    def request_stop(self) -> None:
        self._stop_requested = True


class CoreQualificationBatchRunner(QObject):
    """FIFO batch runner with one active batch and a bounded pending queue."""

    batch_progress = Signal(object)
    batch_completed = Signal(object)
    batch_failed = Signal(str, str)
    batch_rejected = Signal(str, str)
    batch_item_failed = Signal(object)
    _dispatch_batch = Signal(object)
    _request_stop = Signal()

    def __init__(
        self,
        runtime: GuiShadowCoreRuntime,
        store: CoreShadowAgreementStore,
        parent: Optional[QObject] = None,
        *,
        max_pending_batches: int = 2,
        failure_journal: Optional[QualificationBatchFailureJournal] = None,
    ) -> None:
        super().__init__(parent)
        if max_pending_batches < 0:
            raise ValueError("max_pending_batches must be non-negative")
        self._thread = QThread(self)
        self._worker = _QualificationBatchWorker(runtime, store, failure_journal)
        self._worker.moveToThread(self._thread)
        self._dispatch_batch.connect(self._worker.run_batch)
        self._request_stop.connect(self._worker.request_stop)
        self._worker.progress.connect(self.batch_progress)
        self._worker.completed.connect(self._on_completed)
        self._worker.failed.connect(self._on_failed)
        self._worker.item_failed.connect(self.batch_item_failed)
        self._thread.finished.connect(self._worker.deleteLater)
        self._queue: list[QualificationBatch] = []
        self._active = False
        self._closed = False
        self._max_pending_batches = max_pending_batches
        self._thread.start()

    def submit_batch(self, batch: QualificationBatch) -> bool:
        if self._closed:
            raise RuntimeError("CoreQualificationBatchRunner is closed")
        if not batch.items:
            self.batch_rejected.emit(batch.batch_id, "EMPTY_BATCH")
            return False
        if self._active:
            if len(self._queue) >= self._max_pending_batches:
                self.batch_rejected.emit(batch.batch_id, "QUEUE_FULL")
                return False
            self._queue.append(batch)
            return True
        self._start(batch)
        return True

    def _start(self, batch: QualificationBatch) -> None:
        self._active = True
        self._dispatch_batch.emit(batch)

    @Slot(object)
    def _on_completed(self, summary: QualificationBatchSummary) -> None:
        self.batch_completed.emit(summary)
        self._advance()

    @Slot(str, str)
    def _on_failed(self, batch_id: str, message: str) -> None:
        self.batch_failed.emit(batch_id, message)
        self._advance()

    def _advance(self) -> None:
        self._active = False
        if self._queue and not self._closed:
            self._start(self._queue.pop(0))

    def _shutdown(self, timeout_ms: int = 5000) -> None:
        if self._closed:
            return
        self._closed = True
        self._queue.clear()
        self._request_stop.emit()
        self._thread.quit()
        if not self._thread.wait(timeout_ms):
            self._thread.requestInterruption()
