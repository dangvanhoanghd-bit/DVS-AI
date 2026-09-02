# DVS AI S4.1.2-r2B — Deterministic Root Wrapper Shutdown

- Production source changed: `dvs_ai/app.py` only.
- `MainWindow.deleteLater()` is posted after existing telemetry/order-flow stop steps.
- DeferredDelete is drained with a bounded 1-second loop using `QCoreApplication.sendPostedEvents` and `app.processEvents`.
- `RuntimeTelemetryExporter` is not deleted separately; Qt parent-child ownership cascades from `MainWindow`.
- `QApplication` teardown is unchanged in this build.
- F01/F02 corrected `main_window.py` is preserved.
- Decision Engine is unchanged.

## Source identity

- `dvs_ai/app.py`: `4fb1102e9dc17eef8c909886deab56eb4fbc4898b676ed1f97656b29c40a04fd`
- `dvs_ai/ui/main_window.py`: `0f390bb27f8180791987bedb467d7285866bda873479b6a2d02c62325b479d29`
- `dvs_ai/engines/decision_engine.py`: `00c1db1a1684896b3c06fbf4cfaeea094337f1841dc2e3cb9dfdf9013252dbce`

Runtime verification remains pending.
