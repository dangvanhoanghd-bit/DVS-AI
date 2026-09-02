# Milestone 1.2 — Implementation Notes

## Files changed

- `dvs_ai/integration/models.py`
- `dvs_ai/integration/scientific_backend.py`
- `dvs_ai/integration/__init__.py`
- `dvs_ai/ui/truth_dashboard.py`
- `tests/test_integration_scientific_backend_bridge.py`

## Implemented behavior

- Added immutable `BackendSource` enum.
- Added explicit root-resolution metadata.
- Validates required JSON artifacts before accepting a root.
- Emits explicit reason codes for missing roots, missing artifacts, unreadable roots, and invalid JSON.
- Emits `CONFIGURED_ROOT_FALLBACK_USED` whenever a configured root is replaced by a packaged snapshot.
- Marks fallback status as `DEGRADED`, even when the packaged snapshot itself is fully verified.
- Truth Dashboard now displays active source and active root.
