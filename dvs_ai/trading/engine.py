from __future__ import annotations
from datetime import datetime, timezone
from uuid import uuid4
from dvs_ai.risk import RiskManager
from dvs_ai.scientific.decision import DecisionAction, ScientificDecision
from .models import ClosedTrade, OrderStatus, PaperOrder, Position, PositionSide
from .portfolio import PaperPortfolio

class PaperTradingEngine:
    """Deterministic paper execution only. It has no exchange/network adapter."""
    def __init__(self, portfolio: PaperPortfolio | None = None, risk_manager: RiskManager | None = None,
                 *, fee_rate: float = 0.0004) -> None:
        if fee_rate < 0:
            raise ValueError("fee_rate cannot be negative")
        self.portfolio = portfolio or PaperPortfolio()
        self.risk_manager = risk_manager or RiskManager()
        self.fee_rate = float(fee_rate)
        self.orders: list[PaperOrder] = []

    def execute_decision(self, decision: ScientificDecision, *, price: float, quantity: float,
                         at: datetime | None = None) -> PaperOrder:
        at = at or datetime.now(timezone.utc)
        if not decision.authorized or decision.final_action not in (DecisionAction.BUY, DecisionAction.SELL):
            return self._reject(decision, price, "PAPER_DECISION_NOT_EXECUTABLE", at=at)
        if decision.symbol in self.portfolio.positions:
            return self._reject(decision, price, "PAPER_POSITION_ALREADY_OPEN", at=at)
        exposure = sum(abs(p.quantity * p.entry_price) for p in self.portfolio.positions.values())
        risk = self.risk_manager.evaluate(price=price, requested_quantity=quantity,
            current_exposure=exposure, equity=self.portfolio.equity(), drawdown=self.portfolio.drawdown())
        if not risk.allowed:
            return self._reject(decision, price, *risk.reason_codes, at=at)
        side = PositionSide.LONG if decision.final_action is DecisionAction.BUY else PositionSide.SHORT
        fee = price * risk.approved_quantity * self.fee_rate
        self.portfolio.cash_balance -= fee
        self.portfolio.positions[decision.symbol] = Position(decision.symbol, side, risk.approved_quantity,
            float(price), at, decision.decision_id, fee)
        order = PaperOrder(f"ord-{uuid4().hex}", decision.decision_id, decision.symbol, side,
                           risk.approved_quantity, float(price), fee, OrderStatus.FILLED, risk.reason_codes, at)
        self.orders.append(order)
        return order

    def close_position(self, symbol: str, *, price: float, at: datetime | None = None) -> ClosedTrade:
        symbol = symbol.upper().strip()
        if symbol not in self.portfolio.positions:
            raise KeyError(f"no open position for {symbol}")
        at = at or datetime.now(timezone.utc)
        pos = self.portfolio.positions.pop(symbol)
        gross = pos.unrealized_pnl(price)
        exit_fee = price * pos.quantity * self.fee_rate
        net = gross - pos.entry_fee - exit_fee
        self.portfolio.cash_balance += gross - exit_fee
        trade = ClosedTrade(f"trd-{uuid4().hex}", symbol, pos.side, pos.quantity, pos.entry_price,
            float(price), gross, pos.entry_fee + exit_fee, net, pos.opened_at, at, pos.decision_id)
        self.portfolio.closed_trades.append(trade)
        self.risk_manager.record_realized_pnl(net, at=at)
        return trade

    def _reject(self, decision: ScientificDecision, price: float, *codes: str, at: datetime) -> PaperOrder:
        side = PositionSide.LONG if decision.final_action is DecisionAction.BUY else PositionSide.SHORT
        order = PaperOrder(f"ord-{uuid4().hex}", decision.decision_id, decision.symbol, side, 0.0,
                           float(price), 0.0, OrderStatus.REJECTED, tuple(codes), at)
        self.orders.append(order)
        return order
