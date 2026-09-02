# Release Notes — Beta 3D-r1 Audit Verified

## Status

`IMPLEMENTED + TESTED + INDEPENDENT ATTACK AUDIT VERIFIED`

## Changes from the supplied Beta 3D implementation

- Added 21 independent adversarial tests.
- Prevented promotion ranking across different policy or extraction cohorts.
- Made lineage failures bundle-local instead of timeline-global.
- Oriented pairwise comparisons chronologically by verified manifest timestamp.
- Preserved all existing Beta 3D behavior and public report structures where possible.

## Verification

- Beta 3D original + independent tests: 66 passed.
- Full project suite: 1118 passed, 0 failed.
- Compileall: PASS.
- Decision Engine unchanged.
