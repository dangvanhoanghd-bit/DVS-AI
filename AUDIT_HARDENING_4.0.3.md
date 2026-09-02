# DVS AI Alpha 4.0.3 — Qualification Audit Hardening Hotfix

## Fixed invariants
- Decision Graph confidence is conserved even when reason_codes and event_names are empty.
- A descriptive `baseline_confidence` node preserves the persisted confidence without inventing an indicator or strategy weight.
- A replay validation node marks `GRAPH_CONFIDENCE_INVARIANT_FAILED` if contribution conservation ever fails.
- Batch item exceptions are no longer swallowed.
- Each item failure emits a structured diagnostic record and is written to a bounded rotating JSONL journal.
- One failed item does not terminate the persistent worker or prevent following items from running.

## Unchanged safety boundaries
- Bounded FIFO remains `max_pending_batches=2` by default.
- Queue overflow remains explicit `QUEUE_FULL`.
- One persistent QThread is retained.
- Unified Core remains Shadow-only.
- Quantity remains 0.
- Paper Authority remains Legacy.
