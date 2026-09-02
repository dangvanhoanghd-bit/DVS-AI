# DVS AI Alpha 4.3.0E-3-QBP-4-RC3

## Runtime Table Batch Optimization

Scope is limited to GUI runtime projection and diagnostics. Decision Engine and Quantum research/governance logic are unchanged.

### Changes
- Buffer per-symbol streaming table updates for 100 ms.
- Commit each buffer atomically with repaint, signals and sorting disabled.
- Sort and rebuild the symbol-row index once per batch instead of once per symbol.
- Flush pending table updates before finalization.
- Add separate profiler samples for batch commit, sorting and row-index rebuild.
- Preserve the RC2 Worker lifecycle fix.

### Safety
- Execution remains PAPER.
- Live execution remains disabled.
- Quantum remains observe-only.
- No threshold or Decision Engine changes.
