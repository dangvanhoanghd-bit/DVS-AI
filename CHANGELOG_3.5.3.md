# DVS AI Alpha 3.5.3 — Scientific Qualification Report

## Added
- Read-only Scientific Qualification Report service.
- JSON, HTML, and dependency-free archival PDF export.
- Executive qualification summary, integrity counts, and breakdowns by symbol, regime, phase, and confidence bucket.
- Explicit governance recommendation: `NOT_READY` or `READY_FOR_GOVERNANCE_REVIEW`.
- GUI button in Qualification Evidence Center for exporting the complete report package.

## Safety invariants
- Unified Core remains `SHADOW_ONLY`.
- Paper Authority remains `LEGACY`.
- No automatic promotion, activation, authority switching, or exchange-order path was added.
- Report generation is read-only.

## Validation
- Python compileall: PASS.
- Full regression suite: 670 passed.
