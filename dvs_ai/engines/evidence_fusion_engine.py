from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable, Mapping


DEFAULT_FAMILY_WEIGHTS = {
    "TIMING": 0.22,
    "ENTRY": 0.18,
    "ORDER_FLOW": 0.32,
    "DIRECTION": 0.16,
    "MARKET": 0.12,
}

DEFAULT_SOURCE_MULTIPLIERS = {
    "FULL": 1.0,
    "PROXY": 0.82,
    "BOOTSTRAP": 0.55,
    "SIMULATED": 0.35,
    "UNKNOWN": 0.70,
}


@dataclass(frozen=True)
class EvidenceSignal:
    name: str
    family: str
    score: float
    weight: float | None = None
    quality: float = 1.0
    reliability: float | None = None
    source: str = "FULL"
    available: bool = True
    contradiction: bool = False
    contradiction_strength: float = 1.0


@dataclass(frozen=True)
class EvidenceFusionResult:
    score: float
    active_weight: float
    effective_weight: float
    components: tuple[str, ...]
    families: tuple[str, ...]
    contradictions: tuple[str, ...]
    unavailable: tuple[str, ...]
    family_details: tuple[str, ...] = ()
    directional_penalty: float = 0.0
    method: str = "FAMILY_BALANCED_RELIABILITY_SOURCE_WEIGHTED_V3"


class EvidenceFusionEngine:
    """Family-balanced fusion with reliability/source weighting.

    Correlated members are fused inside one family, so sub-signals cannot
    multiply the family's vote. UNKNOWN reliability is neutral rather than a
    hidden penalty. Source provenance and directional contradictions reduce
    influence explicitly and remain visible in diagnostics.
    """

    def __init__(
        self,
        *,
        family_weights: Mapping[str, float] | None = None,
        source_multipliers: Mapping[str, float] | None = None,
        contradiction_penalty: float = 14.0,
        contradiction_cap: float = 68.0,
    ) -> None:
        self.family_weights = dict(DEFAULT_FAMILY_WEIGHTS)
        if family_weights:
            for key, value in family_weights.items():
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue
                if isfinite(value) and value >= 0.0:
                    self.family_weights[str(key).upper()] = value
        self.source_multipliers = dict(DEFAULT_SOURCE_MULTIPLIERS)
        if source_multipliers:
            for key, value in source_multipliers.items():
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue
                if isfinite(value):
                    self.source_multipliers[str(key).upper()] = max(0.0, min(1.0, value))
        self.contradiction_penalty = max(0.0, min(40.0, float(contradiction_penalty)))
        self.contradiction_cap = max(0.0, min(100.0, float(contradiction_cap)))

    @staticmethod
    def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
        try:
            value = float(value)
        except (TypeError, ValueError):
            return low
        if not isfinite(value):
            return low
        return max(low, min(high, value))

    @staticmethod
    def _unit(value: object, default: float = 1.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        if not isfinite(number):
            return default
        return max(0.0, min(1.0, number))

    def _reliability_multiplier(self, reliability: float | None) -> float:
        # None means UNKNOWN and is deliberately neutral. Valid reliability
        # estimates map 50% -> 0.75 and 100% -> 1.0; they never boost above 1.
        if reliability is None:
            return 1.0
        r = self._unit(reliability)
        return 0.5 + 0.5 * r

    def fuse(self, signals: Iterable[EvidenceSignal]) -> EvidenceFusionResult:
        family_buckets: dict[str, list[EvidenceSignal]] = {}
        unavailable: list[str] = []
        contradictions: list[str] = []

        for signal in signals:
            family = str(signal.family).upper()
            declared_weight = self.family_weights.get(family, 0.0) if signal.weight is None else signal.weight
            try:
                declared_weight = float(declared_weight)
            except (TypeError, ValueError):
                declared_weight = 0.0
            if not signal.available or not isfinite(declared_weight) or declared_weight <= 0.0:
                unavailable.append(signal.name)
                continue
            family_buckets.setdefault(family, []).append(signal)
            if signal.contradiction:
                contradictions.append(signal.name)

        family_scores: list[tuple[str, float, float]] = []
        components: list[str] = []
        family_details: list[str] = []
        raw_active_weight = 0.0
        effective_weight = 0.0
        directional_penalty = 0.0

        for family, members in family_buckets.items():
            configured_family_weight = self.family_weights.get(family, 0.0)
            explicit_weights = [
                max(0.0, float(m.weight)) for m in members
                if m.weight is not None and isfinite(float(m.weight))
            ]
            family_weight = max(explicit_weights, default=0.0) if explicit_weights else configured_family_weight
            if family_weight <= 0.0:
                continue

            member_mass = 0.0
            weighted_score = 0.0
            weighted_quality = 0.0
            family_contradiction = 0.0
            for member in members:
                member_weight = max(0.0, float(member.weight)) if member.weight is not None else 1.0
                quality = self._unit(member.quality)
                reliability_mult = self._reliability_multiplier(member.reliability)
                source_mult = self.source_multipliers.get(str(member.source).upper(), self.source_multipliers["UNKNOWN"])
                influence = member_weight * quality * reliability_mult * source_mult
                score = self._clamp(member.score)
                strength = self._unit(member.contradiction_strength, 1.0)
                if member.contradiction:
                    score = min(score, 35.0 - 10.0 * strength)
                    family_contradiction = max(family_contradiction, strength)
                member_mass += max(0.0, member_weight)
                weighted_score += influence * score
                weighted_quality += max(0.0, member_weight) * quality * reliability_mult * source_mult
                components.append(member.name)

            if member_mass <= 0.0 or weighted_quality <= 0.0:
                continue
            family_score = weighted_score / weighted_quality
            family_quality = weighted_quality / member_mass
            family_effective_weight = family_weight * family_quality
            raw_active_weight += family_weight
            effective_weight += family_effective_weight
            family_scores.append((family, family_effective_weight, family_score))
            if family_contradiction > 0.0:
                directional_penalty += self.contradiction_penalty * family_weight * family_contradiction
            family_details.append(
                f"{family}:{family_score:.1f}:w{family_weight:.3f}:ew{family_effective_weight:.3f}"
            )

        if effective_weight <= 0.0:
            return EvidenceFusionResult(
                score=0.0,
                active_weight=raw_active_weight,
                effective_weight=0.0,
                components=tuple(components),
                families=tuple(family_buckets),
                contradictions=tuple(contradictions),
                unavailable=tuple(unavailable),
                family_details=tuple(family_details),
            )

        score = sum(weight * value for _, weight, value in family_scores) / effective_weight
        if contradictions:
            score = min(score - directional_penalty, self.contradiction_cap)

        return EvidenceFusionResult(
            score=self._clamp(score),
            active_weight=raw_active_weight,
            effective_weight=effective_weight,
            components=tuple(components),
            families=tuple(family for family, _, _ in family_scores),
            contradictions=tuple(contradictions),
            unavailable=tuple(unavailable),
            family_details=tuple(family_details),
            directional_penalty=directional_penalty,
        )
