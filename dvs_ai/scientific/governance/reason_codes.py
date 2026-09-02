from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Mapping

from ..contracts.reason_codes import ScientificReasonCode


class ReasonCategory(str, Enum):
    DATA = "DATA"
    EVIDENCE = "EVIDENCE"
    VALIDATION = "VALIDATION"
    CERTIFICATION = "CERTIFICATION"
    REGISTRY = "REGISTRY"
    PIPELINE = "PIPELINE"
    TRACE = "TRACE"
    CONTRACT = "CONTRACT"


@dataclass(frozen=True, slots=True)
class ReasonCodeDefinition:
    code: str
    category: ReasonCategory
    description: str
    terminal: bool = False

    def __post_init__(self) -> None:
        if not self.code.strip() or self.code != self.code.strip().upper():
            raise ValueError("reason code must be non-empty uppercase text")
        if not self.description.strip():
            raise ValueError("reason code description is required")


def _category(code: str) -> ReasonCategory:
    if code.startswith(("DATA_", "DATASET_", "SAMPLE_", "TIME_", "REGIME_", "DIRECTION_")):
        return ReasonCategory.DATA
    if code.startswith("EVIDENCE_"):
        return ReasonCategory.EVIDENCE
    if code.startswith(("VALIDATION_", "STABILITY_")):
        return ReasonCategory.VALIDATION
    if code.startswith("CERTIFICATION_"):
        return ReasonCategory.CERTIFICATION
    if code.startswith("REGISTRY_"):
        return ReasonCategory.REGISTRY
    if code.startswith("TRACE_"):
        return ReasonCategory.TRACE
    if code.startswith("CONTRACT_") or code == "INVALID_STATE_TRANSITION":
        return ReasonCategory.CONTRACT
    return ReasonCategory.PIPELINE


_DEFAULT_DESCRIPTIONS = {
    code.value: code.value.replace("_", " ").title() for code in ScientificReasonCode
}


class ReasonCodeRegistry:
    """Immutable registry and validator for audit-stable scientific reason codes."""

    def __init__(self, definitions: Iterable[ReasonCodeDefinition]) -> None:
        values: dict[str, ReasonCodeDefinition] = {}
        for definition in definitions:
            if definition.code in values:
                raise ValueError(f"duplicate reason code: {definition.code}")
            values[definition.code] = definition
        self._definitions: Mapping[str, ReasonCodeDefinition] = MappingProxyType(values)

    @property
    def definitions(self) -> Mapping[str, ReasonCodeDefinition]:
        return self._definitions

    def contains(self, code: str) -> bool:
        return str(code).strip().upper() in self._definitions

    def require(self, code: str) -> ReasonCodeDefinition:
        normalized = str(code).strip().upper()
        try:
            return self._definitions[normalized]
        except KeyError as exc:
            # Namespaced diagnostic details remain governed by their canonical base.
            base = normalized.split(":", 1)[0]
            if base in self._definitions:
                return self._definitions[base]
            raise ValueError(f"unregistered scientific reason code: {normalized}") from exc

    def normalize(self, values: Iterable[str] | None, *, strict: bool = True) -> tuple[str, ...]:
        output: list[str] = []
        seen: set[str] = set()
        for value in values or ():
            code = str(value).strip().upper()
            if not code or code in seen:
                continue
            if strict:
                self.require(code)
            seen.add(code)
            output.append(code)
        return tuple(output)

    def category_for(self, code: str) -> ReasonCategory:
        return self.require(code).category


DEFAULT_REASON_CODE_REGISTRY = ReasonCodeRegistry(
    ReasonCodeDefinition(
        code=code.value,
        category=_category(code.value),
        description=_DEFAULT_DESCRIPTIONS[code.value],
        terminal=code.value.endswith(("FAILED", "DENIED")) or code.value in {
            "CERTIFICATION_NOT_GRANTED", "REGISTRY_NOT_AVAILABLE", "INVALID_STATE_TRANSITION"
        },
    )
    for code in ScientificReasonCode
)
