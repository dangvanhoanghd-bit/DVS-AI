# Beta 4A RC4.2 — Stable Capture Key & Async Learning

Status: AUDIT_CANDIDATE

## Runtime fixes

- Replaced Python object-identity (`id(CoinAnalysis)`) linkage with stable `(scan_id, symbol)` capture keys.
- Added a bounded 30-second Auto Paper identity wait with explicit `AUTO_PAPER_IDENTITY_TIMEOUT` audit logging.
- Preserved fail-closed behavior: a Paper trade is never created without Unified identity.
- Moved Learning aggregation and Quantum-readiness reads to a dedicated persistent `QThread`.
- Coalesced repeated Learning refresh requests while a refresh is in progress.
- Added clean Learning worker shutdown.

## Verification

- Focused RC4.2 tests: 3 passed.
- Full repository: 1187 passed, 0 failed.
- Python compile verification: PASS.

Decision Engine remains unchanged.
