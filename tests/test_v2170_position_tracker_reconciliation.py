from pathlib import Path

from dvs_ai.execution import (
    ExecutionMode,
    ExecutionResult,
    OrderStatus,
    PositionReconciler,
    PositionTracker,
    ReconciliationCode,
    TrackedPositionStatus,
)


def filled(client_id="DVS-1"):
    return ExecutionResult(
        accepted=True,
        mode=ExecutionMode.PAPER,
        status=OrderStatus.FILLED,
        symbol="BTCUSDT",
        client_order_id=client_id,
        exchange_order_id="PAPER-1",
        filled_quantity=0.01,
        average_price=100.0,
        fee_paid=0.01,
    )


def test_reconcile_registers_protected_position(tmp_path):
    tracker = PositionTracker(tmp_path/"positions.db")
    result = PositionReconciler(tracker).reconcile_fill(
        execution_result=filled(),
        direction="LONG",
        invalidation=98,
        tp1=103,
        tp2=105,
        require_protective_stop=True,
        protective_stop_attached=True,
    )
    assert result.ok
    assert result.code == ReconciliationCode.OK
    assert result.position.status == TrackedPositionStatus.PROTECTED


def test_missing_stop_fails_reconciliation(tmp_path):
    tracker = PositionTracker(tmp_path/"positions.db")
    result = PositionReconciler(tracker).reconcile_fill(
        execution_result=filled(),
        direction="LONG",
        invalidation=98,
        tp1=103,
        tp2=105,
        require_protective_stop=True,
        protective_stop_attached=False,
    )
    assert not result.ok
    assert result.code == ReconciliationCode.UNPROTECTED_POSITION
    assert tracker.get("DVS-1").status == TrackedPositionStatus.RECONCILIATION_FAILED


def test_position_updates_to_tp2(tmp_path):
    tracker = PositionTracker(tmp_path/"positions.db")
    PositionReconciler(tracker).reconcile_fill(
        execution_result=filled(),
        direction="LONG",
        invalidation=98,
        tp1=103,
        tp2=105,
        require_protective_stop=True,
        protective_stop_attached=True,
    )
    position = tracker.update_mark("DVS-1", 106)
    assert position.status == TrackedPositionStatus.TP2_HIT
    assert position.realized_pnl > 0


def test_duplicate_client_order_is_idempotent(tmp_path):
    tracker = PositionTracker(tmp_path/"positions.db")
    first = tracker.register_fill(
        symbol="BTCUSDT",
        direction="LONG",
        quantity=0.01,
        entry_price=100,
        invalidation=98,
        tp1=103,
        tp2=105,
        client_order_id="DVS-X",
        protective_stop_attached=True,
    )
    second = tracker.register_fill(
        symbol="BTCUSDT",
        direction="LONG",
        quantity=0.01,
        entry_price=100,
        invalidation=98,
        tp1=103,
        tp2=105,
        client_order_id="DVS-X",
        protective_stop_attached=True,
    )
    assert first == second


def test_auto_execution_still_disabled_by_default():
    import json
    raw = json.loads(Path("config.json").read_text(encoding="utf-8"))
    assert raw["auto_paper_execution_enabled"] is False
    assert raw["execution_live_enabled"] is False
