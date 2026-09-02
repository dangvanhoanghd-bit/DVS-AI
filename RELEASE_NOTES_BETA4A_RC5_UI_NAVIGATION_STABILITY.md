# Beta 4A RC5 — UI Navigation Stability & Render Debounce

## Scope

This release candidate is intentionally limited to operator-facing UI stability.
It does not change the Decision Engine, qualification rules, Paper lifecycle,
Unified Outcome contracts, or Beta 4A model governance.

## Fixed

- Scan finalization no longer forces the workspace back to the page that was
  active when the scan began.
- Finalization preserves the symbol selected at commit time rather than
  restoring a stale launch-time selection.
- Dashboard table scroll position is preserved across delta finalization.
- Streaming table commits are coalesced into 250 ms batches.
- Aggregate refresh requests are coalesced into 400 ms batches.

## Invariant

Automated data refresh owns data state only. Navigation, page selection,
operator focus, table selection, and viewport position remain user-owned state.
