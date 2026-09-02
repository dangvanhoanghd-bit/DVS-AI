from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
import pytest

try:
    _ccxt_spec = importlib.util.find_spec("ccxt")
except ValueError:
    _ccxt_spec = None
if _ccxt_spec is None:
    sys.path.insert(0, "test_stubs")
sys.path.insert(0, ".")

from dvs_ai.engines.smart_entry_engine import (
    _correlated_cluster,
    _harmonic_consensus,
)


def test_correlated_cluster_is_one_vote():
    assert _correlated_cluster(100, 100, 100) == 100.0
    assert _correlated_cluster(100, 0, 0) == 72.0


def test_harmonic_consensus_penalizes_weak_group():
    assert _harmonic_consensus((80, 80, 80)) == pytest.approx(80.0)
    assert _harmonic_consensus((90, 90, 20)) < 50.0


def test_no_inverse_short_evidence():
    source = Path(
        "dvs_ai/engines/smart_entry_engine.py"
    ).read_text(encoding="utf-8")
    assert "100 - weak" not in source
    assert "100 - absorption" not in source
    assert "weak_short" in source
    assert "absorption_short" in source


def test_structure_is_grouped_once():
    source = Path(
        "dvs_ai/engines/smart_entry_engine.py"
    ).read_text(encoding="utf-8")
    assert "long_structure = max(" in source
    assert "short_structure = max(" in source


def test_smp_is_independent_group_consensus():
    source = Path(
        "dvs_ai/engines/smart_entry_engine.py"
    ).read_text(encoding="utf-8")
    assert "_harmonic_consensus(dominant_groups)" in source
    assert "independent_group_count" in source


def test_decision_does_not_double_vote_state_or_smp():
    source = Path(
        "dvs_ai/engines/decision_engine.py"
    ).read_text(encoding="utf-8")
    assert 'smart_entry.state == "SMART LONG READY"' not in source
    assert 'smart_entry.state == "SMART SHORT READY"' not in source
    assert "+ 0.06 * smart_entry.smart_money_probability" not in source
    assert "smp_modifier" in source


def test_version_matches_app_version():
    from dvs_ai import __version__
    from dvs_ai.version import APP_VERSION
    assert __version__ == APP_VERSION


def test_execution_safety_config():
    import json
    raw = json.loads(Path("config.json").read_text(encoding="utf-8"))
    assert raw["execution_mode"] == "PAPER"
    assert raw["execution_live_enabled"] is False
