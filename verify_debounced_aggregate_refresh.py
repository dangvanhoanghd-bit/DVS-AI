from pathlib import Path
import py_compile

for filename in (
    "main_window.py",
    "market_chart.py",
    "ui_geometry_manager.py",
    "ui_performance_profiler.py",
):
    py_compile.compile(filename, doraise=True)

source = Path("main_window.py").read_text(encoding="utf-8")

assert "self.aggregate_refresh_timer.setInterval(200)" in source
assert "self.aggregate_refresh_timer.setSingleShot(True)" in source
assert "def _schedule_aggregate_refresh" in source
assert "def _flush_aggregate_refresh" in source
assert "aggregate_refresh_debounced" in source

error_start = source.index("@Slot(str,str)")
error_end = source.index("@Slot(object)", error_start)
error_block = source[error_start:error_end]
assert "def on_error" in error_block
assert "self._schedule_aggregate_refresh()" in error_block
assert "self._refresh_error_table()" not in error_block

result_start = source.index("@Slot(object)", error_end)
result_end = source.index("def _restore_scroll_value", result_start)
result_block = source[result_start:result_end]
assert "def on_result" in result_block
assert "self._upsert_row(a)" in result_block
assert "self._schedule_aggregate_refresh()" in result_block
assert "self.refresh_summary()" not in result_block
assert "self._refresh_error_table()" not in result_block

finish_start = source.index("def _on_finished_impl")
finish_end = source.index("def _upsert_row", finish_start)
finish_block = source[finish_start:finish_end]
assert "self.aggregate_refresh_timer.stop()" in finish_block
assert "self._flush_aggregate_refresh()" in finish_block

print("Debounced Aggregate Refresh verification: PASS")
