from __future__ import annotations

"""Asynchronous, shadow-only GUI boundary for the Unified Core.

The adapter deliberately exposes no authorization, sizing, order, exchange,
or ledger mutation capabilities. Its only public operation is
``run_cycle_async``; results are immutable read models suitable for display.

3.4.4 stability note: the adapter owns one persistent QThread for its entire
lifetime.  This removes the create/delete-per-click lifecycle race that can
terminate a Qt process without a Python traceback on some Windows builds.
"""

from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

from PySide6.QtCore import QObject, QThread, Signal, Slot

from dvs_ai.application import DVSAICore, UnifiedCycleRequest, UnifiedCycleResult


@dataclass(frozen=True, slots=True)
class CoreCycleRequest:
    cycle: UnifiedCycleRequest
    analysis_revision: int
    request_id: str = ""
    shadow_only: bool = True

    def __post_init__(self) -> None:
        if self.analysis_revision < 0:
            raise ValueError("analysis_revision must be non-negative")
        if not self.shadow_only:
            raise ValueError("CoreRuntimeAdapter only accepts shadow-only requests")
        if not self.request_id:
            object.__setattr__(self, "request_id", uuid4().hex)

    @property
    def symbol(self) -> str:
        return self.cycle.snapshot.symbol


@dataclass(frozen=True, slots=True)
class CoreCycleResultViewModel:
    request_id: str
    analysis_revision: int
    symbol: str
    lifecycle_state: str
    decision: str
    authorized: bool
    risk_allowed: bool
    quantity: float
    reason_codes: tuple[str, ...]
    explanation: tuple[str, ...]
    ledger_verified: bool
    shadow_only: bool


@dataclass(frozen=True, slots=True)
class CoreCycleFailureViewModel:
    request_id: str
    analysis_revision: int
    symbol: str
    error_code: str
    message: str
    shadow_only: bool = True


class _CoreCycleWorker(QObject):
    completed = Signal(object, object)
    failed = Signal(object, object)
    request_finished = Signal()

    def __init__(self, core: DVSAICore) -> None:
        super().__init__()
        self._core = core

    @Slot(object)
    def run_request(self, request: CoreCycleRequest) -> None:
        try:
            result = self._core.run_cycle(request.cycle)
            self.completed.emit(request, result)
        except Exception as exc:  # fail closed at the GUI boundary
            failure = CoreCycleFailureViewModel(
                request_id=request.request_id,
                analysis_revision=request.analysis_revision,
                symbol=request.symbol,
                error_code="UNIFIED_CORE_CYCLE_FAILED",
                message=f"{type(exc).__name__}: {exc}",
            )
            self.failed.emit(request, failure)
        finally:
            self.request_finished.emit()


class CoreRuntimeAdapter(QObject):
    """Latest-request-wins asynchronous projection of :class:`DVSAICore`.

    A single persistent worker thread owns the core. At most one request is
    active and one pending request is retained. Repeated GUI selections
    coalesce to the newest request. Results from superseded requests are
    discarded before reaching the GUI.
    """

    cycle_completed = Signal(object)
    cycle_failed = Signal(object)
    stale_result_discarded = Signal(str)
    _request_worker = Signal(object)

    def __init__(self, core: DVSAICore, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._core = core
        self._thread = QThread(self)
        self._worker = _CoreCycleWorker(core)
        self._worker.moveToThread(self._thread)
        self._request_worker.connect(self._worker.run_request)
        self._worker.completed.connect(self._on_completed)
        self._worker.failed.connect(self._on_failed)
        self._worker.request_finished.connect(self._on_request_finished)
        self._thread.finished.connect(self._worker.deleteLater)
        self._pending: Optional[CoreCycleRequest] = None
        self._latest_request_id: Optional[str] = None
        self._active = False
        self._closed = False
        self._thread.start()

    def run_cycle_async(self, request: CoreCycleRequest) -> None:
        """Queue a shadow-only cycle without blocking the GUI thread."""
        if self._closed:
            raise RuntimeError("CoreRuntimeAdapter is closed")
        if not request.shadow_only:
            raise ValueError("Only shadow-only cycles are permitted")

        self._latest_request_id = request.request_id
        if self._active:
            self._pending = request
            return
        self._dispatch(request)

    def _dispatch(self, request: CoreCycleRequest) -> None:
        if self._closed:
            return
        self._active = True
        self._request_worker.emit(request)

    @Slot(object, object)
    def _on_completed(self, request: CoreCycleRequest, result: UnifiedCycleResult) -> None:
        if request.request_id != self._latest_request_id:
            self.stale_result_discarded.emit(request.request_id)
            return
        self.cycle_completed.emit(self._to_view_model(request, result))

    @Slot(object, object)
    def _on_failed(self, request: CoreCycleRequest, failure: CoreCycleFailureViewModel) -> None:
        if request.request_id != self._latest_request_id:
            self.stale_result_discarded.emit(request.request_id)
            return
        self.cycle_failed.emit(failure)

    @Slot()
    def _on_request_finished(self) -> None:
        self._active = False
        pending, self._pending = self._pending, None
        if pending is not None and not self._closed:
            self._dispatch(pending)

    @staticmethod
    def _to_view_model(
        request: CoreCycleRequest,
        result: UnifiedCycleResult,
    ) -> CoreCycleResultViewModel:
        decision = result.decision
        order = result.order
        risk_allowed = bool(decision.authorized and order.status.value == "FILLED")
        reasons = tuple(dict.fromkeys((*decision.reason_codes, *order.reason_codes)))
        explanation = (
            f"Unified Core decision: {decision.final_action.value}",
            f"Authorized: {decision.authorized}",
            f"Paper outcome: {order.status.value}",
        )
        return CoreCycleResultViewModel(
            request_id=request.request_id,
            analysis_revision=request.analysis_revision,
            symbol=request.symbol,
            lifecycle_state="AVAILABLE" if decision.authorized else "NOT_AVAILABLE",
            decision=decision.final_action.value,
            authorized=bool(decision.authorized),
            risk_allowed=risk_allowed,
            quantity=0.0,
            reason_codes=reasons,
            explanation=explanation,
            ledger_verified=bool(decision.authorized),
            shadow_only=True,
        )

    def _shutdown(self, timeout_ms: int = 5000) -> None:
        """Internal lifecycle hook; not an execution capability."""
        if self._closed:
            return
        self._closed = True
        self._pending = None
        self._thread.quit()
        if not self._thread.wait(timeout_ms):
            # Never terminate a running thread forcefully; leave a diagnostic
            # rather than risking a native Qt crash during application exit.
            self._thread.requestInterruption()
