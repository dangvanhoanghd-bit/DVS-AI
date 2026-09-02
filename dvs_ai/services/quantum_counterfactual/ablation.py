from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from dvs_ai.services.quantum_explainability.foundation import canonical_hash, canonical_json, verify_dataset_bundle
from dvs_ai.services.quantum_counterfactual.replay import (
    FUTURE_OR_OUTCOME_FIELDS,
    HistoricalReplayEngine,
    ReplayState,
)

ABLATION_SCHEMA_VERSION = "dvs-quantum-historical-ablation-v1"
ABLATION_MANIFEST_VERSION = "dvs-quantum-historical-ablation-manifest-v1"


class AblationState(str, Enum):
    COMPLETED_NON_IDENTIFIABLE = "COMPLETED_NON_IDENTIFIABLE"
    INVALID_STUDY = "INVALID_STUDY"
    REPLAY_BLOCKED = "REPLAY_BLOCKED"
    DATASET_INTEGRITY_BLOCKED = "DATASET_INTEGRITY_BLOCKED"


class AssociationClass(str, Enum):
    UNOBSERVABLE = "UNOBSERVABLE"
    INCONCLUSIVE = "INCONCLUSIVE"
    ASSOCIATED = "ASSOCIATED"
    ROBUST_ASSOCIATION = "ROBUST_ASSOCIATION"


@dataclass(frozen=True)
class AblationStudy:
    study_id: str
    target_field: str
    label: str = ""
    rationale: str = ""

    def normalized(self) -> "AblationStudy":
        return AblationStudy(
            study_id=str(self.study_id).strip(),
            target_field=str(self.target_field).strip(),
            label=str(self.label).strip(),
            rationale=str(self.rationale).strip(),
        )


@dataclass(frozen=True)
class OutcomeSummary:
    raw_n: int
    resolved_n: int
    win_n: int
    loss_n: int
    mean_realized_r: float | None
    profit_factor: float | None


@dataclass(frozen=True)
class HistoricalAblationResult:
    state: AblationState
    study_id: str
    target_field: str
    replay_state: str
    target_observed_n: int
    target_missing_n: int
    baseline: OutcomeSummary
    projected_without_target: OutcomeSummary
    delta_mean_realized_r: float | None
    association_class: AssociationClass
    limitations: tuple[str, ...]
    violations: tuple[str, ...]
    manifest: Mapping[str, Any]
    optimizer_allowed: bool = False
    recommendation_allowed: bool = False
    shadow_apply_allowed: bool = False
    main_write_authority: bool = False

    def export(self, output_dir: str | Path) -> tuple[Path, Path]:
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        result_path = root / f"quantum_ablation_{self.study_id}.json"
        payload_obj = asdict(self)
        payload_obj.pop("manifest", None)
        payload = canonical_json(payload_obj).encode("utf-8")
        result_path.write_bytes(payload)

        manifest = dict(self.manifest)
        manifest["result_file"] = result_path.name
        manifest["result_file_sha256"] = hashlib.sha256(payload).hexdigest()
        unsigned = canonical_json(manifest).encode("utf-8")
        manifest["self_sha256"] = hashlib.sha256(unsigned).hexdigest()
        manifest_path = root / f"quantum_ablation_{self.study_id}.manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return result_path, manifest_path


class HistoricalAblationEngine:
    """Read-only, non-causal leave-one-evidence-out projection.

    The engine verifies the sealed research dataset and FIRST_ELIGIBLE_PLAN replay
    bundle, then removes one evidence field only from an in-memory projection.
    Trade plans and recorded outcomes are never changed. Because the frozen
    Decision Engine is deliberately not re-executed, this slice must not claim a
    performance counterfactual; it returns COMPLETED_NON_IDENTIFIABLE and a
    transparent zero-by-construction outcome delta.
    """

    def __init__(self, dataset_path: str | Path, dataset_manifest_path: str | Path) -> None:
        self.dataset_path = Path(dataset_path)
        self.dataset_manifest_path = Path(dataset_manifest_path)

    def run(self, study: AblationStudy) -> HistoricalAblationResult:
        study = study.normalized()
        valid, dataset_manifest, detail = verify_dataset_bundle(self.dataset_path, self.dataset_manifest_path)
        if not valid:
            return self._blocked(study, AblationState.DATASET_INTEGRITY_BLOCKED, detail)

        violations = self._validate_study(study)
        if violations:
            return self._invalid(study, violations, dataset_manifest)

        replay = HistoricalReplayEngine(self.dataset_path, self.dataset_manifest_path).build()
        if replay.state != ReplayState.VERIFIED:
            return self._blocked(
                study,
                AblationState.REPLAY_BLOCKED,
                f"historical replay state is {replay.state.value}",
                dataset_manifest,
                replay_state=replay.state.value,
            )

        rows = self._read_rows()
        verified_ids = {record.sample_id for record in replay.records if record.replay_state == ReplayState.VERIFIED.value}
        rows = [row for row in rows if str(row.get("sample_id") or "") in verified_ids]

        observed_n = sum(self._is_observed(row.get(study.target_field)) for row in rows)
        missing_n = len(rows) - observed_n
        baseline = self._outcome_summary(rows)

        # Remove only the requested evidence field from an in-memory projection.
        # Outcomes and plan identity remain byte-for-byte semantically unchanged.
        projected = []
        for row in rows:
            copy = dict(row)
            copy.pop(study.target_field, None)
            projected.append(copy)
        projected_summary = self._outcome_summary(projected)
        delta = self._safe_delta(projected_summary.mean_realized_r, baseline.mean_realized_r)

        limitations = (
            "This is an observability ablation, not a causal estimate.",
            "The frozen Decision Engine is not re-executed; eligibility and TradePlan are unchanged.",
            "Recorded outcomes are immutable and are not used as replay evidence.",
            "A zero outcome delta is expected by construction and must not be interpreted as evidence irrelevance.",
        )
        manifest = self._manifest_base(
            study,
            AblationState.COMPLETED_NON_IDENTIFIABLE,
            dataset_manifest,
            replay.state.value,
            detail,
        )
        manifest.update({
            "target_observed_n": observed_n,
            "target_missing_n": missing_n,
            "outcome_projection_identifiable": False,
            "association_claim_allowed": False,
            "causal_claim_allowed": False,
            "safety_boundary": self._safety_boundary(),
        })
        return HistoricalAblationResult(
            state=AblationState.COMPLETED_NON_IDENTIFIABLE,
            study_id=study.study_id,
            target_field=study.target_field,
            replay_state=replay.state.value,
            target_observed_n=observed_n,
            target_missing_n=missing_n,
            baseline=baseline,
            projected_without_target=projected_summary,
            delta_mean_realized_r=delta,
            association_class=AssociationClass.INCONCLUSIVE,
            limitations=limitations,
            violations=(),
            manifest=manifest,
        )

    @staticmethod
    def _validate_study(study: AblationStudy) -> tuple[str, ...]:
        violations: list[str] = []
        if not study.study_id:
            violations.append("MISSING_STUDY_ID")
        if not study.target_field:
            violations.append("MISSING_TARGET_FIELD")
        if study.target_field in FUTURE_OR_OUTCOME_FIELDS:
            violations.append("OUTCOME_OR_FUTURE_FIELD_CANNOT_BE_ABLATED_AS_EVIDENCE")
        if study.target_field in {
            "sample_id", "candidate_id", "setup_episode_id", "first_evaluation_id",
            "activation_evaluation_id", "first_eligible_timestamp", "policy_scope_id",
            "policy_scope_hash", "decision_engine_checksum", "trade_plan_profile_hash",
            "source_row_hash",
        }:
            violations.append("GOVERNED_IDENTITY_FIELD_CANNOT_BE_ABLATED")
        return tuple(violations)

    def _read_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for line_number, raw in enumerate(self.dataset_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError(f"dataset row {line_number} is not an object")
            rows.append(value)
        return rows

    @staticmethod
    def _is_observed(value: Any) -> bool:
        if value is None or value == "" or value == [] or value == {}:
            return False
        if isinstance(value, float) and math.isnan(value):
            return False
        return True

    @staticmethod
    def _outcome_summary(rows: Sequence[Mapping[str, Any]]) -> OutcomeSummary:
        resolved = [row for row in rows if str(row.get("outcome_status") or "").upper() in {"WIN", "LOSS"}]
        wins = sum(str(row.get("outcome_status") or "").upper() == "WIN" for row in resolved)
        losses = len(resolved) - wins
        r_values = [float(row["realized_r"]) for row in resolved if row.get("realized_r") is not None]
        mean_r = (sum(r_values) / len(r_values)) if r_values else None
        gains = sum(value for value in r_values if value > 0)
        losses_abs = abs(sum(value for value in r_values if value < 0))
        pf = (gains / losses_abs) if losses_abs > 0 else (math.inf if gains > 0 else None)
        return OutcomeSummary(
            raw_n=len(rows),
            resolved_n=len(resolved),
            win_n=wins,
            loss_n=losses,
            mean_realized_r=mean_r,
            profit_factor=pf,
        )

    @staticmethod
    def _safe_delta(left: float | None, right: float | None) -> float | None:
        if left is None or right is None:
            return None
        return left - right

    def _invalid(self, study: AblationStudy, violations: tuple[str, ...], dataset_manifest: Mapping[str, Any]) -> HistoricalAblationResult:
        empty = OutcomeSummary(0, 0, 0, 0, None, None)
        return HistoricalAblationResult(
            state=AblationState.INVALID_STUDY,
            study_id=study.study_id,
            target_field=study.target_field,
            replay_state="NOT_RUN",
            target_observed_n=0,
            target_missing_n=0,
            baseline=empty,
            projected_without_target=empty,
            delta_mean_realized_r=None,
            association_class=AssociationClass.UNOBSERVABLE,
            limitations=("Study rejected before replay.",),
            violations=violations,
            manifest=self._manifest_base(study, AblationState.INVALID_STUDY, dataset_manifest, "NOT_RUN", "; ".join(violations)),
        )

    def _blocked(
        self,
        study: AblationStudy,
        state: AblationState,
        detail: str,
        dataset_manifest: Mapping[str, Any] | None = None,
        replay_state: str = "NOT_RUN",
    ) -> HistoricalAblationResult:
        empty = OutcomeSummary(0, 0, 0, 0, None, None)
        return HistoricalAblationResult(
            state=state,
            study_id=study.study_id,
            target_field=study.target_field,
            replay_state=replay_state,
            target_observed_n=0,
            target_missing_n=0,
            baseline=empty,
            projected_without_target=empty,
            delta_mean_realized_r=None,
            association_class=AssociationClass.UNOBSERVABLE,
            limitations=(detail,),
            violations=(),
            manifest=self._manifest_base(study, state, dataset_manifest or {}, replay_state, detail),
        )

    def _manifest_base(
        self,
        study: AblationStudy,
        state: AblationState,
        dataset_manifest: Mapping[str, Any],
        replay_state: str,
        detail: str,
    ) -> dict[str, Any]:
        return {
            "manifest_version": ABLATION_MANIFEST_VERSION,
            "schema_version": ABLATION_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "state": state.value,
            "study": asdict(study),
            "replay_state": replay_state,
            "dataset_file": self.dataset_path.name,
            "dataset_manifest_file": self.dataset_manifest_path.name,
            "dataset_sha256": dataset_manifest.get("dataset_sha256"),
            "dataset_manifest_self_sha256": dataset_manifest.get("self_sha256"),
            "detail": detail,
            "qg_contract": "QG-01..QG-16",
        }

    @staticmethod
    def _safety_boundary() -> dict[str, bool]:
        return {
            "decision_engine_frozen": True,
            "decision_engine_reexecution": False,
            "trade_plan_mutation": False,
            "outcome_mutation": False,
            "future_data_as_evidence": False,
            "optimizer_authority": False,
            "recommendation_authority": False,
            "shadow_write_authority": False,
            "main_write_authority": False,
        }


def verify_ablation_bundle(result_path: str | Path, manifest_path: str | Path) -> tuple[bool, str]:
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"manifest unreadable: {exc}"
    expected_self = str(manifest.get("self_sha256") or "")
    unsigned = dict(manifest)
    unsigned.pop("self_sha256", None)
    if not expected_self or canonical_hash(unsigned) != expected_self:
        return False, "manifest self checksum mismatch"

    result = Path(result_path)
    if not result.exists():
        return False, "ablation result file missing"
    if manifest.get("result_file") != result.name:
        return False, "ablation result filename does not match manifest"
    if hashlib.sha256(result.read_bytes()).hexdigest() != str(manifest.get("result_file_sha256") or ""):
        return False, "ablation result checksum mismatch"
    try:
        payload = json.loads(result.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"ablation result unreadable: {exc}"
    if payload.get("optimizer_allowed") or payload.get("recommendation_allowed"):
        return False, "forbidden authority enabled"
    if payload.get("shadow_apply_allowed") or payload.get("main_write_authority"):
        return False, "forbidden write authority enabled"
    return True, "verified"
