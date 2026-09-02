# M4 Implementation Notes

Implemented immutable `ModelVersionSummary` and `ModelRegistrySummary` models.

Added read-only bridge APIs:
- `get_registry_summary()`
- `get_current_model()`
- `get_model_history()`

`ScientificSummary` now includes registry state. Truth Dashboard renders registry status, active model and maturity.

The packaged snapshot contains a conservative NOT_READY registry artifact and does not claim a certified current model.
