from __future__ import annotations
import hashlib
import json
import random
from dataclasses import dataclass
from .observable_models import ObservableState, PowerState
from .report_models import ConfidenceReport, EvidenceReport, StageState

@dataclass(frozen=True)
class ConfidenceInput:
    protocol_version: str
    context_id: str
    context_artifact_hash: str
    observability_state: ObservableState
    power_state: PowerState
    integrity_state: StageState
    evidence: EvidenceReport

    def verify(self) -> bool:
        if self.evidence.state not in {StageState.PASS, StageState.SKIPPED}:
            return False
        if self.evidence.artifact_hash:
            expected = hashlib.sha256(json.dumps({
                "context_id": self.context_id,
                "context_artifact_hash": self.context_artifact_hash,
                "sample_count": self.evidence.sample_count,
                "selected_count": self.evidence.selected_count,
                "outcome_count": self.evidence.outcome_count,
                "selected_outcomes": list(self.evidence.selected_outcomes),
            }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            return expected == self.evidence.artifact_hash
        return True

class ConfidenceEngine:
    """Pure statistical engine over a frozen evidence artifact.

    It has no database, repository, Observable Universe, or recommendation dependency.
    """
    ENGINE_VERSION = "1.1"

    @staticmethod
    def build(payload: ConfidenceInput, *, samples: int = 2000) -> ConfidenceReport:
        if not payload.verify():
            return ConfidenceReport(StageState.ANALYSIS_ABORTED, "UNOBSERVABLE", "NONE", None, None, "evidence artifact verification failed", engine_version=ConfidenceEngine.ENGINE_VERSION)
        if payload.integrity_state is not StageState.PASS:
            return ConfidenceReport(StageState.SKIPPED, "UNOBSERVABLE", "NONE", None, None, "integrity gate failed", engine_version=ConfidenceEngine.ENGINE_VERSION)
        if payload.observability_state is ObservableState.UNOBSERVABLE:
            return ConfidenceReport(StageState.SKIPPED, "UNOBSERVABLE", "NONE", None, None, "intersection below observable threshold", engine_version=ConfidenceEngine.ENGINE_VERSION)
        if payload.power_state is not PowerState.POWERED:
            return ConfidenceReport(StageState.SKIPPED, "OBSERVABLE_BUT_UNDERPOWERED", "LOW", None, None, "powered threshold not reached", outcome_count=payload.evidence.outcome_count, engine_version=ConfidenceEngine.ENGINE_VERSION)
        values = tuple(float(x) for x in payload.evidence.selected_outcomes)
        if not values:
            return ConfidenceReport(StageState.PASS, "NO_ACTIONABLE_ISSUE_DETECTED", "LOW", None, None, "no completed selected outcomes", outcome_count=0, engine_version=ConfidenceEngine.ENGINE_VERSION)
        n = len(values)
        rng_seed = int(hashlib.sha256(f"{payload.context_artifact_hash}:{payload.evidence.artifact_hash}".encode()).hexdigest()[:16], 16)
        rng = random.Random(rng_seed)
        draws = max(500, int(samples))
        means = [sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(draws)]
        means.sort()
        lo = means[int(.025 * (draws - 1))]
        hi = means[int(.975 * (draws - 1))]
        positive = sum(1 for x in means if x > 0) / draws
        if lo > 0:
            conclusion = "SUPPORTED"
        elif hi < 0:
            conclusion = "UNSUPPORTED"
        else:
            conclusion = "NO_ACTIONABLE_ISSUE_DETECTED"
        width = hi - lo
        confidence = "HIGH" if n >= 120 and width <= .20 else "MEDIUM" if n >= 60 and width <= .50 else "LOW"
        return ConfidenceReport(StageState.PASS, conclusion, confidence, lo, hi, f"deterministic bootstrap 95% CI from {n} outcomes", positive, width, n, ConfidenceEngine.ENGINE_VERSION)
