# DVS AI Alpha 4.2.4 — Full Python Thread Attribution

This qualification release is instrumentation-first. It adds a bounded,
read-only inventory of every live Python `threading.Thread` after each scan
cycle so the residual non-`dvs-scan` thread accumulation can be attributed by
name, ident, native ID, daemon state, category, first-seen cycle, last-seen
cycle, and age in cycles.

It also changes sleep/resume inference from 8 seconds to 30 seconds. Gaps from
8 to under 30 seconds are logged as low-confidence timer gaps and do not defer
a scan. Gaps of 30 seconds or more are logged as high-confidence resume events.

No Decision Engine, scanner scoring, thresholds, execution authority, or risk
logic changed. The frozen Decision Engine MD5 remains:

`72cf7d54e1ed6369400683358da8c0ef`

Execution remains PAPER-only and live execution remains locked.
