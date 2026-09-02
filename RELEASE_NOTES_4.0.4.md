# DVS AI Alpha 4.0.4 — Qualification Performance & Launcher Stability

## Fixed

- Removed the unescaped Windows batch ampersand that caused `Confidence is not recognized` messages.
- Simplified the launcher title/banner to CMD-safe text.
- Evidence table refresh is now lazy and runs only when the Evidence workspace is opened.
- Replay timeline, Decision Graph, Inspector, and confidence breakdown are now built only when the Replay workspace is opened.
- Scan completion only marks read-only projections dirty; it no longer rebuilds the 250-row Evidence table or replay graph.

## Safety boundaries unchanged

- Unified Core remains SHADOW_ONLY.
- Paper Authority remains LEGACY.
- Quantity exposed remains zero.
- No activate, promote, authority switch, exchange, testnet, or live-order path was added.
