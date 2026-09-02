# Sprint A2 V2.1 — Paper Commit Forensic Instrumentation

## Classification

- Source instrumentation: candidate for SOURCE VERIFIED
- Runtime root-cause visibility: PENDING
- Performance effectiveness: NOT EVALUATED
- Production approval: NOT GRANTED

## Scope

The change instruments `_commit_paper_chunk()` directly without changing the Decision Engine, worker lifecycle, shutdown path, or History commit pipeline.

## Evidence

Runtime output is written to `artifacts/runtime/paper_commit_forensics.jsonl`. A normal chunk emits one asynchronous forensic record. Writer-I/O emits an extra record only when the background writer itself exceeds 25 ms.

The record separates:

- `queue_wait_ms`
- `qt_commit_ms`
- `callback_execution_ms`
- `telemetry_publish_ms` (GUI-side async enqueue)
- `set_item_total_ms` and maximum single call
- `set_foreground_total_ms` and maximum single call
- signal/sorting/update state and restore spans
- selection and viewport scheduling spans
- GC-active snapshot and active generation

Detailed `span_breakdown_ms` and `slow_spans` are attached only when `qt_commit_ms > 25 ms`. All spans are measured in memory with `perf_counter_ns()`; no JSONL write occurs inside the cell loop.

## Safety

- Decision Engine SHA-256 remains `00c1db1a1684896b3c06fbf4cfaeea094337f1841dc2e3cb9dfdf9013252dbce`.
- Shutdown baseline is intentionally unchanged.
- The candidate is diagnostic only.
