from pathlib import Path

from dvs_ai.services.quantum_validation import (
    AttemptLedger, HoldoutManager, ValidationOrchestrator,
    ValidationRequest, ValidationState, WalkForwardFold,
)


def fold() -> WalkForwardFold:
    return WalkForwardFold(
        fold_id="F1",
        train_start="2026-01-01T00:00:00+00:00",
        train_end="2026-01-31T00:00:00+00:00",
        validation_start="2026-02-02T00:00:00+00:00",
        validation_end="2026-02-28T00:00:00+00:00",
        holdout_start="2026-03-02T00:00:00+00:00",
        holdout_end="2026-03-31T00:00:00+00:00",
        purge_seconds=86400,
        embargo_seconds=86400,
    )


def request(**overrides):
    values = dict(
        study_id="STUDY-1", policy_scope_id="QPS-1", policy_scope_hash="scope-hash",
        decision_engine_checksum="engine-hash", replay_state="VERIFIED",
        effective_n=120.0, minimum_effective_n=100.0,
        split_method="ANCHORED_WALK_FORWARD", folds=(fold(),), holdout_id="H-1",
    )
    values.update(overrides)
    return ValidationRequest(**values)


def setup(tmp_path: Path):
    hm = HoldoutManager(tmp_path / "holdout.jsonl")
    hm.lock("H-1", "2026-03-02T00:00:00+00:00", "QPS-1")
    ledger = AttemptLedger(tmp_path / "attempts.jsonl")
    return hm, ledger, ValidationOrchestrator(hm, ledger)


def test_valid_protocol_passes_and_consumes_holdout(tmp_path):
    hm, ledger, service = setup(tmp_path)
    result = service.validate(request())
    assert result.state == ValidationState.PASS
    assert hm.status("H-1")["consumed"] is True
    assert ledger.verify()
    assert result.shadow_apply_allowed is False


def test_random_split_is_blocked(tmp_path):
    _, _, service = setup(tmp_path)
    result = service.validate(request(split_method="RANDOM_SPLIT"))
    assert result.state == ValidationState.BLOCK
    assert "RANDOM_SPLIT_FORBIDDEN" in result.violations


def test_low_effective_n_is_blocked(tmp_path):
    _, _, service = setup(tmp_path)
    result = service.validate(request(effective_n=99.0))
    assert result.state == ValidationState.BLOCK
    assert "EFFECTIVE_N_BELOW_MINIMUM" in result.violations


def test_consumed_holdout_cannot_be_reused(tmp_path):
    _, _, service = setup(tmp_path)
    assert service.validate(request()).state == ValidationState.PASS
    second = service.validate(request(study_id="STUDY-2"))
    assert second.state == ValidationState.BLOCK
    assert "HOLDOUT_ALREADY_CONSUMED" in second.violations


def test_bad_replay_is_blocked(tmp_path):
    _, _, service = setup(tmp_path)
    result = service.validate(request(replay_state="INVALID_REPLAY"))
    assert result.state == ValidationState.BLOCK
    assert "REPLAY_NOT_VERIFIED" in result.violations


def test_attempt_ledger_tamper_is_detected(tmp_path):
    _, ledger, service = setup(tmp_path)
    service.validate(request(effective_n=1.0))
    text = ledger.path.read_text(encoding="utf-8")
    ledger.path.write_text(text.replace('"candidate_count": 1', '"candidate_count": 9'), encoding="utf-8")
    assert ledger.verify() is False
