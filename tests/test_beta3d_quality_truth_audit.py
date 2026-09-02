from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dvs_ai.services.beta3_cross_bundle import BundleRegistry, PromotionRecommender
from dvs_ai.services.beta3_dataset_bundle import DatasetBuilder
from dvs_ai.services.beta3_learning_foundation import (
    FeatureStoreProjector,
    LearningCandidateBuilder,
    PolicyIdentity,
    canonical_sha256,
)
from dvs_ai.services.unified_outcome_service import UnifiedOutcomeRecord

ENGINE_SHA = "00c1db1a1684896b3c06fbf4cfaeea094337f1841dc2e3cb9dfdf9013252dbce"
POLICY = PolicyIdentity(ENGINE_SHA, "qg13:decision-core:v1", "scope-hash-v1")
CLOCK = lambda: datetime(2026, 7, 23, 4, 0, tzinfo=timezone.utc)


class Source:
    def __init__(self, rows):
        self.rows = rows

    def learning_ready(self):
        return list(self.rows)


def governed(count: int):
    records = []
    for index in range(count):
        evidence = {"cmf": 0.1 + index / 1000, "rsi": 50.0 + index % 20, "regime": "TREND"}
        records.append(
            UnifiedOutcomeRecord(
                unified_id=f"u{index}",
                source_identities=(f"candidate_outcomes:c{index}",),
                candidate_id=f"c{index}",
                paper_trade_id=None,
                symbol="BTCUSDT",
                direction="LONG",
                outcome_status="WIN" if index % 2 == 0 else "LOSS",
                identity_status="EXPLICIT_SOURCE_IDENTITY",
                eligibility_status="UNIFIED_ELIGIBLE",
                eligibility_reason="EXPLICIT_SOURCE_IDENTITY",
                feature_snapshot_hash=canonical_sha256(evidence),
                realized_r=1.0 if index % 2 == 0 else -1.0,
                evidence_snapshot=evidence,
                resolution_source="AUTOMATIC",
            )
        )
    candidates = LearningCandidateBuilder(Source(records), POLICY).build().candidates
    evidence_by_id = {record.unified_id: record.evidence_snapshot for record in records}
    rows = FeatureStoreProjector("beta3a.feature.v1", "extractor-sha-v1").project(
        candidates, evidence_by_id
    ).rows
    return candidates, rows


def exclusions(count: int):
    return [{"unified_id": f"excluded-{index}", "reason": "NO_SNAPSHOT"} for index in range(count)]


def test_registry_reads_beta3b_quality_report_as_single_source_of_truth(tmp_path):
    candidates, rows = governed(30)
    built = DatasetBuilder(tmp_path, clock=CLOCK).build(
        candidates, rows, exclusions=exclusions(10)
    )
    bundle = Path(built.bundle_path)
    report = json.loads((bundle / "quality_report.json").read_text(encoding="utf-8"))

    registry = BundleRegistry(clock=CLOCK).rebuild([bundle])

    assert registry.status == "PASS"
    assert len(registry.verified_entries) == 1
    entry = registry.verified_entries[0]
    assert report["coverage"] == pytest.approx(0.75)
    assert report["quality_score"] == pytest.approx(0.75)
    assert entry.coverage_ratio == pytest.approx(report["coverage"])
    assert entry.beta3b_quality_score == pytest.approx(report["quality_score"])


def test_promotion_lexicographic_order_uses_true_beta3b_exclusion_aware_quality(tmp_path):
    candidates, rows = governed(100)
    clean = DatasetBuilder(tmp_path / "clean", clock=CLOCK).build(candidates, rows)
    excluded = DatasetBuilder(tmp_path / "excluded", clock=CLOCK).build(
        candidates, rows, exclusions=exclusions(25)
    )

    registry = BundleRegistry(clock=CLOCK).rebuild([clean.bundle_path, excluded.bundle_path])
    by_path = {Path(item.bundle_path).parent.name: item for item in registry.verified_entries}

    assert by_path["clean"].coverage_ratio == pytest.approx(1.0)
    assert by_path["clean"].beta3b_quality_score == pytest.approx(1.0)
    assert by_path["excluded"].coverage_ratio == pytest.approx(0.8)
    assert by_path["excluded"].beta3b_quality_score == pytest.approx(0.8)

    recommendation = PromotionRecommender().recommend(registry.verified_entries)
    promoted = [
        sha for sha, status in recommendation.recommendations.items()
        if status == "TRAINING_CANDIDATE"
    ]
    assert promoted == [by_path["clean"].bundle_sha256]
