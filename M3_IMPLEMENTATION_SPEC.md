# DVS AI Alpha — Milestone 3 Explainability Integration

## Scope
Read-only explainability integration through JSON artifacts. The GUI does not import Scientific Engine packages and does not mutate engine, database, exchange, runtime, TESTNET, or LIVE state.

## Artifact
`EXPLAINABILITY_SUMMARY.json`

## Read-only APIs
- `get_explainability_summary()`
- `get_decision_trace()`
- `get_scientific_summary()` now includes explainability and decision trace.

## Required behavior
Missing or invalid artifacts return `UNAVAILABLE`. Empty evidence or validation references are surfaced with explicit reason codes; the bridge does not invent references.
