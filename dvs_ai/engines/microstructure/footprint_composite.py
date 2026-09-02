from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .base import LifecycleStage, MicrostructureEvidence


@dataclass(frozen=True)
class SmartMoneyFootprintScore:
    raw_score: float
    score: float
    context_multiplier: float
    direction: str
    consensus_count: int
    independent_group_count: int
    confirmation_depth: str
    strong_confirmation: bool
    direction_alignment: str
    lifecycle_stage: str
    position_building_score: float
    position_building_regime: str
    explanation: tuple[str, ...]
    components: tuple[MicrostructureEvidence, ...]
    component_scores: Mapping[str, float]
    evidence_groups: Mapping[str, str]

    def __post_init__(self) -> None:
        for name in ("raw_score", "score", "position_building_score"):
            object.__setattr__(
                self,
                name,
                max(0.0, min(100.0, float(getattr(self, name)))),
            )
        object.__setattr__(
            self,
            "context_multiplier",
            max(0.30, min(1.35, float(self.context_multiplier))),
        )
        object.__setattr__(self, "explanation", tuple(self.explanation or ()))
        object.__setattr__(self, "components", tuple(self.components or ()))
        object.__setattr__(
            self,
            "component_scores",
            MappingProxyType(dict(self.component_scores or {})),
        )
        object.__setattr__(
            self,
            "evidence_groups",
            MappingProxyType(dict(self.evidence_groups or {})),
        )


class FootprintComposite:
    """Smart Money Footprint V4: context and independent evidence."""

    WEIGHTS = {
        "order_block": 0.20,
        "fvg": 0.15,
        "bos_choch": 0.16,
        "liquidity_sweep": 0.13,
        "absorption": 0.14,
        "position_building": 0.14,
        "lifecycle": 0.08,
    }

    GROUPS = {
        "order_block": "ORDER_BLOCK",
        "fvg": "IMBALANCE",
        "bos_choch": "STRUCTURE",
        "liquidity_sweep": "LIQUIDITY",
        "absorption": "ORDER_FLOW",
        "position_building": "POSITIONING",
        "lifecycle": "CONTEXT",
    }

    @staticmethod
    def _direction(evidence: MicrostructureEvidence) -> str:
        text = " ".join(evidence.evidence).upper()
        if any(token in text for token in (
            "BULLISH", "SWEEP_LOW", "SPRING", "MARKUP",
            "ACCUMULATION", "REACCUMULATION",
            "LONG_CONFIRM", "DIRECTION_LONG",
            "SHORT_COVERING", "SELL_ABSORPTION_LONG",
        )):
            return "LONG"
        if any(token in text for token in (
            "BEARISH", "SWEEP_HIGH", "UPTHRUST", "MARKDOWN",
            "DISTRIBUTION", "REDISTRIBUTION",
            "SHORT_CONFIRM", "DIRECTION_SHORT",
            "LONG_CLOSING", "BUY_ABSORPTION_SHORT",
        )):
            return "SHORT"
        return "NEUTRAL"

    @staticmethod
    def _lifecycle(components: dict[str, MicrostructureEvidence]) -> str:
        evidence = components.get("lifecycle")
        if evidence is None or evidence.stage is None:
            return "UNKNOWN"
        if isinstance(evidence.stage, LifecycleStage):
            return evidence.stage.name
        return str(evidence.stage).upper()

    @staticmethod
    def _multiplier(
        lifecycle: str,
        direction: str,
        aligned_groups: int,
    ) -> float:
        if lifecycle in ("SPRING", "ACCUMULATION") and direction == "LONG":
            return 1.25 if aligned_groups >= 3 else 1.12
        if lifecycle == "TEST" and direction in ("LONG", "SHORT"):
            return 1.30 if aligned_groups >= 3 else 1.15
        if lifecycle in ("UPTHRUST", "DISTRIBUTION") and direction == "SHORT":
            return 1.25 if aligned_groups >= 3 else 1.12
        if lifecycle in ("REACCUMULATION",) and direction == "LONG":
            return 1.07
        if lifecycle in ("REDISTRIBUTION",) and direction == "SHORT":
            return 1.07
        if lifecycle in ("MARKUP", "MARKDOWN"):
            return 0.70
        if lifecycle == "EXHAUSTION":
            return 0.35
        return 0.95

    def combine(
        self,
        components: dict[str, MicrostructureEvidence],
        expected_direction: str | None = None,
    ) -> SmartMoneyFootprintScore:
        weighted_sum = 0.0
        active_weight = 0.0
        long_votes = 0
        short_votes = 0
        component_scores: dict[str, float] = {}
        votes_by_group: dict[str, str] = {}
        explanations: list[str] = []
        excluded_components: list[str] = []

        for name, weight in self.WEIGHTS.items():
            evidence = components.get(name)
            if evidence is None:
                excluded_components.append(f"{name}:MISSING")
                continue

            implemented = bool(
                evidence.metadata.get("implemented", True)
            )
            if not implemented:
                excluded_components.append(
                    f"{name}:NOT_IMPLEMENTED"
                )
                explanations.append(
                    f"{name}: excluded (not implemented)"
                )
                continue

            quality = float(evidence.phase_quality)
            weighted_sum += quality*weight
            active_weight += weight
            component_scores[name] = quality
            direction = self._direction(evidence)
            if quality >= 55 and direction != "NEUTRAL":
                votes_by_group[self.GROUPS[name]] = direction
                if direction == "LONG":
                    long_votes += 1
                else:
                    short_votes += 1
            explanations.append(f"{name}: {quality:.1f} ({direction})")

        raw = (
            weighted_sum/active_weight
            if active_weight > 0.0
            else 0.0
        )

        if long_votes > short_votes:
            direction = "LONG"
            consensus = long_votes
        elif short_votes > long_votes:
            direction = "SHORT"
            consensus = short_votes
        else:
            direction = "NEUTRAL"
            consensus = max(long_votes, short_votes)

        agreeing = {
            group: vote
            for group, vote in votes_by_group.items()
            if vote == direction
        }
        independent_count = len(agreeing)
        depth = (
            "NONE" if independent_count == 0
            else "WEAK" if independent_count == 1
            else "CONFIRMED" if independent_count == 2
            else "STRONG"
        )

        lifecycle = self._lifecycle(components)
        multiplier = self._multiplier(
            lifecycle,
            direction,
            independent_count,
        )
        critical = [component_scores.get(name, 0.0) for name in ("order_block","bos_choch","liquidity_sweep","position_building") if name in component_scores]
        quality_floor = min(critical) if critical else 0.0
        breadth = min(1.0, independent_count/4.0)
        adjusted = raw*multiplier*(0.72+0.28*breadth) + 0.12*quality_floor
        if independent_count >= 3:
            adjusted += min(10.0, (independent_count-2)*3.5)
        adjusted = max(0.0, min(100.0, adjusted))

        expected = str(expected_direction or "").upper()
        if not expected:
            alignment = "NOT_APPLIED"
        elif direction == expected:
            alignment = "ALIGNED"
        elif direction == "NEUTRAL":
            alignment = "NEUTRAL"
        else:
            alignment = "CONFLICT"

        position = components.get("position_building")
        position_score = (
            float(position.phase_quality)
            if position is not None else 0.0
        )
        position_regime = (
            str(position.metadata.get("regime", "UNKNOWN"))
            if position is not None else "UNKNOWN"
        )

        strong = (
            depth == "STRONG"
            and adjusted >= 72.0
            and position_score >= 55.0
            and alignment != "CONFLICT"
            and lifecycle not in ("MARKUP", "MARKDOWN", "EXHAUSTION")
        )

        explanations.extend((
            f"Active weight {active_weight:.2f}/1.00; "
            f"excluded {', '.join(excluded_components) if excluded_components else 'NONE'}.",
            f"Lifecycle {lifecycle} ×{multiplier:.2f}.",
            f"Confirmation {depth}: {independent_count} independent groups.",
            f"Position Building {position_score:.1f} ({position_regime}).",
            f"Direction alignment {alignment}.",
            f"Raw/context score {raw:.1f}/{adjusted:.1f}.",
        ))

        return SmartMoneyFootprintScore(
            raw_score=raw,
            score=adjusted,
            context_multiplier=multiplier,
            direction=direction,
            consensus_count=consensus,
            independent_group_count=independent_count,
            confirmation_depth=depth,
            strong_confirmation=strong,
            direction_alignment=alignment,
            lifecycle_stage=lifecycle,
            position_building_score=position_score,
            position_building_regime=position_regime,
            explanation=tuple(explanations),
            components=tuple(components.values()),
            component_scores=component_scores,
            evidence_groups=agreeing,
        )
