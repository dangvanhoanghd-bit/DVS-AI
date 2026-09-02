# M4 Implementation Specification — Learning & Model Registry Integration

## Goal
Expose model registry state to the desktop GUI through the existing read-only JSON bridge.

## Safety constraints
- No import of Scientific Engine Python packages.
- No registry mutation.
- No model promotion, rollback, deployment, TESTNET, or LIVE action.
- Missing or malformed artifacts resolve to explicit UNAVAILABLE states.

## Artifact contract
`MODEL_REGISTRY.json` may provide:
- `registry_status`
- `generated_at`
- `current_model`
- `models` / `model_history`
- `reason_codes`

Each model may provide model ID, version, training timestamp, registry status, maturity, certification flag, certificate ID, and reason codes.
