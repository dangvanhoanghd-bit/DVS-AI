# QI-2 Operational Hardening

Runtime governance now requires both an allowed bundle root and a trusted SHA-256 fingerprint of `audit_bundle.index.json`. Every startup self-test and runtime authorization decision is appended to a hash-chained JSONL audit ledger. The UI performs a startup governance self-test immediately after constructing the runtime guard. Missing policy, untrusted fingerprints, disallowed paths, malformed/tampered bundles, denied authority, and audit-log creation failure are fail-closed.

Required production environment variables:

- `DVS_QUANTUM_GOVERNANCE_BUNDLE`
- `DVS_QUANTUM_ALLOWED_BUNDLE_ROOTS`
- `DVS_QUANTUM_TRUSTED_BUNDLE_SHA256`
- optional `DVS_QUANTUM_RUNTIME_AUDIT_LOG`

Do not trust development/test fingerprints in production. Rotate a bundle by sealing the new bundle, approving its index fingerprint through the operational change process, then replacing the configured bundle path/fingerprint atomically.
