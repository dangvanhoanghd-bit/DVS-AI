# DVS AI Alpha 4.1.0-C-r2

## Async Live Episode Capture

- Moves Live Episode Capture off the GUI thread.
- Uses one persistent QThread and one serial worker.
- Uses a bounded FIFO queue (512 pending evaluations).
- Does not coalesce or drop valid evaluations unless the safety bound is reached.
- Uses quit() + wait() for shutdown; never terminate().
- Preserves 4.1.0-C Gate Effectiveness, Calibration and Cohort Analytics.
- Decision Engine and all engine source files remain byte-for-byte unchanged.
- Known limitation: structural_event_id remains NONE when the exact trigger-candle timestamp is unavailable.
