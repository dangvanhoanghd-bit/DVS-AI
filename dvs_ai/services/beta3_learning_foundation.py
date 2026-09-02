from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Protocol

from dvs_ai.services.unified_outcome_service import UnifiedOutcomeRecord

READINESS_THRESHOLDS = (30, 100, 300, 500)


def canonical_sha256(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class LearningOutcomeSource(Protocol):
    def learning_ready(self) -> list[UnifiedOutcomeRecord]: ...


@dataclass(frozen=True)
class PolicyIdentity:
    decision_engine_checksum: str
    policy_scope_id: str
    policy_scope_hash: str

    def validate(self) -> None:
        if not self.decision_engine_checksum.strip():
            raise ValueError("decision_engine_checksum is required")
        if not self.policy_scope_id.strip():
            raise ValueError("policy_scope_id is required")
        if not self.policy_scope_hash.strip():
            raise ValueError("policy_scope_hash is required")


@dataclass(frozen=True)
class LearningCandidate:
    learning_candidate_id: str
    unified_id: str
    candidate_id: str | None
    paper_trade_id: str | None
    feature_snapshot_hash: str
    outcome_status: str
    realized_r: float | None
    resolution_source: str | None
    review_action: str | None
    policy: PolicyIdentity
    source_identities: tuple[str, ...]
    # Beta 3D-r3 additive lineage compatibility fields. These values are
    # propagated from governed source truth; Beta 3 never recomputes them.
    first_eligible_evaluation_timestamp: str | None = None
    snapshot_timestamp: str | None = None


@dataclass(frozen=True)
class FeatureRow:
    feature_row_id: str
    learning_candidate_id: str
    unified_id: str
    feature_snapshot_hash: str
    feature_name: str
    feature_type: str
    value: Any
    source: str
    quality: str
    policy_scope_id: str
    policy_scope_hash: str
    decision_engine_checksum: str
    extractor_schema_version: str
    extractor_checksum: str


@dataclass(frozen=True)
class CandidateBuildResult:
    candidates: tuple[LearningCandidate, ...]
    exclusions: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class FeatureProjectionResult:
    rows: tuple[FeatureRow, ...]
    exclusions: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class DatasetReadiness:
    qualified_samples: int
    state: str
    dataset_emission_allowed: bool


def classify_dataset_readiness(qualified_samples: int) -> DatasetReadiness:
    if qualified_samples < 0:
        raise ValueError("qualified_samples cannot be negative")
    if qualified_samples < 30:
        return DatasetReadiness(qualified_samples, "UNOBSERVABLE", False)
    if qualified_samples < 100:
        return DatasetReadiness(qualified_samples, "DESCRIPTIVE_ONLY", True)
    if qualified_samples < 300:
        return DatasetReadiness(qualified_samples, "RESEARCH_CANDIDATE_ONLY", True)
    if qualified_samples < 500:
        return DatasetReadiness(qualified_samples, "VALIDATION_REVIEW_ELIGIBLE", True)
    return DatasetReadiness(qualified_samples, "BURN_IN_COMPLETE", True)


class LearningCandidateBuilder:
    """Beta 3A governed projection from UnifiedOutcomeService only.

    This class does not read SQLite, does not create snapshots, and cannot alter
    Decision Engine state. It accepts only records already exposed through the
    Beta 2 `learning_ready()` contract.
    """

    def __init__(self, outcome_source: LearningOutcomeSource, policy: PolicyIdentity) -> None:
        policy.validate()
        self.outcome_source = outcome_source
        self.policy = policy

    def build(self) -> CandidateBuildResult:
        candidates: list[LearningCandidate] = []
        exclusions: list[dict[str, Any]] = []
        seen: set[str] = set()
        for record in self.outcome_source.learning_ready():
            reason: str | None = None
            if record.unified_id in seen:
                reason = "DUPLICATE_UNIFIED_ID"
            elif record.eligibility_status != "UNIFIED_ELIGIBLE":
                reason = "NOT_UNIFIED_ELIGIBLE"
            elif record.outcome_status not in {"WIN", "LOSS"}:
                reason = "NON_DETERMINATE_OUTCOME"
            elif not record.feature_snapshot_hash:
                reason = "FEATURE_SNAPSHOT_HASH_MISSING"
            elif record.review_action == "EXCLUDE":
                reason = "EXCLUDED_BY_REVIEW"
            elif record.conflict_reason:
                reason = "UNRESOLVED_CONFLICT"
            if reason:
                exclusions.append({"unified_id": record.unified_id, "reason": reason})
                continue
            seen.add(record.unified_id)
            payload = {
                "unified_id": record.unified_id,
                "feature_snapshot_hash": record.feature_snapshot_hash,
                "policy_scope_hash": self.policy.policy_scope_hash,
            }
            candidates.append(LearningCandidate(
                learning_candidate_id=canonical_sha256(payload),
                unified_id=record.unified_id,
                candidate_id=record.candidate_id,
                paper_trade_id=record.paper_trade_id,
                feature_snapshot_hash=record.feature_snapshot_hash,
                outcome_status=record.outcome_status,
                realized_r=record.realized_r,
                resolution_source=record.resolution_source,
                review_action=record.review_action,
                policy=self.policy,
                source_identities=record.source_identities,
                # UnifiedOutcomeRecord.setup_time is the governed activation/setup
                # timestamp currently exposed by the Beta 2 read contract. The
                # compatibility patch propagates it under both explicit lineage
                # names without deriving a new timestamp.
                first_eligible_evaluation_timestamp=record.setup_time,
                snapshot_timestamp=record.setup_time,
            ))
        return CandidateBuildResult(tuple(candidates), tuple(exclusions))


class FeatureStoreProjector:
    """Projects existing evidence payloads; never writes a third snapshot source."""

    RESERVED_KEYS = frozenset({"outcome", "realized_r", "candidate_id", "paper_trade_id"})

    def __init__(self, extractor_schema_version: str, extractor_checksum: str) -> None:
        if not extractor_schema_version or not extractor_checksum:
            raise ValueError("extractor identity is required")
        self.extractor_schema_version = extractor_schema_version
        self.extractor_checksum = extractor_checksum

    @staticmethod
    def _feature_type(value: Any) -> str:
        if isinstance(value, bool):
            return "BOOLEAN"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return "NUMBER"
        if isinstance(value, str):
            return "STRING"
        return "JSON"

    def project(
        self,
        candidates: Iterable[LearningCandidate],
        evidence_by_unified_id: Mapping[str, Mapping[str, Any] | None],
    ) -> FeatureProjectionResult:
        rows: list[FeatureRow] = []
        exclusions: list[dict[str, Any]] = []
        for candidate in candidates:
            evidence = evidence_by_unified_id.get(candidate.unified_id)
            if not evidence:
                exclusions.append({"unified_id": candidate.unified_id, "reason": "EVIDENCE_PAYLOAD_MISSING"})
                continue
            observed_hash = canonical_sha256(evidence)
            declared = candidate.feature_snapshot_hash
            if observed_hash != declared:
                exclusions.append({"unified_id": candidate.unified_id, "reason": "FEATURE_SNAPSHOT_HASH_MISMATCH"})
                continue
            for name in sorted(evidence):
                if name in self.RESERVED_KEYS:
                    continue
                value = evidence[name]
                quality = "INVALID" if value is None else "VALID"
                row_payload = {
                    "learning_candidate_id": candidate.learning_candidate_id,
                    "feature_name": name,
                    "feature_value": value,
                    "extractor_checksum": self.extractor_checksum,
                }
                rows.append(FeatureRow(
                    feature_row_id=canonical_sha256(row_payload),
                    learning_candidate_id=candidate.learning_candidate_id,
                    unified_id=candidate.unified_id,
                    feature_snapshot_hash=declared,
                    feature_name=name,
                    feature_type=self._feature_type(value),
                    value=value,
                    source="UNIFIED_EVIDENCE_SNAPSHOT",
                    quality=quality,
                    policy_scope_id=candidate.policy.policy_scope_id,
                    policy_scope_hash=candidate.policy.policy_scope_hash,
                    decision_engine_checksum=candidate.policy.decision_engine_checksum,
                    extractor_schema_version=self.extractor_schema_version,
                    extractor_checksum=self.extractor_checksum,
                ))
        return FeatureProjectionResult(tuple(rows), tuple(exclusions))


def lineage_record(candidate: LearningCandidate, feature_row: FeatureRow) -> dict[str, Any]:
    if candidate.learning_candidate_id != feature_row.learning_candidate_id:
        raise ValueError("candidate/feature lineage mismatch")
    if candidate.feature_snapshot_hash != feature_row.feature_snapshot_hash:
        raise ValueError("snapshot lineage mismatch")
    return {
        "feature_row_id": feature_row.feature_row_id,
        "learning_candidate_id": candidate.learning_candidate_id,
        "unified_id": candidate.unified_id,
        "candidate_id": candidate.candidate_id,
        "paper_trade_id": candidate.paper_trade_id,
        "source_identities": list(candidate.source_identities),
        "feature_snapshot_hash": candidate.feature_snapshot_hash,
        "policy_scope_id": candidate.policy.policy_scope_id,
        "policy_scope_hash": candidate.policy.policy_scope_hash,
        "decision_engine_checksum": candidate.policy.decision_engine_checksum,
        "first_eligible_evaluation_timestamp": candidate.first_eligible_evaluation_timestamp,
        "snapshot_timestamp": candidate.snapshot_timestamp,
    }
