from pathlib import Path
import json
import weakref

from dvs_ai.runtime.coin_analysis_token_tracker import CoinAnalysisTokenTracker


class Payload:
    def __init__(self, symbol="X"):
        self.symbol = symbol


def test_token_tracker_uses_weak_reference_and_owner_lifecycle(tmp_path):
    tracker = CoinAnalysisTokenTracker(tmp_path / "tokens.jsonl")
    payload = Payload()
    token = tracker.register_created(payload, cycle_index=1, mutation_site="worker")
    assert token == 1
    assert tracker.owner_enter(payload, "Owner.path", cycle_index=1, mutation_site="append") == token
    assert tracker.owner_release(payload, "Owner.path", cycle_index=2, mutation_site="pop") == token
    tracker.cycle_snapshot(cycle_index=2)
    ref = weakref.ref(payload)
    del payload
    import gc
    gc.collect()
    assert ref() is None
    events = [json.loads(line) for line in (tmp_path / "tokens.jsonl").read_text().splitlines()]
    names = [item["event"] for item in events]
    assert "token_created" in names
    assert "token_entered_owner" in names
    assert "token_released_from_owner" in names
    assert "token_collected" in names


def test_build_identity_sources_match():
    root = Path(__file__).resolve().parents[1]
    build_id = (root / "BUILD_ID.txt").read_text(encoding="utf-8").strip()
    primary = json.loads((root / "code_identity.json").read_text(encoding="utf-8"))
    artifact = json.loads((root / "artifacts/code_identity.json").read_text(encoding="utf-8"))
    from dvs_ai.version import BUILD_ID
    assert build_id == BUILD_ID
    assert primary["build_id"] == BUILD_ID
    assert artifact["build_id"] == BUILD_ID
