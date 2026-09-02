from __future__ import annotations

import random
import time

from .models import (
    ExecutionIntent,
    ExecutionMode,
    ExecutionResult,
    OrderStatus,
)


class DryRunBroker:
    """Deterministic-enough PAPER broker with fees and slippage."""

    def __init__(
        self,
        slippage_rate: float = 0.0005,
        fee_rate: float = 0.0005,
        seed: int = 7,
    ) -> None:
        self.slippage_rate = max(0.0, float(slippage_rate))
        self.fee_rate = max(0.0, float(fee_rate))
        self._rng = random.Random(seed)

    def submit(
        self,
        intent: ExecutionIntent,
        mark_price: float,
    ) -> ExecutionResult:
        direction = 1.0 if intent.side.value == "BUY" else -1.0
        randomized = self._rng.gauss(self.slippage_rate, self.slippage_rate*0.25)
        fill_price = max(0.0, mark_price*(1.0+direction*max(0.0, randomized)))
        notional = fill_price*intent.quantity
        fee = notional*self.fee_rate
        exchange_id = f"PAPER-{int(time.time()*1000)}"
        return ExecutionResult(
            accepted=True,
            mode=ExecutionMode.PAPER,
            status=OrderStatus.FILLED,
            symbol=intent.symbol,
            client_order_id=intent.client_order_id,
            exchange_order_id=exchange_id,
            filled_quantity=intent.quantity,
            average_price=fill_price,
            fee_paid=fee,
            message="PAPER_FILL",
            raw={"reduce_only": intent.reduce_only},
        )
