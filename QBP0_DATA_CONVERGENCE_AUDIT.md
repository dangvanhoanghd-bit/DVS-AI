# QBP-0 Data Convergence — implemented foundation

## Architecture decision

QBP-0 uses **Adapter first, migration later**. It does not delete, mutate, backfill, or migrate `paper_trades`, `setup_episodes`, or `candidate_outcomes`.

## Implemented

- Canonical `UnifiedOutcome` with source-qualified identity and provenance.
- Central, fail-closed vocabulary mapping.
- Read-only SQLite sources for legacy Paper Trades and episode outcomes.
- Read-only `QuantumDataAdapter` with deterministic ordering and collision detection.
- Data-equivalence and provenance tests.

## Explicit non-goals for this commit

- The legacy optimizer has not been switched to the adapter because it also requires a governed translation of evidence snapshots and selection semantics.
- No heuristic cross-source deduplication is attempted because no authoritative linkage key currently exists.
- No migration or schema retirement has occurred.
- No Decision Engine code was changed.

## Mapping policy

- `WIN` -> `WIN`
- `LOSS` -> `LOSS`
- `AMBIGUOUS` -> `AMBIGUOUS`
- `PARTIAL_AMBIGUOUS` -> `AMBIGUOUS`
- `EXPIRED` -> `EXPIRED_UNFILLED`

Unknown labels and non-terminal legacy rows fail closed or are excluded. `CLOSED` is treated only as lifecycle status, never as an outcome label.
