# Learning Engine Specification — Beta 3

## Definition

The Beta 3 Learning Engine is a deterministic descriptive-analysis engine. It does not fit or persist a predictive model.

## Allowed analyses by burn-in state

- `UNOBSERVABLE`: counts, exclusions, integrity, coverage only.
- `DESCRIPTIVE_ONLY`: univariate distributions, quantiles, missingness, outcome rates with confidence intervals.
- `RESEARCH_CANDIDATE_ONLY`: governed exploratory associations with multiplicity control.
- `VALIDATION_REVIEW_ELIGIBLE`: stability by time/cohort/policy scope, bootstrap validation, sensitivity diagnostics.
- `BURN_IN_COMPLETE`: same as above plus readiness report for a future model-design phase; still no training.

## Bias diagnostics

- class imbalance;
- symbol concentration;
- direction concentration;
- time-period concentration;
- policy-scope fragmentation;
- review-selection bias;
- missing-feature bias;
- survivor/eligibility bias;
- market-event cluster dependence and effective sample size.

## Output language

The engine reports observations and associations, not causal claims or trading recommendations.
