from __future__ import annotations

import sqlite3

from dvs_ai.execution import (
    ExecutionAudit,
    ExecutionCircuitBreaker,
    ExecutionIntent,
    ExecutionMode,
    ExecutionService,
    OrderSide,
    OrderType,
    OrderValidator,
)


def intent(**kwargs):
    data = dict(
        symbol="BTC/USDT:USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.01,
        leverage=5,
    )
    data.update(kwargs)
    return ExecutionIntent(**data)


def risk(**kwargs):
    data = dict(
        daily_pnl=0.0,
        consecutive_losses=0,
        open_exposure=0.0,
        daily_trades=0,
        api_error_rate=0.0,
        market_data_age_seconds=1.0,
    )
    data.update(kwargs)
    return data


def filters():
    return {
        "step_size": 0.001,
        "tick_size": 0.1,
        "min_qty": 0.001,
        "min_notional": 5.0,
        "max_leverage": 20,
    }


def test_validator_normalizes_quantity():
    result = OrderValidator().validate(
        intent(quantity=0.0109),
        filters(),
        mark_price=60000,
    )
    assert result.valid
    assert result.normalized_intent.quantity == 0.01


def test_circuit_breaker_blocks_new_risk():
    breaker = ExecutionCircuitBreaker(daily_loss_limit=50)
    state = breaker.evaluate(**risk(daily_pnl=-60))
    assert state.blocked
    assert "DAILY_LOSS_LIMIT" in state.reasons


def test_paper_execution_is_audited(tmp_path):
    audit = ExecutionAudit(tmp_path / "audit.db")
    service = ExecutionService(
        mode=ExecutionMode.PAPER,
        audit=audit,
    )
    result = service.execute(
        intent(),
        filters=filters(),
        mark_price=60000,
        risk_metrics=risk(),
    )
    assert result.accepted
    assert result.mode == ExecutionMode.PAPER
    with sqlite3.connect(tmp_path / "audit.db") as con:
        count = con.execute(
            "SELECT COUNT(*) FROM execution_audit"
        ).fetchone()[0]
    assert count == 1


def test_testnet_requires_user_confirmation(tmp_path):
    audit = ExecutionAudit(tmp_path / "audit.db")
    service = ExecutionService(
        mode=ExecutionMode.TESTNET,
        audit=audit,
        gateway=None,
    )
    result = service.execute(
        intent(),
        filters=filters(),
        mark_price=60000,
        risk_metrics=risk(),
        user_confirmed=False,
    )
    assert not result.accepted
    assert result.message == "USER_CONFIRMATION_REQUIRED"


def test_reduce_only_allowed_during_breaker(tmp_path):
    audit = ExecutionAudit(tmp_path / "audit.db")
    service = ExecutionService(
        mode=ExecutionMode.PAPER,
        audit=audit,
        circuit_breaker=ExecutionCircuitBreaker(
            daily_loss_limit=10,
        ),
    )
    result = service.execute(
        intent(reduce_only=True),
        filters=filters(),
        mark_price=60000,
        risk_metrics=risk(daily_pnl=-100),
    )
    assert result.accepted


def test_live_disabled_by_default_in_config():
    import json
    from pathlib import Path

    raw = json.loads(Path("config.json").read_text(encoding="utf-8"))
    assert raw["execution_mode"] == "PAPER"
    assert raw["execution_live_enabled"] is False
