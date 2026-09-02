# Beta 3D-r1 Independent Attack Audit Report

## Scope

This audit was executed against the Beta 3D source package supplied together with the Beta 3C-r1 baseline.

The review compared the two source trees, inspected the Beta 3D production module and tests, ran the original focused suite, added a separate adversarial suite, fixed issues exposed by code review, and reran the complete project regression.

## Baseline verification

- Original Beta 3D focused tests before the audit: **45 passed**.
- Original full project suite before audit changes: **1097 passed**.
- Decision Engine MD5 remained `72cf7d54e1ed6369400683358da8c0ef`.
- Decision Engine SHA-256 remained `00c1db1a1684896b3c06fbf4cfaeea094337f1841dc2e3cb9dfdf9013252dbce`.
- No source differences were found in `dvs_ai/engines/` between the supplied Beta 3C-r1 and Beta 3D trees, ignoring generated `__pycache__` content.

## Findings corrected during audit

### 1. Cross-cohort promotion leakage

The original recommender detected valid same-policy/same-extractor cohorts, but then concatenated Pareto-frontier candidates and selected a single winner globally. That allowed bundles from different policy or extraction identities to compete indirectly.

Correction:

- Pareto filtering and lexicographic selection now run independently inside each `(Policy Identity, Extraction Identity)` cohort.
- Each qualifying Type-A cohort can produce its own `TRAINING_CANDIDATE`.
- Singleton or confounded-only cohorts remain capped at `ELIGIBLE_CANDIDATE`.
- No winner is selected across policy or extractor boundaries.

### 2. Global lineage anomaly poisoning

The original constraint logic used timeline-wide `BROKEN_PARENT_REFERENCE` state. If any branch had a missing parent, every parented bundle could be rejected, including unrelated valid branches.

Correction:

- Lineage eligibility is now computed per bundle.
- Missing-parent, cross-policy-lineage, and cycle failures are attached only to implicated bundles.
- A damaged branch does not poison an unrelated valid branch.

### 3. Baseline/comparison direction depended on SHA ordering

Registry entries are deterministically sorted by bundle SHA. The orchestration layer originally used that order as baseline/comparison direction, so a newer bundle could become the baseline solely because its hash sorted first.

Correction:

- Pair direction is now determined by verified manifest `build_timestamp`, with `bundle_sha256` only as the deterministic final tie-break.
- Raw deltas therefore follow older-to-newer orientation rather than hash order.

## Independent adversarial suite

A separate file, `tests/test_beta3d_independent_attack_audit.py`, contains **21 attack tests** covering:

- policy and extractor cohort isolation;
- fallback caps;
- branch-local broken-parent handling;
- branch-local cycle handling;
- cross-policy lineage rejection;
- Type-B/Type-C no-interpretation behavior;
- low burn-in behavior;
- exact 5%, 15%, and 30% thresholds;
- negative-shift magnitude handling;
- zero-baseline behavior;
- parent-hash timeline semantics;
- fork preservation;
- duplicate identity detection;
- Pareto trade-offs;
- input-order determinism;
- chronological comparison orientation;
- absence of weighted fitness scoring.

Result: **21 passed, 0 failed**.

Combined Beta 3D focused and attack tests: **66 passed, 0 failed**.

## Final regression

- Complete project test suite: **1118 passed, 0 failed**.
- `python -m compileall -q dvs_ai tests`: **PASS**.

## Audit conclusion

Beta 3D-r1 is verified as:

`IMPLEMENTED + TESTED + INDEPENDENT ATTACK AUDIT VERIFIED`

The corrected implementation preserves the frozen Beta 3D principles:

- registry remains derived from verified bundles;
- raw metrics remain separate from interpretation;
- confounded comparisons cannot be described as market drift;
- low-burn-in comparisons cannot receive interpretation labels;
- promotion uses hard constraints, Pareto filtering, and frozen lexicographic ordering without weighted scores;
- comparison and promotion never cross policy/extractor cohort boundaries;
- data lineage remains separate from software release history;
- Decision Engine remains unchanged.
