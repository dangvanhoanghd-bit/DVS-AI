# IR-01A Scientific Backend Worker Candidate V1

## Implemented

- Added immutable `ScientificDashboardPayload`.
- Added `RootDiscoveryCache` with TTL plus filesystem signature invalidation (root inode, mtime, required-file mtime/size/inode).
- Added `ScientificBackendBridge.build_dashboard_payload(generation)`.
- Root resolution is performed once per snapshot; each of nine artifacts is read at most once.
- Explainability is parsed once and reused to construct Decision Trace.
- Added `ScientificBackendWorker` on a dedicated `QThread`.
- Truth Dashboard now submits work asynchronously and commits only the latest generation.
- Stale payloads are rejected before GUI commit.
- Scientific backend file I/O is removed from the GUI timer callback.

## Validation completed

- Python compilation: PASS.
- Scientific backend integration tests: 23 PASS.
- Custom snapshot/immutability/read-count checks: PASS.
- Runtime burn-in verification: PENDING.

## Governance

This is an implementation candidate, not an Incident 1 closure. Runtime watchdog verification and frozen-scope hash comparison remain required.
