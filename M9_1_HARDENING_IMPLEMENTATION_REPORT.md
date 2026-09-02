# M9.1 Strategy Intelligence Integration & Hardening

## Implemented

- Added `StrategyDecisionBridge` to convert M9 fused signals into `DecisionRequest` objects and pass them through the existing Scientific `DecisionAdapter`.
- Enforced fail-closed handling for neutral fused signals; neutral can never become an executable authorization.
- Added atomic, versioned JSON persistence with `JsonStrategyScoreStorage`.
- Added `StrategyScoreRegistry.restore()` with duplicate and aggregate validation.
- Added strategy exception containment in `StrategyIntelligenceEngine`.
- Added protection against a strategy returning a mismatched `strategy_id`.
- Kept the implementation simulation-only; no exchange order execution path was added.

## Changed files

- `dvs_ai/strategy_intelligence/integration.py`
- `dvs_ai/strategy_intelligence/storage.py`
- `dvs_ai/strategy_intelligence/engine.py`
- `dvs_ai/strategy_intelligence/scores.py`
- `dvs_ai/strategy_intelligence/__init__.py`
- `tests/test_m9_strategy_intelligence.py`
