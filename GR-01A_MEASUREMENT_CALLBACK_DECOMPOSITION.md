# GR-01A — Measurement & Callback Decomposition

Build ID: `RC6.4.7H-r2-GR-01A-MEASUREMENT-CALLBACK-DECOMPOSITION`

This build is measurement-only. It does not optimize callback behavior.

Instrumented paths:
- scan_progress_callback
- signal_record_worker GUI completion/failure callbacks
- stream_table_flush
- selected_detail_render_impl
- finalization_finished_callback
- scan_result_side_effect_drain

Output:
`artifacts/runtime/gr01_gui_commit_forensics.jsonl`

Each callback emits one aggregate record after measured work. The writer is asynchronous; no disk I/O is performed inside GUI table/update loops.

Governance boundaries:
- Decision Engine unchanged
- Foundation semantics unchanged
- Provider, Identity, Paper Trade, Outcome, and RP-01 semantics unchanged
- IR-01A-r7 CLEAN_EXIT retained as source baseline
