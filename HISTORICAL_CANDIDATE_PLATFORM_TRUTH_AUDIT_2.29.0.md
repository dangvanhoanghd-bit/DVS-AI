# DVS AI Alpha 2.29.0 — Historical Candidate Performance Platform

## Truth scope
- Append-only candidate lifecycle events.
- Append-only candidate performance snapshots.
- Historical candidate comparison and archive visibility.
- Truth Dashboard historical table and persisted trend chart.

## Verified invariants
- Illegal reverse lifecycle transitions are rejected.
- Historical events and snapshots are never updated in place.
- ARCHIVED candidates remain queryable with their performance history.
- Missing or non-finite metrics are normalized fail-safe at the storage boundary.
- Services contain no order placement, TradeIntent, PositionSizer, Testnet, or LIVE APIs.

## Honest limitations
- Version 2.29.0 provides the historical platform and UI surface; automatic periodic snapshot capture is not yet wired into the observation runtime.
- Candidate lifecycle transitions are explicit and human/audit driven; there is no automatic promotion.
- Existing candidates without lifecycle events appear from artifact discovery until explicitly registered.
- Historical charts begin accumulating only after snapshots are written by this or a later runtime integration release.
