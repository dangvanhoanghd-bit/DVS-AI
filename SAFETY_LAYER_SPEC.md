# Safety Layer Specification

## Separate enforcement boundary

The Safety Layer is a final, explicit gate over every Beta 3 artifact and service.

## Forbidden capabilities

- write access to Decision Engine source/configuration;
- threshold or confidence mutation;
- order creation/execution;
- promotion to MAIN or SHADOW policy;
- automatic model training;
- direct operational database mutation;
- recommendation language presented as execution advice.

## Required checks

- Decision Engine checksum equals frozen value;
- source database opened read-only where applicable;
- no direct legacy consumer SQL bypass;
- manifest and row hashes verify;
- burn-in state authorizes requested analysis;
- statistical controller results are present for association insights;
- complete lineage exists;
- no unresolved review/integrity finding;
- no mixed policy scope without declared stratification.

## Fail-closed states

Any critical failure returns `DATA_INTEGRITY_BLOCKED` and suppresses dataset/insight publication.

## Frozen Decision Engine identity

- MD5: `72cf7d54e1ed6369400683358da8c0ef`
- SHA-256: `00c1db1a1684896b3c06fbf4cfaeea094337f1841dc2e3cb9dfdf9013252dbce`
