# DVS AI Alpha 2.22.5 — UI Geometry Manager

Built directly from the latest uploaded `main_window.py`.

## Fixes
- Root layout uses `SetNoConstraint` so the largest tab cannot force native window width.
- Central widget and QTabWidget use shrinkable size policies.
- Startup geometry is applied once from `QScreen.availableGeometry()`.
- Existing maximized/fullscreen state is preserved.
- Absolute splitter pixel sizes were removed and replaced with stretch ratios.
- Gauge, badge and right-panel minimum widths were reduced.
- Non-recursive geometry diagnostics were added.

## Install
Replace `dvs_ai/ui/main_window.py` with the patched file. Do not copy `.pyc` files; Python regenerates them.
