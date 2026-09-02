from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from .circuit_breaker import ExecutionCircuitBreaker
from .dry_run_broker import DryRunBroker
from .execution_audit import ExecutionAudit
from .models import (
    ExecutionIntent,
    ExecutionMode,
    ExecutionResult,
    OrderStatus,
)
from .order_validator import OrderValidator


class ExecutionService:
    """Single controlled entry point for PAPER/TESTNET/LIVE execution."""

    def __init__(
        self,
        mode: ExecutionMode,
        audit: ExecutionAudit,
        validator: OrderValidator | None = None,
        circuit_breaker: ExecutionCircuitBreaker | None = None,
        paper_broker: DryRunBroker | None = None,
        gateway=None,
    ) -> None:
        self.mode = mode
        self.audit = audit
        self.validator = validator or OrderValidator()
        self.circuit_breaker = circuit_breaker or ExecutionCircuitBreaker()
        self.paper_broker = paper_broker or DryRunBroker()
        self.gateway = gateway

    def execute(
        self,
        intent: ExecutionIntent,
        *,
        filters: dict,
        mark_price: float,
        risk_metrics: dict,
        user_confirmed: bool = False,
    ) -> ExecutionResult:
        if not intent.client_order_id:
            intent = replace(
                intent,
                client_order_id=f"DVS-{uuid4().hex[:20]}",
            )

        breaker = self.circuit_breaker.evaluate(**risk_metrics)
        if breaker.blocked and not intent.reduce_only:
            result = ExecutionResult(
                accepted=False,
                mode=self.mode,
                status=OrderStatus.REJECTED,
                symbol=intent.symbol,
                client_order_id=intent.client_order_id,
                message="CIRCUIT_BREAKER:" + "|".join(breaker.reasons),
            )
            self.audit.record(intent, result)
            return result

        validation = self.validator.validate(intent, filters, mark_price)
        if not validation.valid or validation.normalized_intent is None:
            result = ExecutionResult(
                accepted=False,
                mode=self.mode,
                status=OrderStatus.REJECTED,
                symbol=intent.symbol,
                client_order_id=intent.client_order_id,
                message="VALIDATION:" + "|".join(validation.reasons),
            )
            self.audit.record(intent, result)
            return result

        normalized = validation.normalized_intent

        if self.mode in (ExecutionMode.TESTNET, ExecutionMode.LIVE) and not user_confirmed:
            result = ExecutionResult(
                accepted=False,
                mode=self.mode,
                status=OrderStatus.REJECTED,
                symbol=normalized.symbol,
                client_order_id=normalized.client_order_id,
                message="USER_CONFIRMATION_REQUIRED",
            )
            self.audit.record(normalized, result)
            return result

        if self.mode == ExecutionMode.PAPER:
            result = self.paper_broker.submit(normalized, mark_price)
        else:
            if self.gateway is None:
                result = ExecutionResult(
                    accepted=False,
                    mode=self.mode,
                    status=OrderStatus.REJECTED,
                    symbol=normalized.symbol,
                    client_order_id=normalized.client_order_id,
                    message="EXECUTION_GATEWAY_NOT_CONFIGURED",
                )
            else:
                result = self.gateway.submit(normalized)

        self.audit.record(normalized, result)
        return result
