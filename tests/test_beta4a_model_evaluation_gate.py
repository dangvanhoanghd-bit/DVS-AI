from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3
import threading

import pytest

from dvs_ai.beta4a.contracts import EvaluationMode
from dvs_ai.beta4a.errors import Beta4AGateError
from dvs_ai.beta4a.model_evaluation_gate import ModelEvaluationGate


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 23, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


def make_gate(tmp_path, *, loader=None, clock=None, ttl=timedelta(minutes=15)):
    return ModelEvaluationGate(
        state_db_path=tmp_path / "holdout.sqlite3",
        test_row_loader=loader or (lambda split: [{"row": 1, "split": split}]),
        clock=clock or MutableClock(),
        claim_ttl=ttl,
    )


def test_first_evaluation_is_qualifying_and_second_is_historical(tmp_path):
    gate = make_gate(tmp_path)
    first = gate.evaluate(
        model_slot_id="model-a", split_sha256="split-a", evaluator=lambda _m, rows: {"loss": 0.1}
    )
    second = gate.evaluate(
        model_slot_id="model-b", split_sha256="split-a", evaluator=lambda _m, rows: {"loss": 0.2}
    )

    assert first.evaluation_mode is EvaluationMode.QUALIFYING_HOLDOUT_EVALUATION
    assert first.qualifying is True
    assert first.holdout_consumption_record_sha256
    assert second.evaluation_mode is EvaluationMode.HISTORICAL_BENCHMARK_EVALUATION
    assert second.qualifying is False
    assert second.historical_benchmark_only is True

    audit = gate.audit_snapshot("split-a")
    assert audit["state"]["test_status"] == "CONSUMED"
    assert len(audit["claims"]) == 1
    assert audit["claims"][0]["terminal_outcome"] == "CLAIM_COMPLETED"
    assert audit["consumption"]["model_slot_id"] == "model-a"


def test_access_is_marked_before_loader_receives_test_rows(tmp_path):
    holder = {}

    def loader(split_sha256):
        audit = holder["gate"].audit_snapshot(split_sha256)
        assert audit["state"]["test_status"] == "CONSUMED"
        assert audit["state"]["consumed_reason"] == "HOLDOUT_ACCESS_STARTED"
        assert audit["claims"][0]["access_started_at"] is not None
        return [1]

    gate = make_gate(tmp_path, loader=loader)
    holder["gate"] = gate
    report = gate.evaluate(model_slot_id="m", split_sha256="s", evaluator=lambda *_: {"x": 1.0})
    assert report.qualifying


def test_failure_after_access_consumes_fail_closed(tmp_path):
    calls = {"count": 0}

    def loader(_split):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")
        return [1]

    gate = make_gate(tmp_path, loader=loader)
    with pytest.raises(RuntimeError, match="boom"):
        gate.evaluate(model_slot_id="m1", split_sha256="s1", evaluator=lambda *_: {})

    audit = gate.audit_snapshot("s1")
    assert audit["state"]["test_status"] == "CONSUMED"
    assert audit["state"]["consumed_reason"] == "HOLDOUT_CONSUMED_WITHOUT_COMPLETED_EVALUATION"
    assert audit["claims"][0]["terminal_outcome"] == "CLAIM_ABORTED_AFTER_ACCESS"

    historical = gate.evaluate(model_slot_id="m2", split_sha256="s1", evaluator=lambda *_: {"loss": 1.0})
    assert historical.historical_benchmark_only


def test_atomic_claim_allows_only_one_qualifying_evaluator(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    results = []
    errors = []

    def blocking_loader(_split):
        entered.set()
        release.wait(timeout=5)
        return [1]

    db_path = tmp_path / "race.sqlite3"
    gate_a = ModelEvaluationGate(state_db_path=db_path, test_row_loader=blocking_loader)
    gate_b = ModelEvaluationGate(state_db_path=db_path, test_row_loader=lambda _s: [1])

    def run_a():
        try:
            results.append(gate_a.evaluate(model_slot_id="a", split_sha256="race", evaluator=lambda *_: {"v": 1.0}))
        except Exception as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)

    thread = threading.Thread(target=run_a)
    thread.start()
    assert entered.wait(timeout=5)

    # ACCESS_STARTED is already persisted, therefore the second evaluator is historical.
    second = gate_b.evaluate(model_slot_id="b", split_sha256="race", evaluator=lambda *_: {"v": 2.0})
    release.set()
    thread.join(timeout=5)

    assert not errors
    assert results[0].qualifying is True
    assert second.qualifying is False
    audit = gate_a.audit_snapshot("race")
    assert sum(1 for report in audit["reports"] if report["qualifying"] == 1) == 1


def test_unexpired_claim_is_operationally_refused(tmp_path):
    clock = MutableClock()
    gate = make_gate(tmp_path, clock=clock)
    claim_id = gate._claim_qualifying(split_sha256="s", model_slot_id="m1")
    assert claim_id
    with pytest.raises(Beta4AGateError) as exc:
        gate._claim_qualifying(split_sha256="s", model_slot_id="m2")
    assert exc.value.code == "HOLDOUT_QUALIFYING_CLAIM_ALREADY_HELD"


def test_expired_unaccessed_claim_is_recovered_with_audit_event(tmp_path):
    clock = MutableClock()
    gate = make_gate(tmp_path, clock=clock, ttl=timedelta(seconds=10))
    claim_id = gate._claim_qualifying(split_sha256="s", model_slot_id="m1")
    clock.advance(timedelta(seconds=11))

    events = gate.recover_expired_claims()
    assert len(events) == 1
    assert events[0].claim_id == claim_id
    assert events[0].code == "EXPIRED_CLAIM_RECOVERED"

    audit = gate.audit_snapshot("s")
    assert audit["claims"][0]["terminal_outcome"] == "CLAIM_RECOVERED"
    # The split remains eligible because access never started.
    report = gate.evaluate(model_slot_id="m2", split_sha256="s", evaluator=lambda *_: {"ok": 1.0})
    assert report.qualifying


def test_claim_history_has_exactly_one_terminal_outcome_per_claim(tmp_path):
    gate = make_gate(tmp_path)
    gate.evaluate(model_slot_id="m", split_sha256="s", evaluator=lambda *_: {"ok": 1.0})
    audit = gate.audit_snapshot("s")
    assert all(row["terminal_outcome"] is not None for row in audit["claims"])
