# RC6.4.7B — Retention and Auto-Paper Workload Control

- Enriches per-QTableWidget telemetry with object name, parent, headers, visibility, and cell capacity so the 4,244-row table can be identified from runtime evidence.
- Adds reverse capture-key mapping and bounded TTL/LRU completed-identity retention. Completion is committed before capture-submission authority is removed.
- Cleans deferred/warned/pending/analysis-key state after identity consumption.
- Replaces fixed one-item Auto Paper scheduling with a real `time.monotonic()` budget (8 ms, maximum 8 items) and a 25 ms event-loop yield.
- Samples allocator telemetry every 20 turns or for callbacks >=100 ms.
- Adds point-in-time sort, row, expected/actual values, and analysis identity to display-integrity mismatches.
- Decision Engine and generation-token lifecycle are unchanged.
