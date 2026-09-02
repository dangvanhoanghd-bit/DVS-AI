from __future__ import annotations

from enum import Enum


class ScientificReasonCode(str, Enum):
    """Canonical, audit-stable reason codes used across the scientific lifecycle."""

    DATA_QUALITY_TOO_LOW = "DATA_QUALITY_TOO_LOW"
    DATASET_FINGERPRINT_UNCHANGED = "DATASET_FINGERPRINT_UNCHANGED"
    SAMPLE_DELTA_TOO_SMALL = "SAMPLE_DELTA_TOO_SMALL"
    TIME_COVERAGE_TOO_LOW = "TIME_COVERAGE_TOO_LOW"
    REGIME_DIVERSITY_TOO_LOW = "REGIME_DIVERSITY_TOO_LOW"
    DIRECTION_DIVERSITY_TOO_LOW = "DIRECTION_DIVERSITY_TOO_LOW"
    EVIDENCE_DELTA_TOO_SMALL = "EVIDENCE_DELTA_TOO_SMALL"
    EVIDENCE_NOT_AVAILABLE = "EVIDENCE_NOT_AVAILABLE"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    VALIDATION_NOT_AVAILABLE = "VALIDATION_NOT_AVAILABLE"
    STABILITY_NOT_EVALUATED = "STABILITY_NOT_EVALUATED"
    STABILITY_FAILED = "STABILITY_FAILED"
    CERTIFICATION_NOT_GRANTED = "CERTIFICATION_NOT_GRANTED"
    CERTIFICATION_NOT_AVAILABLE = "CERTIFICATION_NOT_AVAILABLE"
    REGISTRY_NOT_AVAILABLE = "REGISTRY_NOT_AVAILABLE"
    REGISTRY_WRITE_NOT_AUTHORIZED = "REGISTRY_WRITE_NOT_AUTHORIZED"
    TRACE_INCOMPLETE = "TRACE_INCOMPLETE"
    CONTRACT_VERSION_UNSUPPORTED = "CONTRACT_VERSION_UNSUPPORTED"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    PIPELINE_STAGE_EXCEPTION = "PIPELINE_STAGE_EXCEPTION"
    LEDGER_INTEGRITY_FAILED = "LEDGER_INTEGRITY_FAILED"
    REPLAY_TRANSITION_INVALID = "REPLAY_TRANSITION_INVALID"


def normalize_reason_codes(values: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    """Return deterministic, duplicate-free reason codes without inventing values."""

    if not values:
        return ()
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        code = str(value).strip().upper()
        if code and code not in seen:
            seen.add(code)
            normalized.append(code)
    return tuple(normalized)
