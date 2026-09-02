from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Any, Mapping, Sequence


class TestStatus(str, Enum):
    LOCKED_UNCONSUMED = "LOCKED_UNCONSUMED"
    CONSUMED = "CONSUMED"


class EvaluationMode(str, Enum):
    QUALIFYING_HOLDOUT_EVALUATION = "QUALIFYING_HOLDOUT_EVALUATION"
    HISTORICAL_BENCHMARK_EVALUATION = "HISTORICAL_BENCHMARK_EVALUATION"


class HoldoutClaimStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    CLAIMED = "CLAIMED"
    ACCESS_STARTED = "ACCESS_STARTED"
    CONSUMED = "CONSUMED"


class ClaimTerminalOutcome(str, Enum):
    CLAIM_COMPLETED = "CLAIM_COMPLETED"
    CLAIM_RECOVERED = "CLAIM_RECOVERED"
    CLAIM_ABORTED_AFTER_ACCESS = "CLAIM_ABORTED_AFTER_ACCESS"


class ModelSlotState(str, Enum):
    EMPTY = "EMPTY"
    RESERVED = "RESERVED"
    TRAINING = "TRAINING"
    TRAINED_UNVALIDATED = "TRAINED_UNVALIDATED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class FeatureColumn:
    name: str
    dtype: str
    encoding: str
    column_index: int
    categories: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("feature name must be non-empty")
        if self.column_index < 0:
            raise ValueError("column_index must be non-negative")
        if len(set(self.categories)) != len(self.categories):
            raise ValueError("categorical values must be unique")
        if self.encoding == "categorical" and not self.categories:
            raise ValueError("categorical encoding requires frozen categories")
        if self.encoding != "categorical" and self.categories:
            raise ValueError("categories are only valid for categorical encoding")


@dataclass(frozen=True, slots=True)
class FeatureSchemaIdentity:
    feature_schema_version: str
    ordered_feature_list_hash: str


@dataclass(frozen=True, slots=True)
class FeatureSchemaManifest:
    feature_schema_version: str
    columns: tuple[FeatureColumn, ...]

    def __post_init__(self) -> None:
        indices = tuple(column.column_index for column in self.columns)
        if indices != tuple(range(len(self.columns))):
            raise ValueError("columns must use contiguous frozen order starting at zero")
        names = tuple(column.name for column in self.columns)
        if len(set(names)) != len(names):
            raise ValueError("feature names must be unique")

    @property
    def identity(self) -> FeatureSchemaIdentity:
        payload = [
            {
                "name": column.name,
                "dtype": column.dtype,
                "encoding": column.encoding,
                "column_index": column.column_index,
                "categories": list(column.categories),
            }
            for column in self.columns
        ]
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return FeatureSchemaIdentity(self.feature_schema_version, digest)

    def ordered_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    report_id: str
    model_slot_id: str
    split_sha256: str
    evaluation_mode: EvaluationMode
    qualifying: bool
    historical_benchmark_only: bool
    test_status_at_evaluation_start: TestStatus
    holdout_consumption_record_sha256: str | None
    metrics: Mapping[str, Any]
    model_artifact_sha256: str | None = None
    feature_matrix_sha256: str | None = None
    training_run_id: str | None = None

    def __post_init__(self) -> None:
        qualifying_shape = (
            self.evaluation_mode is EvaluationMode.QUALIFYING_HOLDOUT_EVALUATION
            and self.qualifying
            and not self.historical_benchmark_only
            and self.test_status_at_evaluation_start is TestStatus.LOCKED_UNCONSUMED
            and bool(self.holdout_consumption_record_sha256)
        )
        historical_shape = (
            self.evaluation_mode is EvaluationMode.HISTORICAL_BENCHMARK_EVALUATION
            and not self.qualifying
            and self.historical_benchmark_only
            and self.test_status_at_evaluation_start is TestStatus.CONSUMED
            and self.holdout_consumption_record_sha256 is None
        )
        if not (qualifying_shape or historical_shape):
            raise ValueError("evaluation report flags contradict frozen evaluation mode")


@dataclass(frozen=True, slots=True)
class HoldoutConsumptionRecord:
    split_sha256: str
    model_slot_id: str
    consumed_at: str
    evaluation_purpose: str
    evaluation_report_sha256: str


@dataclass(frozen=True, slots=True)
class HoldoutClaimRecord:
    claim_id: str
    split_sha256: str
    model_slot_id: str
    claimed_at: str
    claim_expires_at: str
    access_started_at: str | None = None
    terminal_outcome: ClaimTerminalOutcome | None = None


@dataclass(frozen=True, slots=True)
class ModelSlotManifest:
    model_slot_id: str
    state: ModelSlotState
    policy_identity: tuple[str, str, str]
    extraction_identity: tuple[str, str]
    feature_schema_identity: FeatureSchemaIdentity
    source_bundle_sha256: str
    source_split_sha256: str
    model_artifact_sha256: str | None = None
    feature_matrix_sha256: str | None = None
    training_config_sha256: str | None = None
    training_run_id: str | None = None


@dataclass(frozen=True, slots=True)
class TrainedModelArtifact:
    model_slot_id: str
    model_artifact_sha256: str
    feature_matrix_sha256: str
    training_config_sha256: str
    training_run_id: str

    def __post_init__(self) -> None:
        for name in ("model_artifact_sha256", "feature_matrix_sha256", "training_config_sha256"):
            value = getattr(self, name)
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value.lower()):
                raise ValueError(f"{name} must be a SHA-256 hex digest")
        if not self.model_slot_id or not self.training_run_id:
            raise ValueError("model_slot_id and training_run_id must be non-empty")


@dataclass(frozen=True, slots=True)
class ModelLifecycleTransitionRecord:
    transition_id: str
    model_slot_id: str
    source_state: ModelSlotState
    target_state: ModelSlotState
    source_manifest_sha256: str
    target_manifest_sha256: str
    evaluation_report_id: str
    evaluation_report_sha256: str
    holdout_consumption_record_sha256: str
    transitioned_at: str
