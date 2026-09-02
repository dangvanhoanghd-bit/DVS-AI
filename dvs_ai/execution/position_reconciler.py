from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .models import ExecutionMode, ExecutionResult, OrderStatus
from .position_tracker import PositionTracker, TrackedPosition


class ReconciliationCode(str, Enum):
    OK = "OK"
    ORDER_NOT_FILLED = "ORDER_NOT_FILLED"
    POSITION_NOT_FOUND = "POSITION_NOT_FOUND"
    FILL_MISMATCH = "FILL_MISMATCH"
    UNPROTECTED_POSITION = "UNPROTECTED_POSITION"


@dataclass(frozen=True)
class ReconciliationResult:
    ok: bool
    code: ReconciliationCode
    message: str
    position: TrackedPosition | None = None


class PositionReconciler:
    """Reconciles fills into the local tracker. PAPER is deterministic."""

    def __init__(self, tracker: PositionTracker) -> None:
        self.tracker = tracker

    def reconcile_fill(
        self,
        *,
        execution_result: ExecutionResult,
        direction: str,
        invalidation: float,
        tp1: float,
        tp2: float,
        require_protective_stop: bool,
        protective_stop_attached: bool,
    ) -> ReconciliationResult:
        if (
            not execution_result.accepted
            or execution_result.status
            not in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)
        ):
            return ReconciliationResult(
                False,
                ReconciliationCode.ORDER_NOT_FILLED,
                execution_result.message or "Order is not filled.",
            )
        if execution_result.filled_quantity <= 0:
            return ReconciliationResult(
                False,
                ReconciliationCode.FILL_MISMATCH,
                "Filled quantity is zero.",
            )

        self.tracker.register_fill(
            symbol=execution_result.symbol,
            direction=direction,
            quantity=execution_result.filled_quantity,
            entry_price=execution_result.average_price,
            invalidation=invalidation,
            tp1=tp1,
            tp2=tp2,
            client_order_id=execution_result.client_order_id,
            protective_stop_attached=protective_stop_attached,
        )
        position = self.tracker.get(execution_result.client_order_id)
        if position is None:
            return ReconciliationResult(
                False,
                ReconciliationCode.POSITION_NOT_FOUND,
                "Position was not persisted.",
            )

        if require_protective_stop and not protective_stop_attached:
            self.tracker.mark_reconciliation_failed(
                execution_result.client_order_id
            )
            return ReconciliationResult(
                False,
                ReconciliationCode.UNPROTECTED_POSITION,
                "Protective stop is required but not attached.",
                self.tracker.get(execution_result.client_order_id),
            )

        return ReconciliationResult(
            True,
            ReconciliationCode.OK,
            "Position reconciled.",
            position,
        )
