from __future__ import annotations

from dataclasses import replace

import pytest

from dvs_ai.services.beta3_learning_foundation import (
    FeatureStoreProjector,
    LearningCandidateBuilder,
    PolicyIdentity,
    canonical_sha256,
    classify_dataset_readiness,
    lineage_record,
)
from dvs_ai.services.unified_outcome_service import UnifiedOutcomeRecord


POLICY = PolicyIdentity(
    decision_engine_checksum="00c1db1a1684896b3c06fbf4cfaeea094337f1841dc2e3cb9dfdf9013252dbce",
    policy_scope_id="qg13:decision-core:v1",
    policy_scope_hash="scope-hash-v1",
)


def record(**changes):
    base = UnifiedOutcomeRecord(
        unified_id="u1", source_identities=("candidate_outcomes:c1",), candidate_id="c1",
        paper_trade_id=None, symbol="BTCUSDT", direction="LONG", outcome_status="WIN",
        identity_status="EXPLICIT_SOURCE_IDENTITY", eligibility_status="UNIFIED_ELIGIBLE",
        eligibility_reason="EXPLICIT_SOURCE_IDENTITY", feature_snapshot_hash="placeholder",
        realized_r=1.5, evidence_snapshot={"cmf": 0.1, "rsi": 58.0}, resolution_source="AUTOMATIC",
    )
    return replace(base, **changes)


class Source:
    def __init__(self, rows): self.rows = rows
    def learning_ready(self): return list(self.rows)


@pytest.mark.parametrize("count,state,allowed", [
    (0,"UNOBSERVABLE",False),(29,"UNOBSERVABLE",False),(30,"DESCRIPTIVE_ONLY",True),
    (99,"DESCRIPTIVE_ONLY",True),(100,"RESEARCH_CANDIDATE_ONLY",True),
    (299,"RESEARCH_CANDIDATE_ONLY",True),(300,"VALIDATION_REVIEW_ELIGIBLE",True),
    (499,"VALIDATION_REVIEW_ELIGIBLE",True),(500,"BURN_IN_COMPLETE",True),
])
def test_reuses_frozen_burn_in_scale(count, state, allowed):
    got = classify_dataset_readiness(count)
    assert (got.state, got.dataset_emission_allowed) == (state, allowed)


def test_candidate_builder_reads_learning_ready_contract_and_requires_snapshot():
    good = record(feature_snapshot_hash="h1")
    bad = record(unified_id="u2", candidate_id="c2", feature_snapshot_hash=None)
    result = LearningCandidateBuilder(Source([good, bad]), POLICY).build()
    assert [c.unified_id for c in result.candidates] == ["u1"]
    assert result.exclusions == ({"unified_id": "u2", "reason": "FEATURE_SNAPSHOT_HASH_MISSING"},)


def test_auto_resolved_record_does_not_require_human_review():
    result = LearningCandidateBuilder(Source([record(feature_snapshot_hash="h1", review_action=None)]), POLICY).build()
    assert len(result.candidates) == 1


def test_excluded_review_never_enters_learning():
    excluded = record(feature_snapshot_hash="h1", review_action="EXCLUDE")
    result = LearningCandidateBuilder(Source([excluded]), POLICY).build()
    assert not result.candidates
    assert result.exclusions[0]["reason"] == "EXCLUDED_BY_REVIEW"


def test_feature_projector_uses_existing_snapshot_hash_and_complete_policy_identity():
    evidence = {"cmf": 0.12, "rsi": 61.0, "regime": "TREND"}
    h = canonical_sha256(evidence)
    candidate = LearningCandidateBuilder(Source([record(feature_snapshot_hash=h, evidence_snapshot=evidence)]), POLICY).build().candidates[0]
    projected = FeatureStoreProjector("beta3a.feature.v1", "extractor-sha").project([candidate], {"u1": evidence})
    assert not projected.exclusions
    assert {r.feature_name for r in projected.rows} == {"cmf", "rsi", "regime"}
    assert all(r.policy_scope_hash == POLICY.policy_scope_hash for r in projected.rows)
    assert all(r.decision_engine_checksum == POLICY.decision_engine_checksum for r in projected.rows)


def test_feature_projector_rejects_snapshot_hash_mismatch():
    candidate = LearningCandidateBuilder(Source([record(feature_snapshot_hash="wrong")]), POLICY).build().candidates[0]
    projected = FeatureStoreProjector("v1", "sha").project([candidate], {"u1": {"cmf": 0.1}})
    assert not projected.rows
    assert projected.exclusions[0]["reason"] == "FEATURE_SNAPSHOT_HASH_MISMATCH"


def test_lineage_reaches_source_identity_snapshot_and_policy():
    evidence = {"cmf": 0.2}
    h = canonical_sha256(evidence)
    candidate = LearningCandidateBuilder(Source([record(feature_snapshot_hash=h)]), POLICY).build().candidates[0]
    row = FeatureStoreProjector("v1", "sha").project([candidate], {"u1": evidence}).rows[0]
    lineage = lineage_record(candidate, row)
    assert lineage["unified_id"] == "u1"
    assert lineage["candidate_id"] == "c1"
    assert lineage["feature_snapshot_hash"] == h
    assert lineage["policy_scope_id"] == POLICY.policy_scope_id


def test_module_has_no_sqlite_dependency():
    import inspect
    import dvs_ai.services.beta3_learning_foundation as module
    source = inspect.getsource(module)
    assert "import sqlite3" not in source
    assert "FROM paper_trades" not in source


def test_r3_compatibility_lineage_propagates_temporal_fields_without_recomputation():
    evidence = {"cmf": 0.2}
    timestamp = "2026-07-23T03:45:00Z"
    h = canonical_sha256(evidence)
    candidate = LearningCandidateBuilder(
        Source([record(feature_snapshot_hash=h, setup_time=timestamp)]), POLICY
    ).build().candidates[0]
    row = FeatureStoreProjector("v1", "sha").project([candidate], {"u1": evidence}).rows[0]
    lineage = lineage_record(candidate, row)
    assert candidate.first_eligible_evaluation_timestamp == timestamp
    assert candidate.snapshot_timestamp == timestamp
    assert lineage["first_eligible_evaluation_timestamp"] == timestamp
    assert lineage["snapshot_timestamp"] == timestamp


def test_r3_compatibility_temporal_fields_remain_null_when_source_contract_has_no_timestamp():
    evidence = {"cmf": 0.2}
    h = canonical_sha256(evidence)
    candidate = LearningCandidateBuilder(
        Source([record(feature_snapshot_hash=h, setup_time=None)]), POLICY
    ).build().candidates[0]
    row = FeatureStoreProjector("v1", "sha").project([candidate], {"u1": evidence}).rows[0]
    lineage = lineage_record(candidate, row)
    assert lineage["first_eligible_evaluation_timestamp"] is None
    assert lineage["snapshot_timestamp"] is None
