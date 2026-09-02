# RC6.4.7E — Retention Owner Release, Census Default-Off, Clean Shutdown

- Decision Engine unchanged and frozen.
- Full-heap object census is disabled by default. Enable only with `DVS_OBJECT_CENSUS_ENABLED=1`.
- When disabled, no census worker/thread/timer is created; configuration state is recorded in telemetry.
- ObjectCensusWorker shutdown is idempotent and invoked on its owning thread before QThread quit.
- Auto Paper completion/failure signals return lightweight tokens instead of retaining full CoinAnalysis/identity payloads.
- GUI shadow qualification releases per-run in-memory ledger state and PaperOrder history after durable agreement storage.
- RC6.5 remains paused; paper-only constraints unchanged.
