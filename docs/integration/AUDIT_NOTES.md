# Audit Notes

This is a read-only status bridge, not full module integration.

Known limits:
- bundled data is a verified release snapshot, not live backend telemetry;
- external live status can be selected only by setting `DVS_SCIENTIFIC_BACKEND_ROOT`;
- validation, evidence delta, registry, runtime and execution APIs are intentionally not wired yet;
- LIVE remains NOT_AUTHORIZED and no UI control can change it.
