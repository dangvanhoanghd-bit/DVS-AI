from __future__ import annotations
from datetime import datetime
from ..decision import ScientificDecision
from .models import ShadowHorizon, ShadowMetrics, ShadowObservation
from .storage import ShadowStorage

class ShadowValidator:
    def __init__(self, storage: ShadowStorage) -> None:
        self._storage = storage
    def observe(self, decision: ScientificDecision, *, horizon: ShadowHorizon,
                observed_at: datetime, entry_price: float, exit_price: float) -> ShadowObservation:
        obs = ShadowObservation.from_prices(decision, horizon, observed_at, entry_price, exit_price)
        self._storage.append(obs)
        return obs
    def metrics(self) -> ShadowMetrics:
        rows = self._storage.read_all()
        wins = sum(1 for x in rows if x.return_pct > 0)
        losses = sum(1 for x in rows if x.return_pct < 0)
        total = len(rows)
        gains = sum(x.return_pct for x in rows if x.return_pct > 0)
        loss_abs = abs(sum(x.return_pct for x in rows if x.return_pct < 0))
        return ShadowMetrics(total, wins, losses, wins / total if total else 0.0,
                             sum(x.return_pct for x in rows) / total if total else 0.0,
                             gains / loss_abs if loss_abs else (float("inf") if gains else 0.0))
