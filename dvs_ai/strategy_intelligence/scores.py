from __future__ import annotations

from dataclasses import dataclass

from .models import StrategyScore


@dataclass(slots=True)
class _MutableScore:
    observations: int = 0
    wins: int = 0
    losses: int = 0
    net_return: float = 0.0


class StrategyScoreRegistry:
    """Tracks out-of-sample outcomes and converts them to bounded fusion weights."""

    def __init__(self, prior_reliability: float = 0.5, minimum_weight: float = 0.1) -> None:
        if not 0 <= prior_reliability <= 1:
            raise ValueError("prior_reliability must be between 0 and 1")
        if not 0 < minimum_weight <= 1:
            raise ValueError("minimum_weight must be in (0, 1]")
        self.prior_reliability = prior_reliability
        self.minimum_weight = minimum_weight
        self._scores: dict[str, _MutableScore] = {}

    def record(self, strategy_id: str, return_pct: float) -> StrategyScore:
        if not strategy_id.strip():
            raise ValueError("strategy_id is required")
        s = self._scores.setdefault(strategy_id, _MutableScore())
        s.observations += 1
        s.net_return += float(return_pct)
        if return_pct > 0:
            s.wins += 1
        elif return_pct < 0:
            s.losses += 1
        return self.get(strategy_id)

    def get(self, strategy_id: str) -> StrategyScore:
        s = self._scores.get(strategy_id, _MutableScore())
        win_rate = s.wins / s.observations if s.observations else 0.0
        # Beta(1,1)-style shrinkage prevents tiny samples dominating fusion.
        posterior = (s.wins + self.prior_reliability * 2.0) / (s.observations + 2.0)
        return StrategyScore(
            strategy_id=strategy_id,
            observations=s.observations,
            wins=s.wins,
            losses=s.losses,
            net_return=s.net_return,
            win_rate=win_rate,
            reliability=max(0.0, min(1.0, posterior)),
        )

    def weight(self, strategy_id: str) -> float:
        return max(self.minimum_weight, self.get(strategy_id).reliability)

    def snapshot(self) -> tuple[StrategyScore, ...]:
        return tuple(self.get(key) for key in sorted(self._scores))

    def restore(self, records) -> None:
        """Restore validated aggregate records from a storage adapter."""
        restored: dict[str, _MutableScore] = {}
        for record in records:
            strategy_id = str(record["strategy_id"]).strip()
            observations = int(record["observations"])
            wins = int(record["wins"])
            losses = int(record["losses"])
            net_return = float(record["net_return"])
            if not strategy_id or min(observations, wins, losses) < 0:
                raise ValueError("invalid score record")
            if wins + losses > observations:
                raise ValueError("wins plus losses cannot exceed observations")
            if strategy_id in restored:
                raise ValueError(f"duplicate strategy score: {strategy_id}")
            restored[strategy_id] = _MutableScore(observations, wins, losses, net_return)
        self._scores = restored
