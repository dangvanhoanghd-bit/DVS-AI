# NATIVE2-G2 — Lazy Truth Dashboard Reconciliation

Built from NATIVE2-G1C Stable Clean on 2026-07-26.

## Integrated
- RC6.4.3-UI1 bounded streaming-table rendering: max 8 rows per slice, 20 ms event-loop yield.
- Lazy Truth Dashboard: hidden tab receives only the latest pending analysis; heavy set_analysis runs only when visible.
- Existing G1C cooperative scan-result pipeline is preserved.
- Existing Truth Dashboard data-only history worker and operational worker are preserved (the supplied R2 patch is already a subset of G1C's truth_dashboard.py).

## Preserved
- NATIVE2-F native freeze-dump crash isolation.
- Decision Engine and thresholds.
- PAPER / observe-only execution constraints.
- Signal recorder worker, capture identity, Paper/Outcome pipeline.

## Intentionally not merged
- The full historical UI1 main_window.py was not copied wholesale because it contains older audit instrumentation and a different Auto Paper/capture branch. Only the bounded-render and lazy-dashboard changes were reconciled into the current G1C source.
