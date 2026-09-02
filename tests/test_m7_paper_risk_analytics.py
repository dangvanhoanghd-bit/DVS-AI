from datetime import datetime, timezone
from dvs_ai.analytics import PerformanceAnalyzer
from dvs_ai.risk import RiskLimits, RiskManager
from dvs_ai.scientific.decision import DecisionAction, ScientificDecision
from dvs_ai.trading import OrderStatus, PaperPortfolio, PaperTradingEngine, PositionSide


def decision(action=DecisionAction.BUY, *, authorized=True, symbol="BTCUSDT", confidence=.9):
    return ScientificDecision(
        decision_id="dec-1", pipeline_run_id="run-1", symbol=symbol,
        proposed_action=action, final_action=action if authorized else DecisionAction.NO_ACTION,
        confidence=confidence, authorized=authorized, reason_codes=(), model_id="m1",
        created_at=datetime.now(timezone.utc),
    )


def test_long_paper_trade_pnl_and_fees():
    engine = PaperTradingEngine(PaperPortfolio(10_000), fee_rate=.001)
    order = engine.execute_decision(decision(), price=100, quantity=10)
    assert order.status is OrderStatus.FILLED
    assert order.side is PositionSide.LONG
    trade = engine.close_position("BTCUSDT", price=110)
    assert trade.gross_pnl == 100
    assert trade.fees == 2.1
    assert round(trade.net_pnl, 6) == 97.9
    assert round(engine.portfolio.cash_balance, 6) == 10097.9


def test_short_paper_trade_is_symmetric():
    engine = PaperTradingEngine(PaperPortfolio(10_000), fee_rate=0)
    order = engine.execute_decision(decision(DecisionAction.SELL), price=100, quantity=2)
    assert order.side is PositionSide.SHORT
    trade = engine.close_position("BTCUSDT", price=90)
    assert trade.net_pnl == 20


def test_unauthorized_decision_rejected_fail_closed():
    engine = PaperTradingEngine()
    order = engine.execute_decision(decision(authorized=False), price=100, quantity=1)
    assert order.status is OrderStatus.REJECTED
    assert "PAPER_DECISION_NOT_EXECUTABLE" in order.reason_codes
    assert not engine.portfolio.positions


def test_risk_reduces_quantity_to_position_notional_limit():
    risk = RiskManager(RiskLimits(max_position_notional=500, max_total_exposure=1000,
                                  max_drawdown=.2, max_daily_loss=100, max_leverage=1))
    engine = PaperTradingEngine(PaperPortfolio(10_000), risk, fee_rate=0)
    order = engine.execute_decision(decision(), price=100, quantity=10)
    assert order.status is OrderStatus.FILLED
    assert order.quantity == 5
    assert "RISK_QUANTITY_REDUCED" in order.reason_codes


def test_kill_switch_blocks_execution():
    risk = RiskManager()
    risk.enable_kill_switch()
    engine = PaperTradingEngine(risk_manager=risk)
    order = engine.execute_decision(decision(), price=100, quantity=1)
    assert order.status is OrderStatus.REJECTED
    assert "RISK_KILL_SWITCH_ENABLED" in order.reason_codes


def test_daily_loss_limit_blocks_new_position():
    risk = RiskManager(RiskLimits(max_daily_loss=50))
    risk.record_realized_pnl(-60)
    engine = PaperTradingEngine(risk_manager=risk)
    order = engine.execute_decision(decision(), price=100, quantity=1)
    assert order.status is OrderStatus.REJECTED
    assert "RISK_DAILY_LOSS_LIMIT_EXCEEDED" in order.reason_codes


def test_duplicate_symbol_position_is_rejected():
    engine = PaperTradingEngine(fee_rate=0)
    engine.execute_decision(decision(), price=100, quantity=1)
    second = engine.execute_decision(decision(), price=101, quantity=1)
    assert second.status is OrderStatus.REJECTED
    assert "PAPER_POSITION_ALREADY_OPEN" in second.reason_codes


def test_portfolio_equity_and_drawdown():
    engine = PaperTradingEngine(PaperPortfolio(1000), fee_rate=0)
    engine.execute_decision(decision(), price=100, quantity=5)
    assert engine.portfolio.equity({"BTCUSDT": 120}) == 1100
    assert round(engine.portfolio.drawdown({"BTCUSDT": 80}), 6) == round(200/1100, 6)


def test_performance_analytics_from_closed_trades():
    engine = PaperTradingEngine(PaperPortfolio(10_000), fee_rate=0)
    engine.execute_decision(decision(), price=100, quantity=1)
    engine.close_position("BTCUSDT", price=110)
    engine.execute_decision(decision(DecisionAction.SELL, symbol="ETHUSDT"), price=100, quantity=1)
    engine.close_position("ETHUSDT", price=105)
    report = PerformanceAnalyzer.analyze(engine.portfolio.closed_trades)
    assert report.trades == 2
    assert report.wins == 1 and report.losses == 1
    assert report.win_rate == .5
    assert report.profit_factor == 2
    assert report.net_pnl == 5
