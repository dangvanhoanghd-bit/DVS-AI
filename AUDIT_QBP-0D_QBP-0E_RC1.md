# DVS AI QBP-0D / QBP-0E Release Candidate 1

## Implemented

### QBP-0D — Data Equivalence

- Independent, read-only legacy `paper_trades` baseline reader.
- Canonical field-by-field comparison against `PaperTradeSource`.
- Source-qualified identity comparison.
- Deterministic SHA-256 dataset digests.
- Count, label and realized-R aggregate equivalence.
- Explicit mismatch records; no silent tolerance or heuristic deduplication.

### QBP-0E — Burn-in Infrastructure

Quality-eligible resolved outcomes unlock research capabilities at fixed milestones:

- 0: descriptive monitoring only.
- 30: resolved-outcome review.
- 100: ESS, walk-forward, purge/embargo.
- 300: bootstrap, stability, multiple-comparison controls.
- 500: eligible for Paper Authority Handover **review**.

No milestone grants authority. `authority_granted` is always false. MAIN write,
SHADOW apply, recommendation and execution authority remain outside this layer.

## Validation integration

`ValidationRequest` can carry burn-in count and required capabilities. The
orchestrator blocks with `BURN_IN_CAPABILITY_LOCKED:<capability>` when a QBP
study requests a capability before its fixed threshold. Existing non-QBP
callers remain backward compatible.

## Audit command

```bash
python verify_qbp0_release_candidate.py --db data/dvs_paper_trades.db
```

The report qualifies the bundle for audit when data equivalence passes. It does
not qualify production execution or grant Paper Authority Handover.
