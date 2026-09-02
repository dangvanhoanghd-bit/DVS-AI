"""Beta 4A ML data-preparation foundation.

This package is intentionally limited to frozen contracts, immutable schemas,
and runtime-gate entry points. Production ML logic is introduced only after
independent review of this scaffolding release.
"""

from .contracts import (
    ClaimTerminalOutcome,
    EvaluationMode,
    FeatureColumn,
    FeatureSchemaIdentity,
    HoldoutClaimStatus,
    ModelSlotState,
    TestStatus,
)
from .errors import Beta4AGateError
from .feature_schema import (
    FeatureMatrixArtifact,
    FeatureMatrixBuilder,
    FeatureMatrixExclusion,
    FeatureMatrixPartition,
    FeatureMatrixSourceRow,
    FeatureSchemaManifest,
    MissingFeaturePolicy,
)
from .leakage_detector import (
    BundleRowMembership,
    LeakageDetectionReport,
    LeakageDetector,
    LeakageFinding,
    LeakageReportStatus,
    LeakageRowEvidence,
    LeakageSeverity,
)

__all__ = [
    "Beta4AGateError",
    "ClaimTerminalOutcome",
    "EvaluationMode",
    "FeatureColumn",
    "FeatureSchemaIdentity",
    "HoldoutClaimStatus",
    "FeatureMatrixArtifact",
    "FeatureMatrixBuilder",
    "FeatureMatrixExclusion",
    "FeatureMatrixPartition",
    "FeatureMatrixSourceRow",
    "FeatureSchemaManifest",
    "MissingFeaturePolicy",
    "ModelSlotState",
    "TestStatus",
    "BundleRowMembership",
    "LeakageDetectionReport",
    "LeakageDetector",
    "LeakageFinding",
    "LeakageReportStatus",
    "LeakageRowEvidence",
    "LeakageSeverity",
    "ModelRegistry",
]

from .model_registry import ModelRegistry

from .pipeline import Beta4APipeline, Beta4APipelineResult
__all__.extend(["Beta4APipeline", "Beta4APipelineResult"])
