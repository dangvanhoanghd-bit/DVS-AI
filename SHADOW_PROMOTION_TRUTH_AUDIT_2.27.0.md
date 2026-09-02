# DVS AI Alpha 2.27.0 — Human-Gated Shadow Promotion Truth Audit

## Verified scope
- Chronological PAPER truth-qualified holdout simulation before apply.
- Fee/slippage adjustment, minimum trades, expectancy, drawdown and Brier guardrails.
- Two-step UI confirmation.
- SHADOW-only allowlist writer with atomic config replacement.
- Mandatory config backup, promotion audit log and guarded rollback API.
- MAIN remains byte-value invariant; LIVE remains disabled.

## Limitations
- No automatic promotion to MAIN.
- No automatic rollback based on performance.
- Backtest cannot observe counterfactual outcomes for signals never opened.
- Regime-specific weights are not enabled in this release.
