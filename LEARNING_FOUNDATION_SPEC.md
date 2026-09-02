# Learning Foundation Specification

## Purpose

Provide a governed, read-only foundation that converts verified Unified Outcomes into versioned research datasets and descriptive diagnostics.

## Explicit non-goals

- no supervised/unsupervised model training;
- no online learning;
- no parameter search;
- no threshold adjustment;
- no confidence recalibration;
- no Decision Engine write path;
- no execution or recommendation authority.

## Inputs

Only records returned by `UnifiedOutcomeService.learning_ready()` are considered. The implementation must not bypass the service with direct SQL to `paper_trades`, `candidate_outcomes`, or snapshot tables.

## Output contracts

1. `LearningCandidateSet`
2. `FeatureStoreBundle`
3. `TrainingDatasetBundle`
4. `LearningDiagnosticsReport`
5. `GovernedInsightReport`

All bundles are immutable and self-sealed.

## Burn-in contract

Qualified sample count uses the existing QBP scale:

| Count | State | Permitted output |
|---:|---|---|
| 0–29 | `UNOBSERVABLE` | integrity/coverage report only; no training dataset artifact |
| 30–99 | `DESCRIPTIVE_ONLY` | univariate descriptive summaries |
| 100–299 | `RESEARCH_CANDIDATE_ONLY` | governed exploratory associations |
| 300–499 | `VALIDATION_REVIEW_ELIGIBLE` | stronger validation diagnostics, still no training |
| >=500 | `BURN_IN_COMPLETE` | foundation considered statistically populated; model work remains a later Beta |

A zero-row or below-threshold build must not be labelled success and must not create a misleading empty dataset.

## Determinism

Given identical source records, snapshot bytes, policy scope, software version, and configuration, the generated rows and manifests must be byte-identical.
