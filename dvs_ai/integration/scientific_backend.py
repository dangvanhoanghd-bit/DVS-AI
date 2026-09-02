from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .models import (
    BackendAvailability,
    BackendSource,
    CertificationSummary,
    DecisionTrace,
    ExplainabilitySummary,
    ModelRegistrySummary,
    ModelVersionSummary,
    EvidenceSummary,
    ReadinessSummary,
    SafetyBoundary,
    ScientificBackendStatus,
    ScientificDataState,
    ScientificSummary,
    ValidationSummary,
)


@dataclass(frozen=True, slots=True)
class _RootResolution:
    configured_root: Path | None
    active_root: Path | None
    source: BackendSource
    fallback_reason: str = ""
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScientificDashboardPayload:
    """Immutable, internally consistent scientific dashboard snapshot."""

    generation: int
    collected_monotonic: float
    status: ScientificBackendStatus
    summary: ScientificSummary
    active_root: str
    json_reads: int


@dataclass(slots=True)
class RootDiscoveryCache:
    """Bounded root-resolution cache with TTL and filesystem-signature invalidation."""

    ttl_seconds: float = 5.0
    resolution: _RootResolution | None = None
    signature: tuple[object, ...] = ()
    stored_monotonic: float = 0.0

    def get(self, signature: tuple[object, ...], now: float) -> _RootResolution | None:
        if self.resolution is None:
            return None
        if signature != self.signature:
            return None
        if now - self.stored_monotonic > max(0.0, float(self.ttl_seconds)):
            return None
        return self.resolution

    def put(self, resolution: _RootResolution, signature: tuple[object, ...], now: float) -> None:
        self.resolution = resolution
        self.signature = signature
        self.stored_monotonic = now

    def invalidate(self) -> None:
        self.resolution = None
        self.signature = ()
        self.stored_monotonic = 0.0


class ScientificBackendBridge:
    """Observe-only bridge between the desktop GUI and scientific backend artifacts.

    It never imports backend execution modules and never mutates backend state.
    When a configured backend root fails validation, a packaged snapshot may be
    used, but that fallback is always surfaced through source metadata and reason
    codes; it is never silent.
    """

    ENV_ROOT = "DVS_SCIENTIFIC_BACKEND_ROOT"
    REQUIRED_FILES = ("BUILD_VERIFICATION.json", "SAFETY_BOUNDARY.json")

    def __init__(self, backend_root: str | Path | None = None, *, app_root: str | Path | None = None):
        self._explicit_root = Path(backend_root).expanduser().resolve() if backend_root else None
        self._app_root = Path(app_root).expanduser().resolve() if app_root else Path.cwd().resolve()
        self._root_cache = RootDiscoveryCache()

    @staticmethod
    def _path_signature(path: Path, names: tuple[str, ...]) -> tuple[object, ...]:
        values: list[object] = [str(path)]
        try:
            root_stat = path.stat()
            values.extend((True, root_stat.st_mtime_ns, root_stat.st_ino))
        except OSError:
            values.extend((False, None, None))
        for name in names:
            target = path / name
            try:
                stat = target.stat()
                values.extend((name, True, stat.st_mtime_ns, stat.st_size, stat.st_ino))
            except OSError:
                values.extend((name, False, None, None, None))
        return tuple(values)

    def _root_environment_signature(self) -> tuple[object, ...]:
        configured = self._configured_root()
        candidates = ((configured,) if configured is not None else ()) + self._snapshot_roots()
        names = self.REQUIRED_FILES + ("BACKEND_METADATA.json",)
        signature: list[object] = [str(configured) if configured is not None else ""]
        for root in candidates:
            signature.extend(self._path_signature(root, names))
        return tuple(signature)

    def resolve_root_cached(self) -> _RootResolution:
        now = time.monotonic()
        signature = self._root_environment_signature()
        cached = self._root_cache.get(signature, now)
        if cached is not None:
            return cached
        resolution = self._resolve_root()
        # Recompute after probing so a root replacement during probe cannot be cached
        # under the old signature.
        final_signature = self._root_environment_signature()
        self._root_cache.put(resolution, final_signature, now)
        return resolution

    def _configured_root(self) -> Path | None:
        if self._explicit_root is not None:
            return self._explicit_root
        env_root = os.getenv(self.ENV_ROOT, "").strip()
        return Path(env_root).expanduser().resolve() if env_root else None

    def _snapshot_roots(self) -> tuple[Path, ...]:
        roots = (
            self._app_root / "scientific_backend_snapshot",
            self._app_root / "01_PRODUCT",
            self._app_root,
        )
        unique: list[Path] = []
        for root in roots:
            if root not in unique:
                unique.append(root)
        return tuple(unique)

    @staticmethod
    def _read_json(path: Path) -> Mapping[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Expected object in {path.name}")
        return payload

    def _probe_root(self, root: Path) -> tuple[bool, str, str]:
        if not root.exists():
            return False, "CONFIGURED_ROOT_NOT_FOUND", f"Root does not exist: {root}"
        if not root.is_dir():
            return False, "CONFIGURED_ROOT_NOT_READABLE", f"Root is not a directory: {root}"
        missing = [name for name in self.REQUIRED_FILES if not (root / name).is_file()]
        if missing:
            return False, "CONFIGURED_ROOT_STATUS_FILES_MISSING", f"Missing required files: {', '.join(missing)}"
        try:
            for name in self.REQUIRED_FILES:
                self._read_json(root / name)
            metadata_path = root / "BACKEND_METADATA.json"
            if metadata_path.is_file():
                self._read_json(metadata_path)
        except json.JSONDecodeError as exc:
            return False, "CONFIGURED_ROOT_JSON_INVALID", f"Invalid JSON: {exc}"
        except (OSError, ValueError) as exc:
            return False, "CONFIGURED_ROOT_NOT_READABLE", str(exc)
        return True, "", ""

    def _resolve_root(self) -> _RootResolution:
        configured = self._configured_root()
        configured_code = ""
        configured_detail = ""
        if configured is not None:
            ok, configured_code, configured_detail = self._probe_root(configured)
            if ok:
                return _RootResolution(configured, configured, BackendSource.CONFIGURED_ROOT)

        for snapshot in self._snapshot_roots():
            ok, _, _ = self._probe_root(snapshot)
            if ok:
                if configured is not None:
                    return _RootResolution(
                        configured_root=configured,
                        active_root=snapshot,
                        source=BackendSource.PACKAGED_SNAPSHOT,
                        fallback_reason=configured_detail,
                        reason_codes=(configured_code, "CONFIGURED_ROOT_FALLBACK_USED"),
                    )
                return _RootResolution(None, snapshot, BackendSource.PACKAGED_SNAPSHOT)

        if configured is not None:
            return _RootResolution(
                configured_root=configured,
                active_root=None,
                source=BackendSource.NONE,
                fallback_reason=configured_detail,
                reason_codes=(configured_code, "PACKAGED_SNAPSHOT_NOT_AVAILABLE"),
            )
        return _RootResolution(
            configured_root=None,
            active_root=None,
            source=BackendSource.NONE,
            reason_codes=("BACKEND_STATUS_FILES_NOT_FOUND",),
        )


    def _active_root(self) -> Path | None:
        return self._resolve_root().active_root

    def _read_optional_artifact(self, filename: str) -> tuple[Mapping[str, Any] | None, tuple[str, ...]]:
        root = self._active_root()
        if root is None:
            return None, ("SCIENTIFIC_BACKEND_UNAVAILABLE",)
        path = root / filename
        if not path.is_file():
            return None, (f"{path.stem}_NOT_AVAILABLE",)
        try:
            return self._read_json(path), ()
        except (OSError, ValueError, json.JSONDecodeError):
            return None, (f"{path.stem}_INVALID",)

    @staticmethod
    def _data_state(value: object) -> ScientificDataState:
        normalized = str(value or "UNAVAILABLE").upper()
        if normalized in {"VALID", "VERIFIED", "READY", "CERTIFIED", "PASS", "PASSED"}:
            return ScientificDataState.VALID
        if normalized in {"STALE", "EXPIRED"}:
            return ScientificDataState.STALE
        if normalized in {"NOT_READY", "PENDING", "BLOCKED", "FAILED", "REJECTED"}:
            return ScientificDataState.NOT_READY
        return ScientificDataState.UNAVAILABLE

    def get_validation_summary(self) -> ValidationSummary:
        payload, reasons = self._read_optional_artifact("VALIDATION_SUMMARY.json")
        if payload is None:
            return ValidationSummary(ScientificDataState.UNAVAILABLE, reason_codes=reasons)
        status = str(payload.get("status", payload.get("validation_status", "UNAVAILABLE"))).upper()
        return ValidationSummary(
            state=self._data_state(status),
            validation_status=status,
            last_validation_at=str(payload.get("last_validation_at", payload.get("validated_at", ""))),
            validation_count=int(payload.get("validation_count", payload.get("count", 0)) or 0),
            reason_codes=tuple(str(x) for x in payload.get("reason_codes", ()) if x),
        )

    def get_evidence_summary(self) -> EvidenceSummary:
        payload, reasons = self._read_optional_artifact("EVIDENCE_STATUS.json")
        if payload is None:
            return EvidenceSummary(ScientificDataState.UNAVAILABLE, reason_codes=reasons)
        status = str(payload.get("status", payload.get("evidence_status", "UNAVAILABLE"))).upper()
        return EvidenceSummary(
            state=self._data_state(status),
            evidence_status=status,
            evidence_count=int(payload.get("evidence_count", payload.get("count", 0)) or 0),
            last_evidence_at=str(payload.get("last_evidence_at", payload.get("updated_at", ""))),
            reason_codes=tuple(str(x) for x in payload.get("reason_codes", ()) if x),
        )

    def get_readiness_summary(self) -> ReadinessSummary:
        payload, reasons = self._read_optional_artifact("READINESS_SUMMARY.json")
        if payload is None:
            return ReadinessSummary(ScientificDataState.UNAVAILABLE, reason_codes=reasons)
        level = str(payload.get("readiness_level", payload.get("status", "UNAVAILABLE"))).upper()
        score = payload.get("readiness_score", payload.get("score"))
        return ReadinessSummary(
            state=self._data_state(level),
            readiness_level=level,
            readiness_score=float(score) if score is not None else None,
            recommendation=str(payload.get("recommendation", "")),
            reason_codes=tuple(str(x) for x in payload.get("reason_codes", ()) if x),
        )

    def get_certification_summary(self) -> CertificationSummary:
        payload, reasons = self._read_optional_artifact("CERTIFICATION_SUMMARY.json")
        if payload is None:
            return CertificationSummary(ScientificDataState.UNAVAILABLE, reason_codes=reasons)
        status = str(payload.get("certification_status", payload.get("status", "UNAVAILABLE"))).upper()
        return CertificationSummary(
            state=self._data_state(status),
            certification_status=status,
            certificate_id=str(payload.get("certificate_id", "")),
            certified_at=str(payload.get("certified_at", "")),
            reason_codes=tuple(str(x) for x in payload.get("reason_codes", ()) if x),
        )

    def get_explainability_summary(self) -> ExplainabilitySummary:
        payload, reasons = self._read_optional_artifact("EXPLAINABILITY_SUMMARY.json")
        if payload is None:
            return ExplainabilitySummary(ScientificDataState.UNAVAILABLE, reason_codes=reasons)
        status = str(payload.get("status", "UNAVAILABLE")).upper()
        confidence = payload.get("confidence")
        reason_codes = tuple(str(x) for x in payload.get("reason_codes", ()) if x)
        evidence_refs = tuple(str(x) for x in payload.get("evidence_refs", ()) if x)
        extra_reasons: list[str] = list(reason_codes)
        validation_ref = str(payload.get("validation_ref", ""))
        if not evidence_refs:
            extra_reasons.append("EXPLAINABILITY_EVIDENCE_REFS_EMPTY")
        if not validation_ref:
            extra_reasons.append("EXPLAINABILITY_VALIDATION_REF_MISSING")
        return ExplainabilitySummary(
            state=self._data_state(status),
            status=status,
            decision_id=str(payload.get("decision_id", "")),
            generated_at=str(payload.get("generated_at", "")),
            decision_type=str(payload.get("decision_type", "")),
            confidence=float(confidence) if confidence is not None else None,
            reason_codes=tuple(extra_reasons),
            evidence_refs=evidence_refs,
            validation_ref=validation_ref,
            model_version=str(payload.get("model_version", "")),
        )

    def get_decision_trace(self) -> DecisionTrace:
        summary = self.get_explainability_summary()
        if summary.state is ScientificDataState.UNAVAILABLE:
            return DecisionTrace(
                state=ScientificDataState.UNAVAILABLE,
                decision_id=summary.decision_id,
                reason_codes=summary.reason_codes,
            )
        stages = tuple(
            stage for stage in (
                f"EVIDENCE:{len(summary.evidence_refs)}",
                f"VALIDATION:{summary.validation_ref or 'MISSING'}",
                f"DECISION:{summary.decision_type or 'UNKNOWN'}",
                f"REASONS:{len(summary.reason_codes)}",
            )
        )
        return DecisionTrace(
            state=summary.state,
            decision_id=summary.decision_id,
            stages=stages,
            reason_codes=summary.reason_codes,
        )

    @staticmethod
    def _parse_model_version(payload: Mapping[str, Any]) -> ModelVersionSummary:
        model_id = str(payload.get("model_id", "")).strip()
        version = str(payload.get("version", payload.get("model_version", ""))).strip()
        reasons = [str(x) for x in payload.get("reason_codes", ()) if x]
        if not model_id:
            reasons.append("MODEL_ID_MISSING")
        if not version:
            reasons.append("MODEL_VERSION_MISSING")
        return ModelVersionSummary(
            model_id=model_id,
            version=version,
            training_timestamp=str(payload.get("training_timestamp", payload.get("trained_at", ""))),
            registry_status=str(payload.get("registry_status", payload.get("status", "UNAVAILABLE"))).upper(),
            maturity_level=str(payload.get("maturity_level", payload.get("maturity", "UNAVAILABLE"))).upper(),
            certified=bool(payload.get("certified", False)),
            certificate_id=str(payload.get("certificate_id", "")),
            reason_codes=tuple(dict.fromkeys(reasons)),
        )

    def get_registry_summary(self) -> ModelRegistrySummary:
        payload, reasons = self._read_optional_artifact("MODEL_REGISTRY.json")
        if payload is None:
            return ModelRegistrySummary(ScientificDataState.UNAVAILABLE, reason_codes=reasons)
        status = str(payload.get("registry_status", payload.get("status", "UNAVAILABLE"))).upper()
        raw_models = payload.get("models", payload.get("model_history", ()))
        if not isinstance(raw_models, list):
            return ModelRegistrySummary(
                ScientificDataState.UNAVAILABLE,
                registry_status="UNAVAILABLE",
                reason_codes=("MODEL_REGISTRY_MODELS_INVALID",),
            )
        history = tuple(self._parse_model_version(item) for item in raw_models if isinstance(item, dict))
        current_payload = payload.get("current_model")
        current = self._parse_model_version(current_payload) if isinstance(current_payload, dict) else None
        extra = [str(x) for x in payload.get("reason_codes", ()) if x]
        if current is None:
            current_id = str(payload.get("current_model_id", "")).strip()
            current_version = str(payload.get("current_model_version", "")).strip()
            if current_id or current_version:
                current = next((m for m in history if m.model_id == current_id and (not current_version or m.version == current_version)), None)
            if current is None:
                extra.append("CURRENT_MODEL_NOT_AVAILABLE")
        if not history:
            extra.append("MODEL_HISTORY_EMPTY")
        return ModelRegistrySummary(
            state=self._data_state(status),
            registry_status=status,
            current_model=current,
            model_history=history,
            generated_at=str(payload.get("generated_at", payload.get("updated_at", ""))),
            reason_codes=tuple(dict.fromkeys(extra)),
        )

    def get_current_model(self) -> ModelVersionSummary | None:
        return self.get_registry_summary().current_model

    def get_model_history(self) -> tuple[ModelVersionSummary, ...]:
        return self.get_registry_summary().model_history

    def get_scientific_summary(self) -> ScientificSummary:
        return ScientificSummary(
            validation=self.get_validation_summary(),
            evidence=self.get_evidence_summary(),
            readiness=self.get_readiness_summary(),
            certification=self.get_certification_summary(),
            explainability=self.get_explainability_summary(),
            decision_trace=self.get_decision_trace(),
            registry=self.get_registry_summary(),
        )

    @staticmethod
    def _decision_trace_from_explainability(summary: ExplainabilitySummary) -> DecisionTrace:
        if summary.state is ScientificDataState.UNAVAILABLE:
            return DecisionTrace(
                state=ScientificDataState.UNAVAILABLE,
                decision_id=summary.decision_id,
                reason_codes=summary.reason_codes,
            )
        return DecisionTrace(
            state=summary.state,
            decision_id=summary.decision_id,
            stages=(
                f"EVIDENCE:{len(summary.evidence_refs)}",
                f"VALIDATION:{summary.validation_ref or 'MISSING'}",
                f"DECISION:{summary.decision_type or 'UNKNOWN'}",
                f"REASONS:{len(summary.reason_codes)}",
            ),
            reason_codes=summary.reason_codes,
        )

    def _status_from_loaded(
        self,
        resolution: _RootResolution,
        build: Mapping[str, Any],
        safety_payload: Mapping[str, Any],
        metadata: Mapping[str, Any],
    ) -> ScientificBackendStatus:
        root = resolution.active_root
        assert root is not None
        reasons = list(resolution.reason_codes)
        safety = SafetyBoundary.from_mapping(safety_payload)
        build_valid = bool(build.get("build_valid", False))
        compile_passed = bool(build.get("compile", False))
        tests_successful = bool(build.get("tests_successful", False))
        cli_help_available = bool(build.get("cli_help_available", False))
        tests_run = int(build.get("tests_run", 0) or 0)
        if not build_valid:
            reasons.append("BUILD_NOT_VERIFIED")
        if not compile_passed:
            reasons.append("COMPILE_NOT_VERIFIED")
        if not tests_successful:
            reasons.append("TESTS_NOT_VERIFIED")
        if safety.enforcement != "FAIL_CLOSED":
            reasons.append("SAFETY_NOT_FAIL_CLOSED")
        if safety.live != "NOT_AUTHORIZED":
            reasons.append("LIVE_BOUNDARY_UNEXPECTED")
        if safety.deployment != "DISCONNECTED":
            reasons.append("DEPLOYMENT_BOUNDARY_UNEXPECTED")
        availability = BackendAvailability.AVAILABLE if not reasons else BackendAvailability.DEGRADED
        return ScientificBackendStatus(
            engine_name=str(metadata.get("engine_name", "DVS AI Scientific Backend")),
            engine_version=str(metadata.get("engine_version", "UNKNOWN")),
            availability=availability,
            build_valid=build_valid,
            compile_passed=compile_passed,
            tests_run=tests_run,
            tests_successful=tests_successful,
            cli_help_available=cli_help_available,
            safety=safety,
            integration_mode=str(metadata.get("integration_mode", "EXTERNAL_STATUS_ARTIFACTS")),
            source_path=str(root),
            backend_source=resolution.source,
            configured_root=str(resolution.configured_root or ""),
            active_root=str(root),
            fallback_reason=resolution.fallback_reason,
            reason_codes=tuple(dict.fromkeys(reasons)),
        )

    def build_dashboard_payload(self, generation: int) -> ScientificDashboardPayload:
        """Build one complete snapshot with one root resolution and one read per artifact."""
        resolution = self.resolve_root_cached()
        root = resolution.active_root
        if root is None:
            status = self._unavailable(
                resolution.reason_codes,
                detail=resolution.fallback_reason,
                configured_root=resolution.configured_root,
            )
            unavailable = ScientificDataState.UNAVAILABLE
            summary = ScientificSummary(
                validation=ValidationSummary(unavailable, reason_codes=("SCIENTIFIC_BACKEND_UNAVAILABLE",)),
                evidence=EvidenceSummary(unavailable, reason_codes=("SCIENTIFIC_BACKEND_UNAVAILABLE",)),
                readiness=ReadinessSummary(unavailable, reason_codes=("SCIENTIFIC_BACKEND_UNAVAILABLE",)),
                certification=CertificationSummary(unavailable, reason_codes=("SCIENTIFIC_BACKEND_UNAVAILABLE",)),
                explainability=ExplainabilitySummary(unavailable, reason_codes=("SCIENTIFIC_BACKEND_UNAVAILABLE",)),
                decision_trace=DecisionTrace(unavailable, reason_codes=("SCIENTIFIC_BACKEND_UNAVAILABLE",)),
                registry=ModelRegistrySummary(unavailable, reason_codes=("SCIENTIFIC_BACKEND_UNAVAILABLE",)),
            )
            return ScientificDashboardPayload(int(generation), time.monotonic(), status, summary, "", 0)

        filenames = (
            "BUILD_VERIFICATION.json", "SAFETY_BOUNDARY.json", "BACKEND_METADATA.json",
            "VALIDATION_SUMMARY.json", "EVIDENCE_STATUS.json", "READINESS_SUMMARY.json",
            "CERTIFICATION_SUMMARY.json", "EXPLAINABILITY_SUMMARY.json", "MODEL_REGISTRY.json",
        )
        loaded: dict[str, Mapping[str, Any] | None] = {}
        reads = 0
        for filename in filenames:
            path = root / filename
            if not path.is_file():
                loaded[filename] = None
                continue
            try:
                loaded[filename] = self._read_json(path)
                reads += 1
            except (OSError, ValueError, json.JSONDecodeError):
                loaded[filename] = None

        build = loaded["BUILD_VERIFICATION.json"] or {}
        safety_payload = loaded["SAFETY_BOUNDARY.json"] or {}
        metadata = loaded["BACKEND_METADATA.json"] or {}
        status = self._status_from_loaded(resolution, build, safety_payload, metadata)

        def missing(name: str) -> tuple[str, ...]:
            return (f"{Path(name).stem}_NOT_AVAILABLE",)

        validation_payload = loaded["VALIDATION_SUMMARY.json"]
        if validation_payload is None:
            validation = ValidationSummary(ScientificDataState.UNAVAILABLE, reason_codes=missing("VALIDATION_SUMMARY.json"))
        else:
            value = str(validation_payload.get("status", validation_payload.get("validation_status", "UNAVAILABLE"))).upper()
            validation = ValidationSummary(self._data_state(value), value, str(validation_payload.get("last_validation_at", validation_payload.get("validated_at", ""))), int(validation_payload.get("validation_count", validation_payload.get("count", 0)) or 0), tuple(str(x) for x in validation_payload.get("reason_codes", ()) if x))

        evidence_payload = loaded["EVIDENCE_STATUS.json"]
        if evidence_payload is None:
            evidence = EvidenceSummary(ScientificDataState.UNAVAILABLE, reason_codes=missing("EVIDENCE_STATUS.json"))
        else:
            value = str(evidence_payload.get("status", evidence_payload.get("evidence_status", "UNAVAILABLE"))).upper()
            evidence = EvidenceSummary(self._data_state(value), value, int(evidence_payload.get("evidence_count", evidence_payload.get("count", 0)) or 0), str(evidence_payload.get("last_evidence_at", evidence_payload.get("updated_at", ""))), tuple(str(x) for x in evidence_payload.get("reason_codes", ()) if x))

        readiness_payload = loaded["READINESS_SUMMARY.json"]
        if readiness_payload is None:
            readiness = ReadinessSummary(ScientificDataState.UNAVAILABLE, reason_codes=missing("READINESS_SUMMARY.json"))
        else:
            value = str(readiness_payload.get("readiness_level", readiness_payload.get("status", "UNAVAILABLE"))).upper()
            score = readiness_payload.get("readiness_score", readiness_payload.get("score"))
            readiness = ReadinessSummary(self._data_state(value), value, float(score) if score is not None else None, str(readiness_payload.get("recommendation", "")), tuple(str(x) for x in readiness_payload.get("reason_codes", ()) if x))

        certification_payload = loaded["CERTIFICATION_SUMMARY.json"]
        if certification_payload is None:
            certification = CertificationSummary(ScientificDataState.UNAVAILABLE, reason_codes=missing("CERTIFICATION_SUMMARY.json"))
        else:
            value = str(certification_payload.get("certification_status", certification_payload.get("status", "UNAVAILABLE"))).upper()
            certification = CertificationSummary(self._data_state(value), value, str(certification_payload.get("certificate_id", "")), str(certification_payload.get("certified_at", "")), tuple(str(x) for x in certification_payload.get("reason_codes", ()) if x))

        explainability_payload = loaded["EXPLAINABILITY_SUMMARY.json"]
        if explainability_payload is None:
            explainability = ExplainabilitySummary(ScientificDataState.UNAVAILABLE, reason_codes=missing("EXPLAINABILITY_SUMMARY.json"))
        else:
            value = str(explainability_payload.get("status", "UNAVAILABLE")).upper()
            refs = tuple(str(x) for x in explainability_payload.get("evidence_refs", ()) if x)
            reasons = [str(x) for x in explainability_payload.get("reason_codes", ()) if x]
            validation_ref = str(explainability_payload.get("validation_ref", ""))
            if not refs:
                reasons.append("EXPLAINABILITY_EVIDENCE_REFS_EMPTY")
            if not validation_ref:
                reasons.append("EXPLAINABILITY_VALIDATION_REF_MISSING")
            confidence = explainability_payload.get("confidence")
            explainability = ExplainabilitySummary(self._data_state(value), value, str(explainability_payload.get("decision_id", "")), str(explainability_payload.get("generated_at", "")), str(explainability_payload.get("decision_type", "")), float(confidence) if confidence is not None else None, tuple(reasons), refs, validation_ref, str(explainability_payload.get("model_version", "")))
        decision_trace = self._decision_trace_from_explainability(explainability)

        registry_payload = loaded["MODEL_REGISTRY.json"]
        if registry_payload is None:
            registry = ModelRegistrySummary(ScientificDataState.UNAVAILABLE, reason_codes=missing("MODEL_REGISTRY.json"))
        else:
            value = str(registry_payload.get("registry_status", registry_payload.get("status", "UNAVAILABLE"))).upper()
            raw_models = registry_payload.get("models", registry_payload.get("model_history", ()))
            if not isinstance(raw_models, list):
                registry = ModelRegistrySummary(ScientificDataState.UNAVAILABLE, registry_status="UNAVAILABLE", reason_codes=("MODEL_REGISTRY_MODELS_INVALID",))
            else:
                history = tuple(self._parse_model_version(item) for item in raw_models if isinstance(item, dict))
                current_payload = registry_payload.get("current_model")
                current = self._parse_model_version(current_payload) if isinstance(current_payload, dict) else None
                extra = [str(x) for x in registry_payload.get("reason_codes", ()) if x]
                if current is None:
                    current_id = str(registry_payload.get("current_model_id", "")).strip()
                    current_version = str(registry_payload.get("current_model_version", "")).strip()
                    if current_id or current_version:
                        current = next((m for m in history if m.model_id == current_id and (not current_version or m.version == current_version)), None)
                    if current is None:
                        extra.append("CURRENT_MODEL_NOT_AVAILABLE")
                if not history:
                    extra.append("MODEL_HISTORY_EMPTY")
                registry = ModelRegistrySummary(self._data_state(value), value, current, history, str(registry_payload.get("generated_at", registry_payload.get("updated_at", ""))), tuple(dict.fromkeys(extra)))

        summary = ScientificSummary(validation, evidence, readiness, certification, explainability, decision_trace, registry)
        return ScientificDashboardPayload(int(generation), time.monotonic(), status, summary, str(root), reads)

    def get_status(self) -> ScientificBackendStatus:
        resolution = self._resolve_root()
        root = resolution.active_root
        if root is None:
            return self._unavailable(
                resolution.reason_codes,
                detail=resolution.fallback_reason,
                configured_root=resolution.configured_root,
            )

        reasons = list(resolution.reason_codes)
        try:
            build = self._read_json(root / "BUILD_VERIFICATION.json")
            safety_payload = self._read_json(root / "SAFETY_BOUNDARY.json")
            metadata_path = root / "BACKEND_METADATA.json"
            metadata = self._read_json(metadata_path) if metadata_path.is_file() else {}
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return self._unavailable(
                ("BACKEND_STATUS_INVALID",),
                detail=str(exc),
                configured_root=resolution.configured_root,
                active_root=root,
                source=resolution.source,
            )

        safety = SafetyBoundary.from_mapping(safety_payload)
        build_valid = bool(build.get("build_valid", False))
        compile_passed = bool(build.get("compile", False))
        tests_successful = bool(build.get("tests_successful", False))
        cli_help_available = bool(build.get("cli_help_available", False))
        tests_run = int(build.get("tests_run", 0) or 0)

        if not build_valid:
            reasons.append("BUILD_NOT_VERIFIED")
        if not compile_passed:
            reasons.append("COMPILE_NOT_VERIFIED")
        if not tests_successful:
            reasons.append("TESTS_NOT_VERIFIED")
        if safety.enforcement != "FAIL_CLOSED":
            reasons.append("SAFETY_NOT_FAIL_CLOSED")
        if safety.live != "NOT_AUTHORIZED":
            reasons.append("LIVE_BOUNDARY_UNEXPECTED")
        if safety.deployment != "DISCONNECTED":
            reasons.append("DEPLOYMENT_BOUNDARY_UNEXPECTED")

        # A configured-root fallback is intentionally degraded: the data may be
        # safe, but it is not the live source the operator selected.
        availability = BackendAvailability.AVAILABLE if not reasons else BackendAvailability.DEGRADED
        integration_mode = str(metadata.get("integration_mode", "EXTERNAL_STATUS_ARTIFACTS"))
        return ScientificBackendStatus(
            engine_name=str(metadata.get("engine_name", "DVS AI Scientific Backend")),
            engine_version=str(metadata.get("engine_version", "UNKNOWN")),
            availability=availability,
            build_valid=build_valid,
            compile_passed=compile_passed,
            tests_run=tests_run,
            tests_successful=tests_successful,
            cli_help_available=cli_help_available,
            safety=safety,
            integration_mode=integration_mode,
            source_path=str(root),
            backend_source=resolution.source,
            configured_root=str(resolution.configured_root or ""),
            active_root=str(root),
            fallback_reason=resolution.fallback_reason,
            reason_codes=tuple(reasons),
        )

    @staticmethod
    def _unavailable(
        codes: tuple[str, ...],
        *,
        detail: str = "",
        configured_root: Path | None = None,
        active_root: Path | None = None,
        source: BackendSource = BackendSource.NONE,
    ) -> ScientificBackendStatus:
        reasons = tuple(code for code in codes if code)
        return ScientificBackendStatus(
            engine_name="DVS AI Scientific Backend",
            engine_version="UNKNOWN",
            availability=BackendAvailability.UNAVAILABLE,
            build_valid=False,
            compile_passed=False,
            tests_run=0,
            tests_successful=False,
            cli_help_available=False,
            safety=SafetyBoundary("UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN"),
            integration_mode="UNAVAILABLE",
            source_path=str(active_root or ""),
            backend_source=source,
            configured_root=str(configured_root or ""),
            active_root=str(active_root or ""),
            fallback_reason=detail,
            reason_codes=reasons,
        )
