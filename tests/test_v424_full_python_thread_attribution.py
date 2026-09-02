from pathlib import Path

from dvs_ai.ui.runtime_thread_attribution import RuntimeThreadAttributionTracker


ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "dvs_ai" / "ui" / "main_window.py").read_text(encoding="utf-8")


def test_tracker_returns_bounded_inventory():
    tracker = RuntimeThreadAttributionTracker(max_retired=16)
    snapshot = tracker.snapshot(1)
    assert snapshot["thread_count"] >= 1
    assert any(item["name"] == "MainThread" for item in snapshot["inventory"])
    assert all("first_seen_cycle" in item for item in snapshot["inventory"])


def test_tracker_is_observational_only():
    source = (ROOT / "dvs_ai" / "ui" / "runtime_thread_attribution.py").read_text(encoding="utf-8")
    assert ".start()" not in source
    assert ".join(" not in source
    assert "ThreadPoolExecutor(" not in source


def test_main_window_logs_full_thread_attribution():
    assert "PYTHON_THREAD_ATTRIBUTION" in MAIN
    assert '"thread_inventory"' in MAIN
    assert '"new_thread_names"' in MAIN
    assert '"persistent_thread_names"' in MAIN


def test_resume_threshold_reduces_false_positives():
    assert "if tick_gap >= 30.0:" in MAIN
    assert "TIMER_GAP_OBSERVED confidence=LOW" in MAIN
    assert "SYSTEM_RESUME_DETECTED confidence=HIGH" in MAIN



def test_decision_engine_remains_out_of_scope():
    notes = (ROOT / "RELEASE_NOTES_4.2.4.md").read_text(encoding="utf-8")
    assert "72cf7d54e1ed6369400683358da8c0ef" in notes
    assert "Decision Engine" in notes
