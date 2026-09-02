from pathlib import Path

from dvs_ai.ui.shadow_core_runtime import build_gui_shadow_core_runtime


def test_owner_counters_start_at_zero():
    runtime = build_gui_shadow_core_runtime()
    before = runtime.owner_retention_snapshot()
    assert before["shadow_prepared_runs_count"] == 0
    assert before["shadow_paper_orders_count"] == 0
    assert before["shadow_ledger_run_count"] == 0


def test_summary_fields_are_present_in_source():
    source = Path("dvs_ai/ui/core_qualification_batch_runner.py").read_text(encoding="utf-8")
    for name in (
        "shadow_prepared_runs_count",
        "shadow_paper_orders_count",
        "shadow_ledger_run_count",
        "shadow_release_run_total",
        "shadow_discard_run_total",
    ):
        assert name in source
