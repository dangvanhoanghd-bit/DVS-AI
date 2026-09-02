# A/B Instrumentation Release Notes

This build adds symmetric Performance Validation Standard v1.0 instrumentation only.

- Session-specific runtime metrics JSONL, sampled every 20 seconds.
- Dedicated single writer thread and bounded queue.
- 250 ms event-loop lag probe on the GUI thread.
- 5000 ms objective Not Responding proxy.
- Automatic archival of prior snapshot session folders.
- Session-specific A/B manifest and independent audit tool.
- Minimum official comparison duration: 60 minutes per build.
- Maximum duration difference: 15%.
- G2 CPU mean acceptance: no more than G1 + 10 percentage points.

Decision Engine and trading behavior are unchanged.
