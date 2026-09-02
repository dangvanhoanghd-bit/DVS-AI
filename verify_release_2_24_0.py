"""Static release verification for DVS AI Alpha 2.24.0."""
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
ast.parse(main)
assert 'APP_VERSION = "2.24.0"' in main
assert "Commercial UI Engine" in main
assert "class FinalizationWorker" in main
assert "finalization_thread" in main
assert "_aggregate_refresh_pending" in main
assert "UIGeometryManager" in main
assert "UIPerformanceProfiler" in main
assert "QSettings" in main
assert "QShortcut" in main
assert "apply_market_bias_gate" in main
assert "auto_paper_consider" in main
assert "QuantumOptimizer" in main

version = (ROOT / "dvs_ai" / "__init__.py").read_text(encoding="utf-8")
assert '2.24.0-alpha' in version
print("DVS_AI_ALPHA_2_24_0_RELEASE_VERIFY_PASS")
