# DVS AI Alpha 3.0.1 — Unified Core Safety Hotfix

## Fixed

1. Replaced the removed `MainWindow.show_analysis()` call in `_toggle_expert_mode()` with the active unified renderer `show_selected()`.
2. Preserved timeframe and scroll position while switching Beginner/Expert mode.
3. Added fail-safe exception logging for analysis and microstructure refresh (`UI_EXPERT_MODE_REFRESH_FAILED`, `UI_EXPERT_MODE_MICROSTRUCTURE_REFRESH_FAILED`).
4. Changed `ScientificLedger.verify_run()` to return `False` for unknown or empty runs (fail-closed).
5. Added one central build identity module: `dvs_ai/version.py`.
6. Updated application and launcher identity to `3.0.1 Unified Core Safety Hotfix`.
7. Replaced ambiguous `● LIVE` badge with `● DATA LIVE · ORDERS LOCKED`.
8. Added regression tests in `tests/test_v301_unified_core_safety_hotfix.py`.

## Verification

- Python compile check: PASS
- Focused safety and scientific regression: 46 passed
- PySide6 GUI runtime tests were not executable in the Linux sandbox because PySide6 is not installed. The original Windows runtime remains the required final GUI smoke-test environment.

## Required Windows smoke test

1. Launch using `START_DVS_AI.bat`.
2. Toggle `Chế độ: Dễ hiểu` / `Chế độ: Chuyên gia` before and after a scan.
3. Confirm no `AttributeError` appears.
4. Confirm selected symbol, timeframe and scroll position are retained.
5. Confirm the badge reads `DATA LIVE · ORDERS LOCKED`.
