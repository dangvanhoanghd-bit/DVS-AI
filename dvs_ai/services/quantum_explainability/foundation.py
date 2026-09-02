from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

EXPLANATION_SCHEMA_VERSION = "dvs-quantum-explanation-v1"
EXPLANATION_MANIFEST_VERSION = "dvs-quantum-explanation-manifest-v1"

# Outcome fields are permitted as provenance only. They are never decision evidence.
FORBIDDEN_EVIDENCE_FIELDS = frozenset({
    "outcome_status", "outcome_time", "realized_r", "mfe_r", "mae_r",
    "future_return", "future_price", "resolved_at",
})

DEFAULT_EVIDENCE_FIELDS = (
    "cmf", "rsi", "open_interest", "oi", "funding", "delta", "order_flow",
    "volume", "wyckoff", "structure", "smart_money", "market_regime",
    "trend", "volatility", "confidence", "entry_score", "gate_set",
)


class ExplanationState(str, Enum):
    VERIFIED = "VERIFIED"
    INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
    DATASET_INTEGRITY_BLOCKED = "DATASET_INTEGRITY_BLOCKED"


@dataclass(frozen=True)
class EvidenceItem:
    name: str
    value: Any
    source: str = "first_eligible_snapshot"


@dataclass(frozen=True)
class EvidenceGraphNode:
    node_id: str
    node_type: str
    label: str


@dataclass(frozen=True)
class EvidenceGraphEdge:
    source: str
    target: str
    relation: str


@dataclass(frozen=True)
class DecisionExplanationRecord:
    explanation_id: str
    sample_id: str
    setup_episode_id: str
    candidate_id: str
    activation_evaluation_id: str
    first_evaluation_id: str
    first_eligible_timestamp: str
    symbol: str
    direction: str
    lifecycle_family: str
    cohort: str
    policy_scope_id: str
    policy_scope_hash: str
    decision_engine_checksum: str
    trade_plan_profile_hash: str
    dataset_sha256: str
    source_row_hash: str
    state: str
    observed_evidence: tuple[EvidenceItem, ...]
    missing_evidence: tuple[str, ...]
    graph_nodes: tuple[EvidenceGraphNode, ...]
    graph_edges: tuple[EvidenceGraphEdge, ...]
    limitations: tuple[str, ...]
    record_sha256: str


@dataclass(frozen=True)
class ExplanationBuildResult:
    state: ExplanationState
    dataset_integrity_verified: bool
    explanation_count: int
    verified_count: int
    incomplete_count: int
    records: tuple[DecisionExplanationRecord, ...]
    manifest: Mapping[str, Any]
    optimizer_allowed: bool = False
    recommendation_allowed: bool = False
    shadow_apply_allowed: bool = False
    main_write_authority: bool = False

    def export(self, output_dir: str | Path) -> tuple[Path, Path]:
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        records_path = root / "quantum_decision_explanations.jsonl"
        lines = [canonical_json(asdict(record)) for record in self.records]
        records_bytes = (("\n".join(lines) + "\n") if lines else "").encode("utf-8")
        records_path.write_bytes(records_bytes)

        manifest = dict(self.manifest)
        manifest["explanation_file"] = records_path.name
        manifest["explanation_file_sha256"] = hashlib.sha256(records_bytes).hexdigest()
        unsigned = canonical_json(manifest).encode("utf-8")
        manifest["self_sha256"] = hashlib.sha256(unsigned).hexdigest()
        manifest_path = root / "quantum_decision_explanations.manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return records_path, manifest_path


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _canonical_value(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(v) for v in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite value is forbidden in governed artifacts")
        return format(value, ".12g")
    return value


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(_canonical_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def verify_self_sealed_manifest(path: str | Path) -> tuple[bool, dict[str, Any], str]:
    manifest_path = Path(path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, {}, f"manifest unreadable: {exc}"
    expected = str(payload.get("self_sha256") or "")
    unsigned = dict(payload)
    unsigned.pop("self_sha256", None)
    actual = hashlib.sha256(canonical_json(unsigned).encode("utf-8")).hexdigest()
    if not expected or actual != expected:
        return False, payload, "manifest self checksum mismatch"
    return True, payload, "verified"


def verify_dataset_bundle(dataset_path: str | Path, manifest_path: str | Path) -> tuple[bool, dict[str, Any], str]:
    ok, manifest, detail = verify_self_sealed_manifest(manifest_path)
    if not ok:
        return False, manifest, detail
    dataset = Path(dataset_path)
    if not dataset.exists():
        return False, manifest, "dataset file missing"
    actual = hashlib.sha256(dataset.read_bytes()).hexdigest()
    if actual != str(manifest.get("dataset_sha256") or ""):
        return False, manifest, "dataset checksum mismatch"
    if manifest.get("dataset_file") and manifest.get("dataset_file") != dataset.name:
        return False, manifest, "dataset filename does not match manifest"
    if manifest.get("readiness_state") == "DATA_INTEGRITY_BLOCKED":
        return False, manifest, "source dataset integrity is blocked"
    findings = manifest.get("integrity_findings", [])
    if findings and any(not bool(item.get("passed")) for item in findings if isinstance(item, Mapping)):
        return False, manifest, "source dataset contains failed integrity findings"
    return True, manifest, "verified"


class QuantumExplainabilityFoundation:
    """Build deterministic, non-causal explanations from a sealed research dataset.

    This boundary has no optimizer, recommendation, SHADOW-write, MAIN-write, or
    exchange execution path. It never recomputes features and never treats outcome
    fields as evidence for a historical decision.
    """

    def __init__(
        self,
        dataset_path: str | Path,
        manifest_path: str | Path,
        *,
        expected_evidence_fields: Sequence[str] = DEFAULT_EVIDENCE_FIELDS,
    ) -> None:
        self.dataset_path = Path(dataset_path)
        self.manifest_path = Path(manifest_path)
        cleaned = tuple(dict.fromkeys(str(x).strip() for x in expected_evidence_fields if str(x).strip()))
        forbidden = sorted(set(cleaned) & FORBIDDEN_EVIDENCE_FIELDS)
        if forbidden:
            raise ValueError(f"Outcome/future fields cannot be configured as evidence: {forbidden}")
        self.expected_evidence_fields = cleaned

    def build(self) -> ExplanationBuildResult:
        verified, dataset_manifest, detail = verify_dataset_bundle(self.dataset_path, self.manifest_path)
        if not verified:
            return self._blocked(dataset_manifest, detail)

        dataset_sha256 = str(dataset_manifest["dataset_sha256"])
        records: list[DecisionExplanationRecord] = []
        for line_number, raw_line in enumerate(self.dataset_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw_line.strip():
                continue
            try:
                episode = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                return self._blocked(dataset_manifest, f"invalid JSONL at line {line_number}: {exc}")
            if not isinstance(episode, dict):
                return self._blocked(dataset_manifest, f"dataset row {line_number} is not an object")
            records.append(self._explain_episode(episode, dataset_sha256))

        verified_count = sum(r.state == ExplanationState.VERIFIED.value for r in records)
        incomplete_count = sum(r.state == ExplanationState.INCOMPLETE_EVIDENCE.value for r in records)
        overall = ExplanationState.VERIFIED if incomplete_count == 0 else ExplanationState.INCOMPLETE_EVIDENCE
        manifest = self._manifest_base(overall, dataset_manifest, detail)
        manifest.update({
            "explanation_count": len(records),
            "verified_count": verified_count,
            "incomplete_count": incomplete_count,
            "expected_evidence_fields": list(self.expected_evidence_fields),
            "forbidden_evidence_fields": sorted(FORBIDDEN_EVIDENCE_FIELDS),
            "safety_boundary": {
                "decision_engine_frozen": True,
                "feature_recomputation": False,
                "future_data_allowed": False,
                "causal_claims_allowed": False,
                "optimizer_authority": False,
                "recommendation_authority": False,
                "shadow_write_authority": False,
                "main_write_authority": False,
                "exchange_order_capability": False,
            },
        })
        return ExplanationBuildResult(
            state=overall,
            dataset_integrity_verified=True,
            explanation_count=len(records),
            verified_count=verified_count,
            incomplete_count=incomplete_count,
            records=tuple(records),
            manifest=manifest,
        )

    def _blocked(self, dataset_manifest: Mapping[str, Any], detail: str) -> ExplanationBuildResult:
        manifest = self._manifest_base(ExplanationState.DATASET_INTEGRITY_BLOCKED, dataset_manifest, detail)
        return ExplanationBuildResult(
            state=ExplanationState.DATASET_INTEGRITY_BLOCKED,
            dataset_integrity_verified=False,
            explanation_count=0,
            verified_count=0,
            incomplete_count=0,
            records=(),
            manifest=manifest,
        )

    def _explain_episode(self, episode: Mapping[str, Any], dataset_sha256: str) -> DecisionExplanationRecord:
        observed: list[EvidenceItem] = []
        missing: list[str] = []
        for name in self.expected_evidence_fields:
            value = episode.get(name)
            if value is None or value == "" or value == [] or value == {}:
                missing.append(name)
            else:
                observed.append(EvidenceItem(name=name, value=value))

        # Decision trace nodes are provenance, not newly inferred evidence.
        nodes: list[EvidenceGraphNode] = []
        edges: list[EvidenceGraphEdge] = []
        for index, item in enumerate(observed):
            node_id = f"E{index + 1}"
            nodes.append(EvidenceGraphNode(node_id=node_id, node_type="OBSERVED_EVIDENCE", label=item.name))
        gate_id = "GATE"
        decision_id = "DECISION"
        nodes.append(EvidenceGraphNode(node_id=gate_id, node_type="TRACE_GATE", label="recorded decision path"))
        nodes.append(EvidenceGraphNode(
            node_id=decision_id,
            node_type="RECORDED_DECISION",
            label=str(episode.get("direction") or "UNKNOWN").upper(),
        ))
        for index in range(len(observed)):
            edges.append(EvidenceGraphEdge(source=f"E{index + 1}", target=gate_id, relation="observed_before_decision"))
        edges.append(EvidenceGraphEdge(source=gate_id, target=decision_id, relation="recorded_trace"))

        limitations = [
            "Descriptive decision trace only; no causal claim.",
            "No feature is recomputed and no future/outcome field is used as decision evidence.",
        ]
        if missing:
            limitations.append("Expected evidence fields absent from Research Dataset v1: " + ", ".join(missing))
        state = ExplanationState.INCOMPLETE_EVIDENCE if missing else ExplanationState.VERIFIED

        base = {
            "schema_version": EXPLANATION_SCHEMA_VERSION,
            "sample_id": str(episode.get("sample_id") or ""),
            "setup_episode_id": str(episode.get("setup_episode_id") or ""),
            "candidate_id": str(episode.get("candidate_id") or ""),
            "activation_evaluation_id": str(episode.get("activation_evaluation_id") or ""),
            "first_evaluation_id": str(episode.get("first_evaluation_id") or ""),
            "first_eligible_timestamp": str(episode.get("first_eligible_timestamp") or ""),
            "symbol": str(episode.get("symbol") or "UNKNOWN"),
            "direction": str(episode.get("direction") or "UNKNOWN").upper(),
            "lifecycle_family": str(episode.get("lifecycle_family") or "UNKNOWN"),
            "cohort": str(episode.get("cohort") or "UNKNOWN"),
            "policy_scope_id": str(episode.get("policy_scope_id") or ""),
            "policy_scope_hash": str(episode.get("policy_scope_hash") or ""),
            "decision_engine_checksum": str(episode.get("decision_engine_checksum") or ""),
            "trade_plan_profile_hash": str(episode.get("trade_plan_profile_hash") or ""),
            "dataset_sha256": dataset_sha256,
            "source_row_hash": str(episode.get("source_row_hash") or ""),
            "state": state.value,
            "observed_evidence": [asdict(x) for x in observed],
            "missing_evidence": missing,
            "graph_nodes": [asdict(x) for x in nodes],
            "graph_edges": [asdict(x) for x in edges],
            "limitations": limitations,
        }
        record_hash = canonical_hash(base)
        explanation_id = f"QEX-{hashlib.sha256((base['sample_id'] + record_hash).encode()).hexdigest()[:24].upper()}"
        return DecisionExplanationRecord(
            explanation_id=explanation_id,
            sample_id=base["sample_id"],
            setup_episode_id=base["setup_episode_id"],
            candidate_id=base["candidate_id"],
            activation_evaluation_id=base["activation_evaluation_id"],
            first_evaluation_id=base["first_evaluation_id"],
            first_eligible_timestamp=base["first_eligible_timestamp"],
            symbol=base["symbol"],
            direction=base["direction"],
            lifecycle_family=base["lifecycle_family"],
            cohort=base["cohort"],
            policy_scope_id=base["policy_scope_id"],
            policy_scope_hash=base["policy_scope_hash"],
            decision_engine_checksum=base["decision_engine_checksum"],
            trade_plan_profile_hash=base["trade_plan_profile_hash"],
            dataset_sha256=dataset_sha256,
            source_row_hash=base["source_row_hash"],
            state=state.value,
            observed_evidence=tuple(observed),
            missing_evidence=tuple(missing),
            graph_nodes=tuple(nodes),
            graph_edges=tuple(edges),
            limitations=tuple(limitations),
            record_sha256=record_hash,
        )

    def _manifest_base(
        self,
        state: ExplanationState,
        dataset_manifest: Mapping[str, Any],
        verification_detail: str,
    ) -> dict[str, Any]:
        return {
            "manifest_version": EXPLANATION_MANIFEST_VERSION,
            "explanation_schema_version": EXPLANATION_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "state": state.value,
            "dataset_file": self.dataset_path.name,
            "dataset_manifest_file": self.manifest_path.name,
            "dataset_sha256": dataset_manifest.get("dataset_sha256"),
            "dataset_manifest_self_sha256": dataset_manifest.get("self_sha256"),
            "dataset_integrity_detail": verification_detail,
            "qg_contract": "QG-01..QG-16",
            "first_eligible_plan_required": True,
        }


def verify_explanation_bundle(records_path: str | Path, manifest_path: str | Path) -> tuple[bool, str]:
    ok, manifest, detail = verify_self_sealed_manifest(manifest_path)
    if not ok:
        return False, detail
    records = Path(records_path)
    if not records.exists():
        return False, "explanation file missing"
    if manifest.get("explanation_file") and manifest.get("explanation_file") != records.name:
        return False, "explanation filename does not match manifest"
    actual = hashlib.sha256(records.read_bytes()).hexdigest()
    if actual != str(manifest.get("explanation_file_sha256") or ""):
        return False, "explanation file checksum mismatch"
    for line_number, raw_line in enumerate(records.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            return False, f"invalid explanation JSONL at line {line_number}: {exc}"
        expected = str(row.get("record_sha256") or "")
        unsigned = dict(row)
        unsigned.pop("record_sha256", None)
        unsigned.pop("explanation_id", None)
        unsigned["schema_version"] = EXPLANATION_SCHEMA_VERSION
        actual_record = canonical_hash(unsigned)
        if expected != actual_record:
            return False, f"record checksum mismatch at line {line_number}"
    return True, "verified"
