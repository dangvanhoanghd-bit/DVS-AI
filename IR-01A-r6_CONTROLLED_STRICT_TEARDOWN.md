# IR-01A-r6 Controlled Strict Teardown Experiment

Purpose: test whether strict lifecycle ordering for the History Prepare, Paper Prepare,
and Auto Paper worker/QThread pairs changes DummyThread persistence and the PLF exit code.

Controlled variable:
- disable submissions;
- disconnect producer/result signals;
- request interruption;
- queue worker `deleteLater()` while the worker event loop is alive;
- `QThread.quit()` and `wait(5000)`;
- verify `isRunning() == false`;
- queue/flush QThread DeferredDelete while the GUI event loop remains alive.

This build does not mutate `threading._active`, does not alter trading algorithms, and does
not change the Decision Engine.

Runtime artifact:
`artifacts/runtime/controlled_teardown_experiment.jsonl`

Acceptance matrix:
- Dummy count decreases + exit 0: strong causal evidence.
- Dummy count decreases + crash persists: persistence is not sufficient.
- Dummy count unchanged + exit 0: teardown order matters more than Dummy count.
- Dummy count unchanged + crash persists: experiment did not affect the causal variable.
