# RC6.4.7G — Payload Footprint & Allocator Localization

- Measures selected-deep bytes for `MainWindow.results`, `MainWindow.current_analysis`, and `MainWindow._truth_dashboard_pending_analysis`.
- Prioritizes the long-lived pending reference every cycle.
- Samples the full results graph every fifth cycle with strict time/node budgets.
- Recognizes pandas deep memory and NumPy native buffers.
- Does not call `gc.get_objects()`, use `repr()`, or retain domain references.
- Writes `artifacts/runtime/payload_footprint.jsonl`.
- Runtime code identity now imports canonical `BUILD_ID`; no literal stale build label remains.
- Decision Engine unchanged.
