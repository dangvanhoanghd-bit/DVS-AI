from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "dvs_ai" / "ui" / "main_window.py"
TELEMETRY = ROOT / "dvs_ai" / "ui" / "retention_owner_telemetry.py"


def test_six_direct_owner_descriptors_present() -> None:
    source = MAIN.read_text(encoding="utf-8")
    expected = {
        "MainWindow.results",
        "MainWindow._scan_result_side_effect_queue",
        "MainWindow._auto_paper_queue",
        "MainWindow._capture_identity_by_key",
        "MainWindow.learning_service._snapshot_cache",
        "MainWindow.service._frame_cache",
    }
    for owner_path in expected:
        assert owner_path in source
    assert source.count("OwnerDescriptor(") == 6


def test_no_full_heap_census_or_domain_serialization() -> None:
    source = TELEMETRY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                calls.append(node.func.attr)
            elif isinstance(node.func, ast.Name):
                calls.append(node.func.id)
    assert "get_objects" not in calls
    assert "repr" not in calls


def test_one_snapshot_call_in_finalization() -> None:
    source = MAIN.read_text(encoding="utf-8")
    assert source.count("_retention_owner_telemetry.snapshot(") == 1
