from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from dvs_ai.services.quantum_explainability.foundation import canonical_hash, canonical_json, verify_dataset_bundle

REPLAY_SCHEMA_VERSION = "dvs-quantum-historical-replay-v1"
REPLAY_MANIFEST_VERSION = "dvs-quantum-historical-replay-manifest-v1"

FUTURE_OR_OUTCOME_FIELDS = frozenset({
    "outcome_status", "outcome_time", "realized_r", "mfe_r", "mae_r",
    "future_return", "future_price", "resolved_at",
})


class ReplayState(str, Enum):
    VERIFIED = "VERIFIED"
    INVALID_REPLAY = "INVALID_REPLAY"
    DATASET_INTEGRITY_BLOCKED = "DATASET_INTEGRITY_BLOCKED"


@dataclass(frozen=True)
class HistoricalReplayRecord:
    replay_id: str
    sample_id: str
    candidate_id: str
    setup_episode_id: str
    first_evaluation_id: str
    activation_evaluation_id: str
    first_eligible_timestamp: str
    policy_scope_id: str
    policy_scope_hash: str
    decision_engine_checksum: str
    trade_plan_profile_hash: str
    source_row_hash: str
    replay_state: str
    replay_basis: str
    snapshot_fields: tuple[str, ...]
    violations: tuple[str, ...]
    limitations: tuple[str, ...]
    record_sha256: str


@dataclass(frozen=True)
class HistoricalReplayResult:
    state: ReplayState
    dataset_integrity_verified: bool
    replay_count: int
    verified_count: int
    invalid_count: int
    records: tuple[HistoricalReplayRecord, ...]
    manifest: Mapping[str, Any]
    optimizer_allowed: bool = False
    recommendation_allowed: bool = False
    shadow_apply_allowed: bool = False
    main_write_authority: bool = False

    def export(self, output_dir: str | Path) -> tuple[Path, Path]:
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        records_path = root / "quantum_historical_replays.jsonl"
        lines = [canonical_json(asdict(record)) for record in self.records]
        payload = (("\n".join(lines) + "\n") if lines else "").encode("utf-8")
        records_path.write_bytes(payload)

        manifest = dict(self.manifest)
        manifest["replay_file"] = records_path.name
        manifest["replay_file_sha256"] = hashlib.sha256(payload).hexdigest()
        unsigned = canonical_json(manifest).encode("utf-8")
        manifest["self_sha256"] = hashlib.sha256(unsigned).hexdigest()
        manifest_path = root / "quantum_historical_replays.manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return records_path, manifest_path


class HistoricalReplayEngine:
    """Validate replay provenance without recomputing or changing the frozen Decision Engine.

    This first 4.3.0D slice verifies that each research episode can be replayed only
    from its recorded FIRST_ELIGIBLE_PLAN identity. It deliberately does not infer
    missing features, consume future outcomes as evidence, optimize, recommend, or
    write to SHADOW/MAIN.
    """

    REQUIRED_IDENTITY_FIELDS = (
        "sample_id", "candidate_id", "setup_episode_id", "first_evaluation_id",
        "activation_evaluation_id", "first_eligible_timestamp", "policy_scope_id",
        "policy_scope_hash", "decision_engine_checksum", "trade_plan_profile_hash",
        "source_row_hash",
    )

    def __init__(self, dataset_path: str | Path, manifest_path: str | Path) -> None:
        self.dataset_path = Path(dataset_path)
        self.manifest_path = Path(manifest_path)

    def build(self) -> HistoricalReplayResult:
        verified, dataset_manifest, detail = verify_dataset_bundle(self.dataset_path, self.manifest_path)
        if not verified:
            return self._blocked(dataset_manifest, detail)

        records: list[HistoricalReplayRecord] = []
        for line_number, raw_line in enumerate(self.dataset_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw_line.strip():
                continue
            try:
                episode = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                return self._blocked(dataset_manifest, f"invalid JSONL at line {line_number}: {exc}")
            if not isinstance(episode, dict):
                return self._blocked(dataset_manifest, f"dataset row {line_number} is not an object")
            records.append(self._validate_episode(episode))

        invalid_count = sum(r.replay_state == ReplayState.INVALID_REPLAY.value for r in records)
        verified_count = len(records) - invalid_count
        state = ReplayState.INVALID_REPLAY if invalid_count else ReplayState.VERIFIED
        manifest = self._manifest_base(state, dataset_manifest, detail)
        manifest.update({
            "replay_count": len(records),
            "verified_count": verified_count,
            "invalid_count": invalid_count,
            "first_eligible_plan_required": True,
            "future_or_outcome_fields_forbidden_as_replay_evidence": sorted(FUTURE_OR_OUTCOME_FIELDS),
            "safety_boundary": {
                "decision_engine_frozen": True,
                "feature_recomputation": False,
                "future_data_allowed": False,
                "outcome_as_replay_evidence_allowed": False,
                "optimizer_authority": False,
                "recommendation_authority": False,
                "shadow_write_authority": False,
                "main_write_authority": False,
            },
        })
        return HistoricalReplayResult(
            state=state,
            dataset_integrity_verified=True,
            replay_count=len(records),
            verified_count=verified_count,
            invalid_count=invalid_count,
            records=tuple(records),
            manifest=manifest,
        )

    def _validate_episode(self, episode: Mapping[str, Any]) -> HistoricalReplayRecord:
        violations: list[str] = []
        for name in self.REQUIRED_IDENTITY_FIELDS:
            value = episode.get(name)
            if value is None or str(value).strip() == "":
                violations.append(f"MISSING_{name.upper()}")

        first_eval = str(episode.get("first_evaluation_id") or "")
        activation_eval = str(episode.get("activation_evaluation_id") or "")
        if first_eval and activation_eval and first_eval != activation_eval:
            violations.append("FIRST_ELIGIBLE_EVALUATION_MISMATCH")

        ts = str(episode.get("first_eligible_timestamp") or "")
        if ts and not self._is_valid_timestamp(ts):
            violations.append("INVALID_FIRST_ELIGIBLE_TIMESTAMP")

        # Snapshot fields are descriptive provenance only. Explicitly exclude all
        # outcome/future fields so downstream code cannot mistake them for inputs.
        snapshot_fields = tuple(sorted(
            str(k) for k, v in episode.items()
            if k not in FUTURE_OR_OUTCOME_FIELDS and v not in (None, "", [], {})
        ))
        if any(name in FUTURE_OR_OUTCOME_FIELDS for name in snapshot_fields):
            violations.append("FUTURE_OR_OUTCOME_FIELD_LEAKAGE")

        state = ReplayState.INVALID_REPLAY if violations else ReplayState.VERIFIED
        limitations = (
            "Provenance replay validation only; the frozen Decision Engine is not re-executed.",
            "No feature is recomputed and no future/outcome field is accepted as replay evidence.",
            "Ablation and uncertainty estimation are not part of this 4.3.0D-1 slice.",
        )
        base = {
            "schema_version": REPLAY_SCHEMA_VERSION,
            "sample_id": str(episode.get("sample_id") or ""),
            "candidate_id": str(episode.get("candidate_id") or ""),
            "setup_episode_id": str(episode.get("setup_episode_id") or ""),
            "first_evaluation_id": first_eval,
            "activation_evaluation_id": activation_eval,
            "first_eligible_timestamp": ts,
            "policy_scope_id": str(episode.get("policy_scope_id") or ""),
            "policy_scope_hash": str(episode.get("policy_scope_hash") or ""),
            "decision_engine_checksum": str(episode.get("decision_engine_checksum") or ""),
            "trade_plan_profile_hash": str(episode.get("trade_plan_profile_hash") or ""),
            "source_row_hash": str(episode.get("source_row_hash") or ""),
            "replay_state": state.value,
            "replay_basis": "FIRST_ELIGIBLE_PLAN",
            "snapshot_fields": list(snapshot_fields),
            "violations": violations,
            "limitations": list(limitations),
        }
        record_hash = canonical_hash(base)
        replay_id = "QRP-" + hashlib.sha256((base["sample_id"] + record_hash).encode()).hexdigest()[:24].upper()
        return HistoricalReplayRecord(
            replay_id=replay_id,
            sample_id=base["sample_id"],
            candidate_id=base["candidate_id"],
            setup_episode_id=base["setup_episode_id"],
            first_evaluation_id=first_eval,
            activation_evaluation_id=activation_eval,
            first_eligible_timestamp=ts,
            policy_scope_id=base["policy_scope_id"],
            policy_scope_hash=base["policy_scope_hash"],
            decision_engine_checksum=base["decision_engine_checksum"],
            trade_plan_profile_hash=base["trade_plan_profile_hash"],
            source_row_hash=base["source_row_hash"],
            replay_state=state.value,
            replay_basis="FIRST_ELIGIBLE_PLAN",
            snapshot_fields=snapshot_fields,
            violations=tuple(violations),
            limitations=limitations,
            record_sha256=record_hash,
        )

    @staticmethod
    def _is_valid_timestamp(value: str) -> bool:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return parsed.tzinfo is not None

    def _blocked(self, dataset_manifest: Mapping[str, Any], detail: str) -> HistoricalReplayResult:
        return HistoricalReplayResult(
            state=ReplayState.DATASET_INTEGRITY_BLOCKED,
            dataset_integrity_verified=False,
            replay_count=0,
            verified_count=0,
            invalid_count=0,
            records=(),
            manifest=self._manifest_base(ReplayState.DATASET_INTEGRITY_BLOCKED, dataset_manifest, detail),
        )

    def _manifest_base(self, state: ReplayState, dataset_manifest: Mapping[str, Any], detail: str) -> dict[str, Any]:
        return {
            "manifest_version": REPLAY_MANIFEST_VERSION,
            "replay_schema_version": REPLAY_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "state": state.value,
            "dataset_file": self.dataset_path.name,
            "dataset_manifest_file": self.manifest_path.name,
            "dataset_sha256": dataset_manifest.get("dataset_sha256"),
            "dataset_manifest_self_sha256": dataset_manifest.get("self_sha256"),
            "dataset_integrity_detail": detail,
            "qg_contract": "QG-01..QG-16",
        }


def verify_replay_bundle(records_path: str | Path, manifest_path: str | Path) -> tuple[bool, str]:
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"manifest unreadable: {exc}"
    expected_self = str(manifest.get("self_sha256") or "")
    unsigned_manifest = dict(manifest)
    unsigned_manifest.pop("self_sha256", None)
    actual_self = hashlib.sha256(canonical_json(unsigned_manifest).encode()).hexdigest()
    if not expected_self or expected_self != actual_self:
        return False, "manifest self checksum mismatch"

    records = Path(records_path)
    if not records.exists():
        return False, "replay file missing"
    if manifest.get("replay_file") and manifest.get("replay_file") != records.name:
        return False, "replay filename does not match manifest"
    if hashlib.sha256(records.read_bytes()).hexdigest() != str(manifest.get("replay_file_sha256") or ""):
        return False, "replay file checksum mismatch"

    for line_number, raw in enumerate(records.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            return False, f"invalid replay JSONL at line {line_number}: {exc}"
        expected = str(row.get("record_sha256") or "")
        unsigned = dict(row)
        unsigned.pop("record_sha256", None)
        unsigned.pop("replay_id", None)
        unsigned["schema_version"] = REPLAY_SCHEMA_VERSION
        if canonical_hash(unsigned) != expected:
            return False, f"record checksum mismatch at line {line_number}"
    return True, "verified"
