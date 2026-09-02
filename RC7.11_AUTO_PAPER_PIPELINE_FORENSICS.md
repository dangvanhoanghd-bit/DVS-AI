# RC7.11 Auto Paper Pipeline Forensics

Scope: instrumentation only.

Always-on evidence: `artifacts/runtime/auto_paper_pipeline.jsonl`

Stages:
- queue_candidate
- dispatch_selected
- dispatch_blocked_pipeline_disabled
- worker_slot_entered
- service_returned / service_exception
- gui_result_received

No Decision Engine changes. No threshold changes. No PaperTradeService eligibility changes.
No live execution changes. Paper-only boundary preserved.
