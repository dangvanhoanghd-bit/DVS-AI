"""Release verification for DVS AI Alpha 2.24.2 Frame Paint Scheduler."""
from __future__ import annotations

import ast
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UI = ROOT / "dvs_ai" / "ui"
required = [
    ROOT / "run.py",
    ROOT / "config.json",
    ROOT / "requirements.txt",
    ROOT / "dvs_ai" / "app.py",
    UI / "main_window.py",
    UI / "market_chart.py",
    UI / "frame_paint_scheduler.py",
]
for path in required:
    assert path.exists(), f"Missing required file: {path.relative_to(ROOT)}"

for path in ROOT.rglob("*.py"):
    if any(part in {".venv", "venv"} for part in path.parts):
        continue
    py_compile.compile(str(path), doraise=True)

main = (UI / "main_window.py").read_text(encoding="utf-8")
chart = (UI / "market_chart.py").read_text(encoding="utf-8")
scheduler = (UI / "frame_paint_scheduler.py").read_text(encoding="utf-8")
assert 'APP_VERSION = "2.24.2"' in main
assert '2.24.2-alpha' in (ROOT / "dvs_ai" / "__init__.py").read_text(encoding="utf-8")

for token in (
    "class FramePaintScheduler",
    "frame_interval_ms",
    "frame_budget_ms",
    "deduplicated",
    "flush_frame",
    "diagnostics",
):
    assert token in scheduler, f"Missing scheduler token: {token}"

for token in (
    "self.paint_scheduler = FramePaintScheduler",
    "paint_scheduler_diagnostics",
    "self.paint_scheduler.request(self.table.viewport(), priority=20)",
    "self.paint_scheduler.request(self.error_table.viewport(), priority=15)",
    "self.paint_scheduler.close(flush=False)",
):
    assert token in main, f"Missing main-window scheduler integration: {token}"

assert "set_paint_scheduler" in chart
assert "request_repaint" in chart
assert "self._paint_scheduler.request(self, priority)" in chart

# Ensure MarketChart mutations no longer directly repaint except fallback inside request_repaint.
tree = ast.parse(chart)
cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MarketChart")
for name in ("set_analysis", "set_signal_markers_visible", "set_candidate_visibility"):
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)
    segment = ast.get_source_segment(chart, method) or ""
    assert "self.update()" not in segment, f"Direct repaint remains in {name}"
    assert "self.request_repaint" in segment, f"Scheduler request missing in {name}"

print("DVS_AI_ALPHA_2_24_2_RELEASE_VERIFY_PASS")
