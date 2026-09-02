# Beta 4A RC3.1 Startup Hotfix

## Root cause
The RC3 UI-thread sweep replaced unsafe worker error lambdas with `self._show_error` connections in ten widgets. Two widgets were missing the corresponding receiver method:

- `dvs_ai/ui/integrity_operations_console_widget.py`
- `dvs_ai/ui/research_experiment_widget.py`

During `MainWindow` construction, `IntegrityOperationsConsoleWidget.__init__()` evaluated `self._show_error` and raised `AttributeError`, preventing application startup.

## Fix
- Added GUI-thread `@Slot(str) _show_error()` receivers to both widgets.
- Added exception handling to `ResearchExperimentWidget._Worker.load()`.
- Added an AST regression test that fails whenever a widget connects `failed` to `self._show_error` without defining that method.

## Verification
- Python compileall: PASS
- Targeted Beta 4A + UI wiring tests: 41 PASS
- Static connection audit: all ten affected widgets define `_show_error`

A native Qt startup smoke test could not be executed in the Linux build container because PySide6 is not installed. The exact Windows startup exception shown by the user is removed at source and protected by regression test.
