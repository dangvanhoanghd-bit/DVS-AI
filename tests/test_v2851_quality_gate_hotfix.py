from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_quality_gate_not_used_before_assignment():
    source = (
        ROOT / "dvs_ai/engines/decision_engine.py"
    ).read_text(encoding="utf-8")

    combine_start = source.index("def combine")
    helpers_start = source.index(
        "def _maturity_gate",
        combine_start,
    )
    block = source[combine_start:helpers_start]

    init_pos = block.index('quality_gate = "PENDING"')
    call_pos = block.index(
        "status, quality_gate = self._quality_gate("
    )
    reason_pos = block.index(
        "f\"{lifecycle} · Gate {maturity_gate}/{quality_gate}\""
    )

    assert init_pos < call_pos < reason_pos
    assert (
        'maturity_gate=f"{maturity_gate}/{quality_gate}"'
        not in block
    )
    assert "maturity_gate=maturity_gate" in block
