from dataclasses import replace
import json

from dvs_ai.scientific.contracts import ScientificLifecycleState
from dvs_ai.scientific.ledger import InMemoryLedgerStorage, JsonLinesLedgerStorage, ScientificLedger


def test_hash_chain_and_replay():
    ledger = ScientificLedger(InMemoryLedgerStorage())
    ledger.append_transition(pipeline_run_id="r1", stage="feature", state_before=ScientificLifecycleState.RAW, state_after=ScientificLifecycleState.FEATURED, succeeded=True)
    ledger.append_transition(pipeline_run_id="r1", stage="evidence", state_before=ScientificLifecycleState.FEATURED, state_after=ScientificLifecycleState.EVIDENCE_READY, succeeded=True)
    events = ledger.read_run("r1")
    assert len(events) == 2
    assert events[1].previous_hash == events[0].event_hash
    assert ledger.verify_run("r1")


def test_reason_codes_are_preserved():
    ledger = ScientificLedger(InMemoryLedgerStorage())
    event = ledger.append_transition(pipeline_run_id="r2", stage="validation", state_before=ScientificLifecycleState.EVIDENCE_READY, state_after=ScientificLifecycleState.FAILED, succeeded=False, reason_codes=("A", "A", "B"))
    assert event.reason_codes == ("A", "B")


def test_runs_are_isolated():
    ledger = ScientificLedger(InMemoryLedgerStorage())
    for run in ("a", "b"):
        ledger.append_transition(pipeline_run_id=run, stage="x", state_before=ScientificLifecycleState.RAW, state_after=ScientificLifecycleState.FEATURED, succeeded=True)
    assert len(ledger.read_run("a")) == 1
    assert len(ledger.read_run("b")) == 1


def test_tamper_is_detected():
    storage = InMemoryLedgerStorage()
    ledger = ScientificLedger(storage)
    event = ledger.append_transition(pipeline_run_id="r3", stage="x", state_before=ScientificLifecycleState.RAW, state_after=ScientificLifecycleState.FEATURED, succeeded=True)
    storage._events[0] = replace(event, stage="tampered")
    assert not ledger.verify_run("r3")


def test_jsonl_is_append_only_and_round_trips(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = ScientificLedger(JsonLinesLedgerStorage(path))
    ledger.append_transition(pipeline_run_id="r4", stage="x", state_before=ScientificLifecycleState.RAW, state_after=ScientificLifecycleState.FEATURED, succeeded=True)
    size1 = path.stat().st_size
    ledger.append_transition(pipeline_run_id="r4", stage="y", state_before=ScientificLifecycleState.FEATURED, state_after=ScientificLifecycleState.EVIDENCE_READY, succeeded=True)
    assert path.stat().st_size > size1
    assert ledger.verify_run("r4")
    assert len(path.read_text().splitlines()) == 2
