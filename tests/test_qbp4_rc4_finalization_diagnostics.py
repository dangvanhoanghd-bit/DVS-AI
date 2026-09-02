from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_rc5_version_and_launcher_are_cmd_safe():
    version = (ROOT / "dvs_ai" / "version.py").read_text(encoding="utf-8")
    launcher = (ROOT / "START_DVS_AI.bat").read_text(encoding="utf-8")
    assert 'APP_VERSION = "4.3.0E-3-QBP-4-RC7"' in version
    assert "Delta Finalization" in launcher
    assert "Performance & Stability" not in launcher
    assert "'Runtime'" not in launcher


def test_finalization_commit_emits_structured_metrics():
    source = (ROOT / "dvs_ai" / "ui" / "main_window.py").read_text(encoding="utf-8")
    for token in (
        "FINALIZATION_GUI_COMMIT_METRICS",
        '"session_id"',
        '"scan_cycle_id"',
        '"results_after"',
        '"table_rows_after"',
        '"cells_changed"',
        '"build_rows_ms"',
        '"sort_ms"',
        '"row_index_rebuild_ms"',
        '"total_commit_ms"',
    ):
        assert token in source


def test_watchdog_suppresses_suspend_artifacts():
    source = (ROOT / "dvs_ai" / "ui" / "ui_performance_profiler.py").read_text(encoding="utf-8")
    assert "suspend_gap_ms" in source
    assert "UI_WATCHDOG_GAP_SUPPRESSED" in source
    assert "reason=process_suspended" in source
