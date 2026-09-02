from pathlib import Path
import py_compile

for filename in (
    "main_window.py",
    "market_chart.py",
    "ui_geometry_manager.py",
    "ui_performance_profiler.py",
):
    py_compile.compile(filename, doraise=True)

main = Path("main_window.py").read_text(encoding="utf-8")
chart = Path("market_chart.py").read_text(encoding="utf-8")

assert "class FinalizationWorker(QObject)" in main
assert "self.finalization_worker.moveToThread" in main
assert "def _start_async_finalization" in main
assert "def _on_finalization_finished" in main
assert "def _commit_finalization_payload" in main
assert "def _process_auto_paper_batch" in main
assert "self.table.setUpdatesEnabled(False)" in main
assert "self.table.blockSignals(True)" in main
assert "self._row_by_symbol" in main
assert "def _rebuild_row_index" in main

# Heavy pipeline must live in FinalizationWorker, not on_finished.
on_finished_start = main.index("def on_finished")
upsert_start = main.index("def _upsert_row", on_finished_start)
on_finished_region = main[on_finished_start:upsert_start]
assert "build_market_brief(self.results)" not in on_finished_region
assert "hydrate_microstructure(" not in on_finished_region

assert "self._render_key" in chart
assert "if render_key == self._render_key" in chart

print("Async Finalization verification: PASS")
