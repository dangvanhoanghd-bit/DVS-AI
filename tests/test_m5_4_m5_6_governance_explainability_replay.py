from dataclasses import replace

import pytest

from dvs_ai.scientific.contracts import ScientificLifecycleState, ScientificReasonCode
from dvs_ai.scientific.explainability import ScientificExplainabilityEngine
from dvs_ai.scientific.governance import DEFAULT_REASON_CODE_REGISTRY, ReasonCodeDefinition, ReasonCodeRegistry, ReasonCategory
from dvs_ai.scientific.ledger import InMemoryLedgerStorage, ScientificLedger
from dvs_ai.scientific.replay import ScientificReplayEngine


def _successful_run():
    ledger = ScientificLedger(InMemoryLedgerStorage())
    run = "run-ok"
    states = [
        ("feature", ScientificLifecycleState.RAW, ScientificLifecycleState.FEATURED),
        ("evidence", ScientificLifecycleState.FEATURED, ScientificLifecycleState.EVIDENCE_READY),
        ("validation", ScientificLifecycleState.EVIDENCE_READY, ScientificLifecycleState.VALIDATED),
        ("certification", ScientificLifecycleState.VALIDATED, ScientificLifecycleState.CERTIFIED),
        ("registry", ScientificLifecycleState.CERTIFIED, ScientificLifecycleState.REGISTERED),
        ("availability", ScientificLifecycleState.REGISTERED, ScientificLifecycleState.AVAILABLE),
    ]
    for stage, before, after in states:
        ledger.append_transition(pipeline_run_id=run, stage=stage, state_before=before, state_after=after, succeeded=True)
    return ledger, run


def test_default_registry_covers_all_contract_codes():
    for code in ScientificReasonCode:
        assert DEFAULT_REASON_CODE_REGISTRY.contains(code.value)
        assert DEFAULT_REASON_CODE_REGISTRY.require(code.value).description


def test_registry_rejects_duplicate_codes():
    definition = ReasonCodeDefinition("X", ReasonCategory.PIPELINE, "x")
    with pytest.raises(ValueError):
        ReasonCodeRegistry([definition, definition])


def test_ledger_rejects_unregistered_reason_code():
    ledger = ScientificLedger(InMemoryLedgerStorage(), strict_reason_codes=True)
    with pytest.raises(ValueError):
        ledger.append_transition(
            pipeline_run_id="bad", stage="x", state_before=ScientificLifecycleState.RAW,
            state_after=ScientificLifecycleState.FAILED, succeeded=False,
            reason_codes=("FREE_TEXT_REASON",),
        )


def test_explainability_builds_auditable_success_narrative():
    ledger, run = _successful_run()
    explanation = ScientificExplainabilityEngine(ledger).explain_run(run)
    assert explanation.succeeded
    assert explanation.integrity_verified
    assert explanation.final_state is ScientificLifecycleState.AVAILABLE
    assert len(explanation.steps) == 6


def test_explainability_maps_failure_reason():
    ledger = ScientificLedger(InMemoryLedgerStorage())
    ledger.append_transition(
        pipeline_run_id="failed", stage="validation",
        state_before=ScientificLifecycleState.EVIDENCE_READY,
        state_after=ScientificLifecycleState.FAILED, succeeded=False,
        reason_codes=(ScientificReasonCode.VALIDATION_FAILED.value,),
    )
    explanation = ScientificExplainabilityEngine(ledger).explain_run("failed")
    assert not explanation.succeeded
    assert explanation.primary_reason_codes == (ScientificReasonCode.VALIDATION_FAILED.value,)
    assert "Validation Failed" in explanation.steps[0].narrative


def test_replay_success():
    ledger, run = _successful_run()
    result = ScientificReplayEngine(ledger).replay(run)
    assert result.valid
    assert result.final_state is ScientificLifecycleState.AVAILABLE
    assert result.events_replayed == 6


def test_replay_detects_tamper():
    storage = InMemoryLedgerStorage()
    ledger = ScientificLedger(storage)
    event = ledger.append_transition(
        pipeline_run_id="tamper", stage="feature",
        state_before=ScientificLifecycleState.RAW,
        state_after=ScientificLifecycleState.FEATURED, succeeded=True,
    )
    storage._events[0] = replace(event, stage="changed")
    result = ScientificReplayEngine(ledger).replay("tamper")
    assert not result.valid
    assert result.reason_codes == (ScientificReasonCode.LEDGER_INTEGRITY_FAILED.value,)
