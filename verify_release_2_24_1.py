"""Release verification for DVS AI Alpha 2.24.1 True Cell-Diff Table Engine."""
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
    UI / "ui_geometry_manager.py",
    UI / "ui_performance_profiler.py",
]
for path in required:
    assert path.exists(), f"Missing required file: {path.relative_to(ROOT)}"

for path in ROOT.rglob("*.py"):
    if any(part in {".venv", "venv"} for part in path.parts):
        continue
    py_compile.compile(str(path), doraise=True)

main = (UI / "main_window.py").read_text(encoding="utf-8")
tree = ast.parse(main)
assert 'APP_VERSION = "2.24.1"' in main
assert '2.24.1-alpha' in (ROOT / "dvs_ai" / "__init__.py").read_text(encoding="utf-8")
for token in (
    "_table_diff_metrics",
    "table_diff_diagnostics",
    "_ensure_table_item",
    "_set_cell_display",
    "_set_cell_background",
    "_set_cell_foreground",
    "table_cell_diff",
):
    assert token in main, f"Missing cell-diff implementation token: {token}"

# Ensure the old full-row recreation pattern is gone from _upsert_row.
cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MainWindow")
upsert = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "_upsert_row")
segment = ast.get_source_segment(main, upsert) or ""
assert "QTableWidgetItem(str(value))" not in segment
assert "self.table.setItem(row, col, item)" not in segment
assert "self._ensure_table_item(row, col)" in segment
assert "self._set_cell_display(item, value)" in segment

print("DVS_AI_ALPHA_2_24_1_RELEASE_VERIFY_PASS")
