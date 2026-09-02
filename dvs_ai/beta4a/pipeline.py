from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import uuid
from typing import Callable, Iterable, Mapping, Sequence

from dvs_ai.services.beta3_cross_bundle import RegistryEntry

from .bundle_selection_gate import BundleSelection, BundleSelectionGate
from .contracts import FeatureSchemaManifest, ModelSlotManifest, ModelSlotState, TrainedModelArtifact
from .dataset_split import DatasetRowRecord, DatasetSplitEngine, SplitArtifact, SplitConfig
from .feature_schema import FeatureMatrixArtifact, FeatureMatrixBuilder, FeatureMatrixSourceRow, TrainingFeatureMatrixArtifact
from .leakage_detector import (
    BundleRowMembership,
    LeakageDetectionReport,
    LeakageDetector,
    LeakageRowEvidence,
)
from .model_evaluation_gate import ModelEvaluationGate
from .model_lifecycle_gate import ModelLifecycleGate
from .model_registry import ModelRegistry

Trainer = Callable[[str, TrainingFeatureMatrixArtifact], TrainedModelArtifact | bytes | bytearray]
Evaluator = Callable[[str, object], dict[str, float]]


@dataclass(frozen=True, slots=True)
class Beta4APipelineResult:
    selection: BundleSelection
    split_artifact: SplitArtifact
    leakage_report: LeakageDetectionReport
    feature_matrix: FeatureMatrixArtifact
    trained_manifest: ModelSlotManifest
    validated_manifest: ModelSlotManifest
    evaluation_report_id: str
    trained_model_artifact: TrainedModelArtifact


class Beta4APipeline:
    """Single orchestrated Beta 4A path from bundle selection to validation.

    Lower-layer metrics are consumed as immutable inputs. Test rows are only
    accessed by ``ModelEvaluationGate`` and VALIDATED is only emitted by
    ``ModelLifecycleGate``.
    """

    def __init__(
        self,
        *,
        model_registry: ModelRegistry,
        evaluation_gate: ModelEvaluationGate,
        lifecycle_gate: ModelLifecycleGate,
        bundle_gate: BundleSelectionGate | None = None,
        split_engine: DatasetSplitEngine | None = None,
        leakage_detector: LeakageDetector | None = None,
        matrix_builder: FeatureMatrixBuilder | None = None,
    ) -> None:
        self._registry = model_registry
        self._evaluation_gate = evaluation_gate
        self._lifecycle_gate = lifecycle_gate
        self._bundle_gate = bundle_gate or BundleSelectionGate()
        self._split_engine = split_engine or DatasetSplitEngine()
        self._leakage_detector = leakage_detector or LeakageDetector()
        self._matrix_builder = matrix_builder or FeatureMatrixBuilder()

    def run(
        self,
        *,
        registry_entries: Iterable[RegistryEntry],
        dataset_rows: Iterable[DatasetRowRecord | Mapping[str, object]],
        leakage_rows: Iterable[LeakageRowEvidence | Mapping[str, object]],
        feature_rows: Iterable[FeatureMatrixSourceRow | Mapping[str, object]],
        feature_schema: FeatureSchemaManifest,
        model_slot_id: str,
        trainer: Trainer,
        evaluator: Evaluator,
        split_config: SplitConfig | None = None,
        bundle_memberships: Sequence[BundleRowMembership | Mapping[str, object]] = (),
    ) -> Beta4APipelineResult:
        entries = tuple(registry_entries)
        selection = self._bundle_gate.select(entries)
        selected_entry = next(item for item in entries if item.bundle_sha256 == selection.bundle_sha256)

        split = self._split_engine.split(
            dataset_rows,
            source_bundle_sha256=selection.bundle_sha256,
            config=split_config,
        )
        leakage = self._leakage_detector.detect(
            leakage_rows,
            split_artifact=split,
            bundle_sha256=selection.bundle_sha256,
            feature_schema_identity=feature_schema.identity.ordered_feature_list_hash,
            bundle_memberships=bundle_memberships,
        )
        self._leakage_detector.require_pass(leakage)
        matrix = self._matrix_builder.build(
            feature_rows,
            schema=feature_schema,
            split_artifact=split,
            leakage_report=leakage,
            bundle_sha256=selection.bundle_sha256,
            include_test=False,
        )

        initial = ModelSlotManifest(
            model_slot_id=model_slot_id,
            state=ModelSlotState.EMPTY,
            policy_identity=selected_entry.policy_identity,
            extraction_identity=selected_entry.extraction_identity,
            feature_schema_identity=feature_schema.identity,
            source_bundle_sha256=selection.bundle_sha256,
            source_split_sha256=split.split_sha256,
        )
        self._registry.create_empty_slot(initial)
        self._registry.transition(model_slot_id=model_slot_id, target_state=ModelSlotState.RESERVED, reason="pipeline_reserved")
        self._registry.transition(model_slot_id=model_slot_id, target_state=ModelSlotState.TRAINING, reason="pipeline_training_started")
        training_view = matrix.training_view()
        trainer_result = trainer(model_slot_id, training_view)
        trained = self._registry.transition(
            model_slot_id=model_slot_id,
            target_state=ModelSlotState.TRAINED_UNVALIDATED,
            reason="pipeline_training_completed",
        )
        if isinstance(trainer_result, TrainedModelArtifact):
            artifact = trainer_result
            if artifact.model_slot_id != model_slot_id:
                raise ValueError("trainer returned artifact for a different model_slot_id")
            if artifact.feature_matrix_sha256 != matrix.matrix_sha256:
                raise ValueError("trainer artifact does not bind to the supplied feature matrix")
        elif isinstance(trainer_result, (bytes, bytearray)):
            model_sha = hashlib.sha256(bytes(trainer_result)).hexdigest()
            config_sha = hashlib.sha256(b"{}").hexdigest()
            artifact = TrainedModelArtifact(
                model_slot_id=model_slot_id,
                model_artifact_sha256=model_sha,
                feature_matrix_sha256=matrix.matrix_sha256,
                training_config_sha256=config_sha,
                training_run_id=uuid.uuid4().hex,
            )
        else:
            raise TypeError("trainer must return TrainedModelArtifact or model bytes")
        trained = self._registry.bind_trained_artifact(
            model_slot_id=model_slot_id,
            model_artifact_sha256=artifact.model_artifact_sha256,
            feature_matrix_sha256=artifact.feature_matrix_sha256,
            training_config_sha256=artifact.training_config_sha256,
            training_run_id=artifact.training_run_id,
        )

        report = self._evaluation_gate.evaluate(
            model_slot_id=model_slot_id,
            split_sha256=split.split_sha256,
            evaluator=evaluator,
            model_artifact_sha256=artifact.model_artifact_sha256,
            feature_matrix_sha256=artifact.feature_matrix_sha256,
            training_run_id=artifact.training_run_id,
        )
        validated = self._lifecycle_gate.promote_to_validated(
            model_slot=trained,
            evaluation_report=report,
        )
        return Beta4APipelineResult(
            selection=selection,
            split_artifact=split,
            leakage_report=leakage,
            feature_matrix=matrix,
            trained_manifest=trained,
            validated_manifest=validated,
            evaluation_report_id=report.report_id,
            trained_model_artifact=artifact,
        )
