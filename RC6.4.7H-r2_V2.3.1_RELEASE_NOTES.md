# Sprint A2 V2.3.1 — Paper Table Commit Decongestion

- Removed `ResizeToContents` from the Paper Trade table hot path; stable interactive widths are applied once.
- Reuses existing `QTableWidgetItem` objects and skips unchanged cells.
- Uses a 10 ms adaptive per-turn budget with a maximum of 12 rows before yielding.
- Avoids redundant foreground brush updates.
- Raises callback attribution threshold to 100 ms to reduce forensic observer amplification.
- Decision Engine remains frozen and unchanged.
- Runtime effectiveness remains pending burn-in; production approval is not granted.
