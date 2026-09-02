# Audit — DVS AI Alpha 4.3.0C

- Decision Engine source: unchanged from 4.3.0B baseline.
- Explainability consumes only a sealed Research Dataset.
- Dataset and explanation manifests are self-sealed with SHA-256.
- `outcome_status`, `realized_r`, `mfe_r`, `mae_r`, and future fields are forbidden as evidence.
- Missing evidence is reported explicitly and never reconstructed.
- No execution, optimizer, recommendation, SHADOW-write, or MAIN-write authority.
- QG contract: QG-01 through QG-16.

## Qualification result

- `python -m compileall`: PASS.
- Full pytest suite: **821 passed**.
- New 4.3.0C tests: **6 passed**.
- Frozen Decision Engine MD5: `72cf7d54e1ed6369400683358da8c0ef`.
- Frozen Decision Engine SHA-256: `00c1db1a1684896b3c06fbf4cfaeea094337f1841dc2e3cb9dfdf9013252dbce`.
- Decision Engine is byte-identical to the 4.3.0B baseline.
- Bundled sample operational database remains `DATA_INTEGRITY_BLOCKED`; Explainability correctly propagates this as `DATASET_INTEGRITY_BLOCKED` and emits no explanation records.
