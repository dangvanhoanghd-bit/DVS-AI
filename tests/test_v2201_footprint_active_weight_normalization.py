from __future__ import annotations

import importlib.util
import sys

try:
    _ccxt_spec = importlib.util.find_spec("ccxt")
except ValueError:
    _ccxt_spec = None
if _ccxt_spec is None:
    sys.path.insert(0, "test_stubs")
sys.path.insert(0, ".")

from dvs_ai.engines.microstructure.base import MicrostructureEvidence
from dvs_ai.engines.microstructure.footprint_composite import (
    FootprintComposite,
)


def evidence(
    quality: float,
    *,
    implemented: bool = True,
    token: str = "BULLISH",
):
    return MicrostructureEvidence(
        score=quality,
        phase_quality=quality,
        explanation=(),
        evidence=(token,),
        metadata={"implemented": implemented},
    )


def perfect_components(absorption_implemented: bool):
    return {
        "order_block": evidence(100.0),
        "fvg": evidence(100.0),
        "bos_choch": evidence(100.0),
        "liquidity_sweep": evidence(100.0),
        "absorption": evidence(
            0.0,
            implemented=absorption_implemented,
        ),
        "position_building": evidence(100.0),
        "lifecycle": evidence(100.0),
    }


def test_unimplemented_absorption_is_excluded_from_denominator():
    result = FootprintComposite().combine(
        perfect_components(absorption_implemented=False),
        expected_direction="LONG",
    )

    assert result.raw_score == 100.0
    assert "absorption" not in result.component_scores
    assert any(
        "absorption: excluded (not implemented)" in line
        for line in result.explanation
    )


def test_implemented_absorption_returns_to_full_weighting():
    result = FootprintComposite().combine(
        perfect_components(absorption_implemented=True),
        expected_direction="LONG",
    )

    assert result.raw_score == 86.0
    assert result.component_scores["absorption"] == 0.0


def test_missing_component_is_also_excluded_from_denominator():
    components = perfect_components(absorption_implemented=False)
    components.pop("fvg")

    result = FootprintComposite().combine(
        components,
        expected_direction="LONG",
    )

    assert result.raw_score == 100.0
    assert "fvg" not in result.component_scores


def test_zero_active_weight_is_safe():
    components = {
        name: evidence(0.0, implemented=False)
        for name in FootprintComposite.WEIGHTS
    }

    result = FootprintComposite().combine(components)

    assert result.raw_score == 0.0
    assert result.score == 0.0
