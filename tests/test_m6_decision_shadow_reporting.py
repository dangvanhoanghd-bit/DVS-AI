from datetime import datetime, timezone
from dvs_ai.scientific.contracts import ScientificLifecycleState
from dvs_ai.scientific.ledger import InMemoryLedgerStorage, ScientificLedger
from dvs_ai.scientific.decision import DecisionAction, DecisionAdapter, DecisionRequest
from dvs_ai.scientific.shadow import InMemoryShadowStorage, ShadowHorizon, ShadowValidator
from dvs_ai.scientific.reporting import ScientificDecisionReportBuilder

def available_ledger(run_id="run-1"):
    ledger = ScientificLedger(InMemoryLedgerStorage())
    states = [ScientificLifecycleState.RAW, ScientificLifecycleState.FEATURED,
              ScientificLifecycleState.EVIDENCE_READY, ScientificLifecycleState.VALIDATED,
              ScientificLifecycleState.CERTIFIED, ScientificLifecycleState.REGISTERED,
              ScientificLifecycleState.AVAILABLE]
    for i in range(len(states)-1):
        ledger.append_transition(pipeline_run_id=run_id, stage=f"s{i}", state_before=states[i],
                                 state_after=states[i+1], succeeded=True)
    return ledger

def test_authorizes_only_available_verified_run():
    ledger = available_ledger()
    decision = DecisionAdapter(ledger).authorize(DecisionRequest("run-1", "btcusdt", DecisionAction.BUY, .8, "m1"))
    assert decision.authorized and decision.final_action is DecisionAction.BUY and decision.symbol == "BTCUSDT"

def test_low_confidence_fails_closed():
    ledger = available_ledger()
    decision = DecisionAdapter(ledger, minimum_confidence=.7).authorize(DecisionRequest("run-1", "ETHUSDT", DecisionAction.SELL, .4, "m1"))
    assert not decision.authorized and decision.final_action is DecisionAction.NO_ACTION
    assert "DECISION_CONFIDENCE_TOO_LOW" in decision.reason_codes

def test_unavailable_run_fails_closed():
    ledger = ScientificLedger(InMemoryLedgerStorage())
    decision = DecisionAdapter(ledger).authorize(DecisionRequest("missing", "ETHUSDT", DecisionAction.BUY, .9, "m1"))
    assert not decision.authorized

def test_shadow_long_and_short_returns_and_metrics():
    ledger = available_ledger()
    adapter = DecisionAdapter(ledger)
    long_d = adapter.authorize(DecisionRequest("run-1", "BTCUSDT", DecisionAction.BUY, .9, "m1"))
    short_d = adapter.authorize(DecisionRequest("run-1", "BTCUSDT", DecisionAction.SELL, .9, "m1"))
    validator = ShadowValidator(InMemoryShadowStorage())
    now = datetime.now(timezone.utc)
    assert validator.observe(long_d, horizon=ShadowHorizon.M15, observed_at=now, entry_price=100, exit_price=110).correct
    assert validator.observe(short_d, horizon=ShadowHorizon.H1, observed_at=now, entry_price=100, exit_price=90).correct
    metrics = validator.metrics()
    assert metrics.observations == 2 and metrics.win_rate == 1.0

def test_report_combines_lifecycle_and_decision():
    ledger = available_ledger()
    decision = DecisionAdapter(ledger).authorize(DecisionRequest("run-1", "BTCUSDT", DecisionAction.HOLD, .8, "m1"))
    report = ScientificDecisionReportBuilder(ledger).build(decision)
    assert report.lifecycle_integrity_verified
    assert report.lifecycle_event_count == 6
    assert report.decision.decision_id.startswith("dec-")
