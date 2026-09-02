# DVS AI Alpha 2.25.3 — Gap Detection & Controlled Backfill Audit

## Truth scope

- Detects missing `aggTrade` events only from numeric aggregate-trade IDs.
- Backfills only bounded, contiguous REST `aggTrades` pages.
- Stable event keys prevent CVD double counting.
- Oversized, incomplete, non-contiguous, or failed REST recovery is marked `UNRESOLVED`.
- Missing `forceOrder` events are never reconstructed; reconnects produce a liquidation-gap warning.
- The module remains an evidence/data-quality layer and has no execution dependency.

## Limits

- No guarantee that every exchange-side gap can be recovered.
- No force-order historical backfill.
- No dynamic subscription changes.
- No live execution.
