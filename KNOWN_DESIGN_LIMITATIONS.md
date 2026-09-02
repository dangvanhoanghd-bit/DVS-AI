# Known Design Limitations — DVS AI Alpha 4.2.1

## 1. Audit manifest self-sealing
The manifest checksum proves internal consistency between the manifest and declared payloads. It is not an external authenticity proof. An actor able to modify both payloads and manifest can reseal the archive. External publication of the bundle hash or a digital signature is required for origin/authenticity assurance.

## 2. Normal versus Strict verification
Normal verification preserves backward compatibility: archive members not declared in the manifest produce a warning. Strict verification treats every unlisted archive member as a verification failure.

## 3. Before/after source hash sampling
Audit export compares source database hashes before and after export. A transient modification that is perfectly reverted between the two sampling points is theoretically undetectable. This is accepted for the current single-user/offline threat model.

## 4. Report-like review targets
`LINEAGE_REPORT` and `COHORT_DIAGNOSTICS` historically use an externally supplied checksum as both identifier and stored checksum. This is Level 1 self-asserted integrity, not independent recomputation. Version 4.2.1 no longer labels this tautological comparison PASS; it reports `UNVERIFIABLE_WITHOUT_SOURCE_ARTIFACT` until the original report artifact or a reproducible generation specification is supplied.

## 5. Defensive integrity rules
`DUPLICATE_ACTIVATION`, `ORPHAN_EVALUATION`, and `ORPHAN_CANDIDATE` may be unreachable through the normal schema-enforced writer path. They remain intentionally as defenses against schema drift, disabled per-connection foreign keys, legacy databases, migration defects, and manual tampering.
