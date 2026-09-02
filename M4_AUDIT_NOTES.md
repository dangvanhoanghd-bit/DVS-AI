# M4 Audit Notes

## Preserved boundaries
- Bridge remains artifact-based and read-only.
- No direct Scientific Engine package import.
- No database write path.
- No exchange, deployment, TESTNET or LIVE path.

## Fail-closed behavior
- Missing artifact => UNAVAILABLE + MODEL_REGISTRY_NOT_AVAILABLE.
- Invalid JSON => UNAVAILABLE + MODEL_REGISTRY_INVALID.
- Invalid model-list shape => UNAVAILABLE + MODEL_REGISTRY_MODELS_INVALID.
- Missing current model is surfaced with CURRENT_MODEL_NOT_AVAILABLE; it is not invented.

## Remaining limitation
A visual smoke test with the real PySide6 runtime on the target Windows environment remains required for final GUI acceptance.
