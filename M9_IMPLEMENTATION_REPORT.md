# M9 Strategy Intelligence Layer — Implementation Report

## Scope

M9 adds a simulation-safe strategy intelligence layer without any exchange execution path.

Implemented packages:

- `dvs_ai.strategy_intelligence.sdk`: versioned strategy protocol and registry.
- `dvs_ai.strategy_intelligence.regime`: deterministic market-regime detection.
- `dvs_ai.strategy_intelligence.scores`: out-of-sample strategy reliability registry.
- `dvs_ai.strategy_intelligence.fusion`: weighted multi-strategy signal fusion.
- `dvs_ai.strategy_intelligence.engine`: registry → regime → signal → fusion orchestration.
- `dvs_ai.strategy_intelligence.backtest`: deterministic next-bar historical replay.

## Safety boundaries

- No Binance order submission was added.
- Missing regime features resolve to `UNKNOWN`.
- Conflicting or weak consensus resolves to `NEUTRAL`.
- Regime-incompatible strategies are excluded from fusion.
- Reliability uses sample-size shrinkage so tiny histories cannot dominate.
- Backtesting is simulation-only and supports explicit transaction fees.

## Public API

Import from `dvs_ai.strategy_intelligence`.
