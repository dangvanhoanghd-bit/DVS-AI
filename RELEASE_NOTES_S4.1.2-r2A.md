# DVS AI S4.1.2-r2A — Root Shutdown Instrumentation

Instrumentation-only build on the corrected F01/F02 baseline.

Changed production file: `dvs_ai/app.py` only.

Added:
- safe `shiboken6.isValid()` wrapper checks;
- `MainWindow.destroyed` and telemetry `destroyed` observations;
- root-wrapper validity markers at `finally` entry and exit.

Unchanged:
- root teardown order;
- FinalizationWorker and QuantumWorker lifecycle;
- Decision Engine;
- trading, scan, provider, paper and learning logic.

Required runtime identity:
`dvs_ai/app.py = ed24c709134e66729d50c6d96c525a8cd791180822868637b3f790a579fe1572`
