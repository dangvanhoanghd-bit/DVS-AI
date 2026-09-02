from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_direction_confirmation_not_used_before_assignment():
    source = (
        ROOT / "dvs_ai/engines/decision_engine.py"
    ).read_text(encoding="utf-8")

    combine_start = source.index("def combine")
    helper_start = source.index(
        "def _direction_confirmation",
        combine_start,
    )
    block = source[combine_start:helper_start]

    entry_call_start = block.index(
        "status = self._entry_status("
    )
    entry_call_end = block.index(
        "quality_gate =",
        entry_call_start,
    )
    entry_call = block[
        entry_call_start:entry_call_end
    ]

    assignment_pos = block.index(
        "direction_confirmation_score,"
    )
    reason_pos = block.index(
        'f"{direction_confirmation_score:.1f}/100'
    )
    return_pos = block.index(
        "direction_confirmation_score="
    )

    assert (
        "direction_confirmation_score="
        not in entry_call
    )
    assert (
        "direction_confirmation_gate="
        not in entry_call
    )
    assert assignment_pos < reason_pos < return_pos


def test_coin_analysis_receives_direction_diagnostics():
    source = (
        ROOT / "dvs_ai/engines/decision_engine.py"
    ).read_text(encoding="utf-8")
    return_block = source[
        source.index("return CoinAnalysis("):
        source.index(
            "def _direction_confirmation",
            source.index("return CoinAnalysis("),
        )
    ]
    assert (
        "direction_confirmation_score="
        "direction_confirmation_score"
        in return_block
    )
    assert (
        "direction_confirmation_gate="
        "direction_confirmation_gate"
        in return_block
    )
