# Dataset Builder Specification

## Input boundary

The builder consumes only governed Feature Store rows produced from `UnifiedOutcomeService.learning_ready()` records.

## Required pipeline

1. verify source bundle and manifest hashes;
2. verify row hashes and lineage completeness;
3. enforce one governed policy scope or declared stratification;
4. apply feature quality rules;
5. enforce terminal outcome vocabulary;
6. deduplicate by `unified_id` plus policy scope;
7. calculate qualified count and QBP burn-in state;
8. evaluate cohort coverage and leakage checks;
9. emit dataset only when state is at least `DESCRIPTIVE_ONLY`;
10. create self-sealed manifest.

## Under-threshold behavior

For fewer than 30 qualified samples:

- state = `UNOBSERVABLE`;
- dataset emission = blocked;
- report includes exact counts and exclusion reasons;
- no empty JSONL/CSV artifact may be presented as a successful dataset.

## Dataset row contract

Each row must contain:

- outcome target fields;
- normalized feature vector;
- policy identity;
- source lineage references;
- feature quality summary;
- review provenance;
- source and row checksums.

## Leakage prevention

Features with timestamps after the governed decision boundary are invalid. Outcome-derived fields cannot appear in the input feature vector. The outcome remains a target/label field only.
