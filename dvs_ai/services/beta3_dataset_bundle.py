from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from dvs_ai.services.beta3_learning_foundation import (
    FeatureRow,
    LearningCandidate,
    canonical_sha256,
    classify_dataset_readiness,
    lineage_record,
)

DATASET_SCHEMA_VERSION = "beta4a.dataset.v2"
MANIFEST_SCHEMA_VERSION = "beta3b.manifest.v1"
BUNDLE_FILES = (
    "training_dataset.jsonl",
    "exclusions.jsonl",
    "quality_report.json",
    "lineage_index.jsonl",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_bytes(_canonical_bytes(payload) + b"\n")


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    with path.open("wb") as handle:
        for row in rows:
            handle.write(_canonical_bytes(row) + b"\n")
            count += 1
    return count


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


@dataclass(frozen=True)
class DatasetBuildResult:
    status: str
    readiness_state: str
    qualified_samples: int
    bundle_path: str | None
    dataset_id: str | None
    manifest_sha256: str | None
    bundle_sha256: str | None
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class DatasetVerificationResult:
    valid: bool
    errors: tuple[str, ...]
    manifest: Mapping[str, Any] | None
    bundle_sha256: str | None


class DatasetBuilder:
    """Builds an immutable, policy-homogeneous, self-sealed research dataset.

    The builder accepts only governed Beta 3A objects. It has no database access,
    does not train models, and cannot modify Decision Engine state.
    """

    def __init__(self, output_root: str | os.PathLike[str], *, clock=None) -> None:
        self.output_root = Path(output_root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _validate_inputs(
        candidates: Sequence[LearningCandidate], rows: Sequence[FeatureRow]
    ) -> tuple[list[str], dict[str, list[FeatureRow]]]:
        errors: list[str] = []
        candidate_ids = [c.learning_candidate_id for c in candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            errors.append("DUPLICATE_LEARNING_CANDIDATE_ID")
        unified_ids = [c.unified_id for c in candidates]
        if len(unified_ids) != len(set(unified_ids)):
            errors.append("DUPLICATE_UNIFIED_ID")

        policy_keys = {
            (c.policy.decision_engine_checksum, c.policy.policy_scope_id, c.policy.policy_scope_hash)
            for c in candidates
        }
        if len(policy_keys) > 1:
            errors.append("MIXED_POLICY_IDENTITY")
        for checksum, _, policy_hash in policy_keys:
            if not _SHA256_RE.fullmatch(checksum):
                errors.append("INVALID_DECISION_ENGINE_CHECKSUM")
            if not policy_hash:
                errors.append("INVALID_POLICY_SCOPE_HASH")

        by_candidate: dict[str, list[FeatureRow]] = {}
        valid_ids = set(candidate_ids)
        for row in rows:
            if row.learning_candidate_id not in valid_ids:
                errors.append("ORPHAN_FEATURE_ROW")
                continue
            by_candidate.setdefault(row.learning_candidate_id, []).append(row)
        for candidate in candidates:
            candidate_rows = by_candidate.get(candidate.learning_candidate_id, [])
            if not candidate_rows:
                errors.append(f"MISSING_FEATURE_ROWS:{candidate.unified_id}")
                continue
            names = [r.feature_name for r in candidate_rows]
            if len(names) != len(set(names)):
                errors.append(f"DUPLICATE_FEATURE_NAME:{candidate.unified_id}")
            for row in candidate_rows:
                if row.unified_id != candidate.unified_id:
                    errors.append(f"FEATURE_UNIFIED_ID_MISMATCH:{candidate.unified_id}")
                if row.feature_snapshot_hash != candidate.feature_snapshot_hash:
                    errors.append(f"FEATURE_SNAPSHOT_HASH_MISMATCH:{candidate.unified_id}")
                if (
                    row.decision_engine_checksum != candidate.policy.decision_engine_checksum
                    or row.policy_scope_id != candidate.policy.policy_scope_id
                    or row.policy_scope_hash != candidate.policy.policy_scope_hash
                ):
                    errors.append(f"FEATURE_POLICY_MISMATCH:{candidate.unified_id}")
                if row.quality == "INVALID":
                    errors.append(f"INVALID_FEATURE:{candidate.unified_id}:{row.feature_name}")
        return sorted(set(errors)), by_candidate

    @staticmethod
    def _dataset_row(candidate: LearningCandidate, rows: Sequence[FeatureRow]) -> dict[str, Any]:
        features = {row.feature_name: row.value for row in sorted(rows, key=lambda item: item.feature_name)}
        feature_quality = {row.feature_name: row.quality for row in sorted(rows, key=lambda item: item.feature_name)}
        material = {
            "learning_candidate_id": candidate.learning_candidate_id,
            "unified_id": candidate.unified_id,
            "feature_snapshot_hash": candidate.feature_snapshot_hash,
            "policy_scope_hash": candidate.policy.policy_scope_hash,
            "features": features,
        }
        return {
            "dataset_row_id": canonical_sha256(material),
            "learning_candidate_id": candidate.learning_candidate_id,
            "unified_id": candidate.unified_id,
            "outcome_status": candidate.outcome_status,
            "realized_r": candidate.realized_r,
            "features": features,
            "feature_quality": feature_quality,
            "feature_snapshot_hash": candidate.feature_snapshot_hash,
            "policy_scope_id": candidate.policy.policy_scope_id,
            "policy_scope_hash": candidate.policy.policy_scope_hash,
            "decision_engine_checksum": candidate.policy.decision_engine_checksum,
        }

    def build(
        self,
        candidates: Iterable[LearningCandidate],
        feature_rows: Iterable[FeatureRow],
        *,
        exclusions: Iterable[Mapping[str, Any]] = (),
        parent_bundle_sha256: str | None = None,
    ) -> DatasetBuildResult:
        candidates_seq = tuple(candidates)
        rows_seq = tuple(feature_rows)
        readiness = classify_dataset_readiness(len(candidates_seq))
        if not readiness.dataset_emission_allowed:
            return DatasetBuildResult(
                status="UNOBSERVABLE",
                readiness_state=readiness.state,
                qualified_samples=len(candidates_seq),
                bundle_path=None,
                dataset_id=None,
                manifest_sha256=None,
                bundle_sha256=None,
                errors=("MINIMUM_SAMPLE_THRESHOLD_NOT_MET",),
            )

        errors, by_candidate = self._validate_inputs(candidates_seq, rows_seq)
        if errors:
            return DatasetBuildResult(
                status="BLOCKED", readiness_state=readiness.state,
                qualified_samples=len(candidates_seq), bundle_path=None, dataset_id=None,
                manifest_sha256=None, bundle_sha256=None, errors=tuple(errors),
            )

        first = candidates_seq[0]
        extractor_identities = sorted({(r.extractor_schema_version, r.extractor_checksum) for r in rows_seq})
        if len(extractor_identities) != 1:
            return DatasetBuildResult(
                status="BLOCKED", readiness_state=readiness.state,
                qualified_samples=len(candidates_seq), bundle_path=None, dataset_id=None,
                manifest_sha256=None, bundle_sha256=None, errors=("MIXED_EXTRACTOR_IDENTITY",),
            )
        extractor_schema_version, extractor_checksum = extractor_identities[0]

        created_at = self.clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        dataset_seed = {
            "created_at": created_at,
            "candidate_ids": sorted(c.learning_candidate_id for c in candidates_seq),
            "policy_scope_hash": first.policy.policy_scope_hash,
            "dataset_schema_version": DATASET_SCHEMA_VERSION,
        }
        dataset_id = f"dataset-{created_at[:10].replace('-', '')}-{canonical_sha256(dataset_seed)[:16]}"
        bundle_dir = self.output_root / dataset_id
        if bundle_dir.exists():
            return DatasetBuildResult(
                status="BLOCKED", readiness_state=readiness.state,
                qualified_samples=len(candidates_seq), bundle_path=None, dataset_id=dataset_id,
                manifest_sha256=None, bundle_sha256=None, errors=("IMMUTABLE_BUNDLE_ALREADY_EXISTS",),
            )
        bundle_dir.mkdir(parents=True, exist_ok=False)

        dataset_rows: list[dict[str, Any]] = []
        lineage_rows: list[dict[str, Any]] = []
        for candidate in sorted(candidates_seq, key=lambda item: item.learning_candidate_id):
            current_rows = by_candidate[candidate.learning_candidate_id]
            dataset_row = self._dataset_row(candidate, current_rows)
            dataset_rows.append(dataset_row)
            feature_lineage = [lineage_record(candidate, row) for row in sorted(current_rows, key=lambda item: item.feature_row_id)]
            lineage_rows.append({
                "dataset_row_id": dataset_row["dataset_row_id"],
                "dataset_id": dataset_id,
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
                "feature_rows": feature_lineage,
            })

        exclusions_rows = [dict(item) for item in exclusions]
        feature_count = sum(len(item["features"]) for item in dataset_rows)
        valid_feature_count = sum(
            1 for item in dataset_rows for quality in item["feature_quality"].values() if quality == "VALID"
        )
        quality_report = {
            "dataset_id": dataset_id,
            "qualified_samples": len(dataset_rows),
            "excluded_samples": len(exclusions_rows),
            "feature_count": feature_count,
            "valid_feature_count": valid_feature_count,
            "coverage": len(dataset_rows) / max(1, len(dataset_rows) + len(exclusions_rows)),
            "feature_completeness": valid_feature_count / max(1, feature_count),
            "quality_score": (valid_feature_count / max(1, feature_count)) * (
                len(dataset_rows) / max(1, len(dataset_rows) + len(exclusions_rows))
            ),
            "readiness_state": readiness.state,
            "emission_allowed": True,
        }

        _write_jsonl(bundle_dir / "training_dataset.jsonl", dataset_rows)
        _write_jsonl(bundle_dir / "exclusions.jsonl", exclusions_rows)
        _write_json(bundle_dir / "quality_report.json", quality_report)
        _write_jsonl(bundle_dir / "lineage_index.jsonl", lineage_rows)
        file_hashes = {name: _file_sha256(bundle_dir / name) for name in BUNDLE_FILES}

        manifest: dict[str, Any] = {
            "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
            "dataset_schema_version": DATASET_SCHEMA_VERSION,
            "dataset_id": dataset_id,
            "created_at": created_at,
            "decision_engine_checksum": first.policy.decision_engine_checksum,
            "policy_scope_id": first.policy.policy_scope_id,
            "policy_scope_hash": first.policy.policy_scope_hash,
            "extractor_schema_version": extractor_schema_version,
            "extractor_checksum": extractor_checksum,
            "burn_in_level": readiness.state,
            "record_count": len(dataset_rows),
            "feature_count": feature_count,
            "parent_bundle_sha256": parent_bundle_sha256,
            "files": {name: {"sha256": file_hashes[name]} for name in BUNDLE_FILES},
        }
        manifest["manifest_sha256"] = hashlib.sha256(_canonical_bytes(manifest)).hexdigest()
        bundle_material = {
            "manifest_sha256": manifest["manifest_sha256"],
            "files": file_hashes,
        }
        manifest["bundle_sha256"] = hashlib.sha256(_canonical_bytes(bundle_material)).hexdigest()
        _write_json(bundle_dir / "dataset.manifest.json", manifest)

        verification = DatasetBundleVerifier().verify(bundle_dir)
        if not verification.valid:
            return DatasetBuildResult(
                status="BLOCKED", readiness_state=readiness.state,
                qualified_samples=len(candidates_seq), bundle_path=str(bundle_dir), dataset_id=dataset_id,
                manifest_sha256=manifest["manifest_sha256"], bundle_sha256=manifest["bundle_sha256"],
                errors=verification.errors,
            )
        return DatasetBuildResult(
            status="RELEASED", readiness_state=readiness.state,
            qualified_samples=len(candidates_seq), bundle_path=str(bundle_dir), dataset_id=dataset_id,
            manifest_sha256=manifest["manifest_sha256"], bundle_sha256=manifest["bundle_sha256"],
        )


class DatasetBundleVerifier:
    def verify(self, bundle_path: str | os.PathLike[str]) -> DatasetVerificationResult:
        bundle_dir = Path(bundle_path)
        errors: list[str] = []
        manifest_path = bundle_dir / "dataset.manifest.json"
        if not manifest_path.is_file():
            return DatasetVerificationResult(False, ("MANIFEST_MISSING",), None, None)
        try:
            manifest = _read_json(manifest_path)
        except (OSError, json.JSONDecodeError):
            return DatasetVerificationResult(False, ("MANIFEST_INVALID_JSON",), None, None)

        for name in BUNDLE_FILES:
            path = bundle_dir / name
            if not path.is_file():
                errors.append(f"FILE_MISSING:{name}")
                continue
            expected = manifest.get("files", {}).get(name, {}).get("sha256")
            actual = _file_sha256(path)
            if expected != actual:
                errors.append(f"FILE_HASH_MISMATCH:{name}")

        manifest_material = {k: v for k, v in manifest.items() if k not in {"manifest_sha256", "bundle_sha256"}}
        actual_manifest_sha = hashlib.sha256(_canonical_bytes(manifest_material)).hexdigest()
        if manifest.get("manifest_sha256") != actual_manifest_sha:
            errors.append("MANIFEST_SHA256_MISMATCH")

        actual_hashes = {
            name: _file_sha256(bundle_dir / name)
            for name in BUNDLE_FILES if (bundle_dir / name).is_file()
        }
        bundle_material = {"manifest_sha256": actual_manifest_sha, "files": actual_hashes}
        actual_bundle_sha = hashlib.sha256(_canonical_bytes(bundle_material)).hexdigest()
        if manifest.get("bundle_sha256") != actual_bundle_sha:
            errors.append("BUNDLE_SHA256_MISMATCH")

        try:
            dataset_rows = _read_jsonl(bundle_dir / "training_dataset.jsonl")
            lineage_rows = _read_jsonl(bundle_dir / "lineage_index.jsonl")
            quality = _read_json(bundle_dir / "quality_report.json")
        except (OSError, json.JSONDecodeError):
            errors.append("BUNDLE_CONTENT_INVALID_JSON")
            return DatasetVerificationResult(False, tuple(sorted(set(errors))), manifest, actual_bundle_sha)

        if manifest.get("record_count") != len(dataset_rows):
            errors.append("RECORD_COUNT_MISMATCH")
        if quality.get("qualified_samples") != len(dataset_rows):
            errors.append("QUALITY_COUNT_MISMATCH")
        if len(lineage_rows) != len(dataset_rows):
            errors.append("LINEAGE_COUNT_MISMATCH")
        dataset_ids = {row.get("dataset_row_id") for row in dataset_rows}
        lineage_ids = {row.get("dataset_row_id") for row in lineage_rows}
        if dataset_ids != lineage_ids:
            errors.append("LINEAGE_DATASET_ROW_MISMATCH")
        for row in dataset_rows:
            required = {
                "dataset_row_id", "learning_candidate_id", "unified_id", "features",
                "feature_snapshot_hash", "policy_scope_id", "policy_scope_hash",
                "decision_engine_checksum",
            }
            if not required.issubset(row):
                errors.append("DATASET_ROW_REQUIRED_FIELD_MISSING")
            if row.get("decision_engine_checksum") != manifest.get("decision_engine_checksum"):
                errors.append("DATASET_POLICY_MISMATCH")
            if row.get("policy_scope_hash") != manifest.get("policy_scope_hash"):
                errors.append("DATASET_POLICY_MISMATCH")
        for row in lineage_rows:
            required = {
                "dataset_row_id", "unified_id", "feature_snapshot_hash", "policy_scope_id",
                "policy_scope_hash", "decision_engine_checksum", "source_identities", "feature_rows",
            }
            if not required.issubset(row):
                errors.append("LINEAGE_REQUIRED_FIELD_MISSING")
            if row.get("decision_engine_checksum") != manifest.get("decision_engine_checksum"):
                errors.append("LINEAGE_POLICY_MISMATCH")
            if row.get("policy_scope_hash") != manifest.get("policy_scope_hash"):
                errors.append("LINEAGE_POLICY_MISMATCH")

        return DatasetVerificationResult(not errors, tuple(sorted(set(errors))), manifest, actual_bundle_sha)
