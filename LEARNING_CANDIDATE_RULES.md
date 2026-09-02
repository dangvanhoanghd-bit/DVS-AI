# Learning Candidate Rules

## Eligibility source

Base candidates come from `UnifiedOutcomeService.learning_ready()` only.

## Required conditions

- terminal outcome;
- immutable snapshot exists and verifies;
- explicit source identity linkage;
- no unresolved conflict;
- no ambiguous match;
- integrity pass;
- eligibility is `UNIFIED_ELIGIBLE`;
- feature extraction quality passes.

## Human review semantics

Human review is conditional, not universally mandatory.

- Explicit automatic merge with verified source identity may become a Learning Candidate without Human Review.
- If review exists, its event hash and application must be valid.
- `ACCEPT_PAPER` and `ACCEPT_CANDIDATE` select the governed source but cannot bypass snapshot/integrity requirements.
- `EXCLUDE` permanently excludes the record from the current dataset build.
- unresolved or inconsistent review blocks inclusion.

## Deduplication

At most one candidate row per `unified_id` and policy scope appears in a dataset. Cross-policy records are stratified, never silently collapsed.

## Exclusion vocabulary

Examples:

- `HISTORICAL_SNAPSHOT_UNAVAILABLE`
- `FEATURE_SNAPSHOT_HASH_MISMATCH`
- `POLICY_IDENTITY_MISSING`
- `POLICY_SCOPE_MIXED_UNDECLARED`
- `REVIEW_EVENT_HASH_INVALID`
- `EXCLUDED_BY_REVIEW`
- `AMBIGUOUS_MATCH`
- `UNRESOLVED_CONFLICT`
