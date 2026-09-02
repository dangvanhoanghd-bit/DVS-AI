from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable

from .models import StrategyScore


class JsonStrategyScoreStorage:
    """Atomic JSON persistence for strategy score snapshots.

    This storage is deliberately independent from live trading databases.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save(self, scores: Iterable[StrategyScore]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "scores": [
                {
                    "strategy_id": s.strategy_id,
                    "observations": s.observations,
                    "wins": s.wins,
                    "losses": s.losses,
                    "net_return": s.net_return,
                }
                for s in scores
            ],
        }
        with NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as tmp:
            json.dump(payload, tmp, sort_keys=True, separators=(",", ":"))
            tmp.flush()
            os.fsync(tmp.fileno())
            temp_name = tmp.name
        os.replace(temp_name, self.path)

    def load(self) -> tuple[dict[str, int | float | str], ...]:
        if not self.path.exists():
            return ()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != 1 or not isinstance(raw.get("scores"), list):
            raise ValueError("unsupported or malformed strategy score snapshot")
        result: list[dict[str, int | float | str]] = []
        for item in raw["scores"]:
            if not isinstance(item, dict):
                raise ValueError("malformed strategy score record")
            strategy_id = str(item.get("strategy_id", "")).strip()
            observations = int(item.get("observations", -1))
            wins = int(item.get("wins", -1))
            losses = int(item.get("losses", -1))
            net_return = float(item.get("net_return", 0.0))
            if not strategy_id or min(observations, wins, losses) < 0 or wins + losses > observations:
                raise ValueError("invalid strategy score record")
            result.append({
                "strategy_id": strategy_id,
                "observations": observations,
                "wins": wins,
                "losses": losses,
                "net_return": net_return,
            })
        return tuple(result)
