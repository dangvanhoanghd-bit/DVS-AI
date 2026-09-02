from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from dvs_ai.services.beta3_cross_bundle import PromotionRecommender, RegistryEntry

from .errors import Beta4AGateError


@dataclass(frozen=True, slots=True)
class BundleSelection:
    bundle_sha256: str
    dataset_id: str
    recommendation: str


class BundleSelectionGate:
    """Sole Beta 4A entry point for selecting one cumulative bundle."""

    def __init__(self, recommender: PromotionRecommender | None = None) -> None:
        self._recommender = recommender or PromotionRecommender()

    def select(self, entries: Iterable[RegistryEntry]) -> BundleSelection:
        candidates = tuple(entries)
        result = self._recommender.recommend(candidates)
        selected = [sha for sha, value in result.recommendations.items() if value == "TRAINING_CANDIDATE"]
        if len(selected) != 1:
            raise Beta4AGateError(
                "TRAINING_CANDIDATE_CARDINALITY_VIOLATION",
                f"expected exactly one TRAINING_CANDIDATE, got {len(selected)}",
            )
        sha = selected[0]
        entry = next(item for item in candidates if item.bundle_sha256 == sha)
        return BundleSelection(sha, entry.dataset_id, "TRAINING_CANDIDATE")
