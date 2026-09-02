from pathlib import Path

from dvs_ai.engines.microstructure.order_block_engine import (
    OrderBlockState,
)


def test_broken_state_is_explicitly_reserved():
    source = Path(
        "dvs_ai/engines/microstructure/order_block_engine.py"
    ).read_text(encoding="utf-8")

    assert "BROKEN is intentionally unreachable" in source
    assert "broken = invalidated" in source
    assert OrderBlockState.BROKEN.value == "BROKEN"


def test_invalidated_precedes_broken_in_state_resolution():
    source = Path(
        "dvs_ai/engines/microstructure/order_block_engine.py"
    ).read_text(encoding="utf-8")

    invalidated_pos = source.find("elif invalidated:")
    broken_pos = source.find("elif broken:")

    assert invalidated_pos >= 0
    assert broken_pos > invalidated_pos


def test_no_other_module_depends_on_broken_state():
    project = Path("dvs_ai")
    references = []

    for path in project.rglob("*.py"):
        if path.name == "order_block_engine.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "OrderBlockState.BROKEN" in text:
            references.append(str(path))

    assert references == []
