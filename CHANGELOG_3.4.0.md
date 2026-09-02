# DVS AI Alpha 3.4.0 — Shadow-only GUI Integration

- Injects `CoreRuntimeAdapter` into `MainWindow` from `app.py`.
- Runs Unified Core asynchronously for the currently selected analysis.
- Adds Legacy / Unified Core / Agreement panels to Decision Core.
- Keeps Legacy as the sole Paper authority.
- Unified output is immutable, shadow-only, and exposes quantity `0.0`.
- Stale symbol/revision results are rejected.
- Adds an isolated in-memory shadow ledger and paper portfolio; no exchange or production Paper service is reachable.
- Freezes the future Paper authority handover criteria before shadow metrics are collected.
- Corrects the Windows launcher build label.
