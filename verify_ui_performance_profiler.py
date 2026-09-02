from pathlib import Path
import py_compile

for filename in (
    "main_window.py",
    "ui_geometry_manager.py",
    "ui_performance_profiler.py",
):
    py_compile.compile(filename, doraise=True)

main = Path("main_window.py").read_text(encoding="utf-8")
profiler = Path("ui_performance_profiler.py").read_text(encoding="utf-8")

assert "UIPerformanceProfiler" in main
assert 'section("show_selected")' in main
assert 'section("on_finished_total")' in main
assert 'log_report("scan_finished")' in main

assert "class UIPerformanceProfiler" in profiler
assert "UI_EVENT_LOOP_STALL" in profiler
assert "UI_SLOW_SECTION" in profiler
assert "UI_PERFORMANCE_REPORT" in profiler

print("UI Performance Profiler verification: PASS")
