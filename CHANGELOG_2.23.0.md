# Alpha 2.23.0 — Async Finalization

- Moved full end-of-scan finalization off the GUI thread.
- Added atomic final table commit.
- Added O(1) symbol-row indexing.
- Reduced sorting to one final operation.
- Added event-loop-friendly Auto Paper batching.
- Deferred Paper outcome maintenance until after the UI commit.
- Added MarketChart render-key caching.
- Preserved user selection and scroll state.
- No trading algorithm changes.
