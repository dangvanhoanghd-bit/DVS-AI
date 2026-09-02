# QI-1 Runtime Governance Integration

This patch closes the audited live-application bypass without changing the frozen Decision Engine.

## Runtime behavior

- `run_quantum_optimizer()` now performs a fail-closed governance preflight before creating the optimizer thread.
- `apply_quantum_shadow()` now performs a fail-closed governance preflight before candidate creation, backtesting, confirmation dialogs, or SHADOW writes.
- Missing, corrupt, unsealed, or authority-free governance bundles block both actions.
- The 4.3.0E-3 governance manifest is audit-readiness only and explicitly denies optimizer/SHADOW authority, so the legacy UI paths are intentionally blocked.
- A later sealed governance release may explicitly add `runtime_authority.optimizer_allowed` and `runtime_authority.shadow_apply_allowed`.

## Configuration

Set `DVS_QUANTUM_GOVERNANCE_BUNDLE` to the sealed audit bundle directory. No configured bundle means BLOCK.

## Safety boundary

This integration does not alter Decision Engine logic, thresholds, heuristics, execution authority, or MAIN configuration.
