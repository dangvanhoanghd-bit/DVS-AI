from pathlib import Path


def test_no_stale_position_building_implemented_false():
    stale = []
    this_file = Path(__file__).resolve()

    for path in Path("tests").rglob("test_*.py"):
        if path.resolve() == this_file:
            continue
        text = path.read_text(encoding="utf-8")
        obsolete_patterns = (
            "r['position_building'].metadata['implemented'] is False",
            'r["position_building"].metadata["implemented"] is False',
            "position_building.metadata['implemented'] is False",
            'position_building.metadata["implemented"] is False',
        )
        if any(pattern in text for pattern in obsolete_patterns):
            stale.append(str(path))

    assert stale == []


def test_position_building_remains_evidence_only():
    source = Path(
        "dvs_ai/engines/microstructure/position_building_engine.py"
    ).read_text(encoding="utf-8")

    assert '"implemented": True' in source
    for token in (
        "place_order(",
        "submit_order(",
        "execute_trade(",
        "ExecutionService(",
    ):
        assert token not in source
