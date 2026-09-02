# Beta 4A M4 Leakage Detector Specification — RC1

## Scope

M4 is a structural verifier. It reads already-produced dataset rows, lineage,
split artifacts and bundle identities. It never recomputes feature mathematics,
quality, coverage, burn-in, labels or lineage timestamps.

## Frozen checks

1. **Temporal consistency**
   - Verify `snapshot_timestamp <= first_eligible_evaluation_timestamp`.
   - Missing temporal lineage fails closed.
   - Codes: `TEMPORAL_CONSISTENCY_VIOLATION`,
     `TEMPORAL_LINEAGE_EVIDENCE_MISSING`.

2. **Structural group isolation**
   - The immutable `structural_group_id` used by M3 must not span Train,
     Validation and Test.
   - Code: `SHARED_STRUCTURAL_GROUP_SPLIT_VIOLATION`.

3. **Cross-bundle duplicate identity**
   - Defense-in-depth check for one `dataset_row_id` appearing in more than one
     distinct bundle identity.
   - Code: `CROSS_BUNDLE_DUPLICATE_IDENTITY`.

4. **Raw feature/label correlation diagnostics**
   - Pearson correlation is descriptive only and uses values supplied by lower
     layers.
   - No feature is removed or modified.
   - Code: `SUSPICIOUS_LABEL_CORRELATION` (`WARNING` only).

## Report contract

`LeakageDetectionReport` is deterministically sealed by SHA-256 over canonical
content. Status is:

- `PASS`: no hard-block finding; warnings may be present.
- `BLOCKED`: at least one hard-block finding.

`LeakageDetector.require_pass()` is the official downstream gate. A blocked
report emits `LEAKAGE_REPORT_HARD_BLOCKED`.

## Explicit limitations

M4 does not prove absence of every possible statistical leakage. It verifies
only structural evidence present in the supplied artifacts. It does not infer
future information from feature mathematics and does not claim causal meaning
from correlation.
