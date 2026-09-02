# RC6.4.4 Release Notes

This release hardens Binance provider deadlines, scan-future lifecycle management, executor quarantine, and forensic telemetry integrity. It does not alter the Decision Engine, signal scoring, paper execution policy, or trade-selection logic.

New runtime evidence files:

- `artifacts/runtime/provider_evidence.jsonl`
- Existing `stage_boundary.jsonl` now has in-memory integrity counters available through `STAGE_BOUNDARY.snapshot_counters()`.

Operational validation remains required: two independent runs of at least three hours plus a controlled stress run.
