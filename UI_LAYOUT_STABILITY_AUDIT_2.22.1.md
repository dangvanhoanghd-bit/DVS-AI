# DVS AI Alpha 2.22.1 — UI Layout Stability Audit

## Root cause

The progress callback reset `QSplitter.setSizes(...)` for every scanned coin.
That forced repeated Qt layout negotiation while labels, tables, gauges and
charts were updating, producing the visible frame jumping in the video.

## Fix

- Removed splitter resets from `on_progress()`.
- Fixed the right result rail at 520 px.
- Made the left analysis pane the only expanding splitter child.
- Restored saved geometry once after all scan updates using a deferred timer.
- Stabilized dynamic title and metric-label size policies.
- Disabled opaque resize to reduce redraw artifacts during manual splitter drag.

No analysis or trading logic changed.
