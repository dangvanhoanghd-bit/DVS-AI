# DVS AI Alpha 2.22.3 — Auto Scan UI State Preservation

The remaining movement during the 60-second Auto Scan cycle was caused by
outer-scroll state loss and a premature selected-coin refresh.

Fixes:
- Capture the outer detail QScrollArea and inner scroll positions before scan.
- Remove the selected-coin refresh before final Ranking/Microstructure.
- Refresh the selected coin once using the final pipeline result.
- Freeze paints during that update.
- Restore scroll state after 0 ms, 40 ms and 140 ms.
- Fix the Auto Scan button width.

No trading or analysis logic changed.
