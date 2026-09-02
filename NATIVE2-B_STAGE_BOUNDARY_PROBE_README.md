# DVS AI Beta4A RC6.1 Test-A NATIVE2-B — Stage Boundary Probe

Diagnostic-only release built on the R2 Network Startup Guard baseline.

## Added evidence

`artifacts/runtime/stage_boundary.jsonl` records durable, flushed checkpoints across:

- snapshot completion
- frame fetch and each timeframe indicator
- structure, regime, alignment, smart entry
- Decision Engine combine boundary (no internal code change)
- footprint context and footprint analysis
- reliability application and result assembly
- `scan_coin` return
- future completion/result resolution/signal emission
- GUI result receipt/storage

## Invariants

- Decision Engine source is unchanged.
- PAPER-only/execution settings are unchanged.
- No score, threshold, signal, result, or data-flow semantics are changed.
- Existing Network Startup Guard and frame-ownership telemetry remain enabled.
- Telemetry failures are fail-open and cannot interrupt the scan.

## Run

Start with `START_DVS_AI.bat`. Press **Quét dữ liệu** once. If the process closes, zip `artifacts/runtime` immediately, especially `stage_boundary.jsonl`, `frame_ownership.jsonl`, `network_startup.jsonl`, and native/freeze logs.
