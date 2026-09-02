from __future__ import annotations

import json
from pathlib import Path

from dvs_ai.services.universe_loader_telemetry import UniverseLoaderTelemetry


def test_started_finalized_invariant(tmp_path: Path):
    path = tmp_path / "universe_loader.jsonl"
    telemetry = UniverseLoaderTelemetry(path)
    telemetry.emit("universe_loader_started", universe_load_id="u1")
    telemetry.emit("universe_loader_finalized", universe_load_id="u1")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["universe_load_started_count"] == 1
    assert rows[-1]["universe_load_finalized_count"] == 1
    assert rows[-1]["universe_load_active_count"] == 0
