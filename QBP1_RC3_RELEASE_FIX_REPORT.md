# QBP-1 RC3 Release Fix Report

## Scope

This release candidate fixes the version-identity regression and removes historical version test debt found during independent RC2 audit. No Decision Engine logic was changed.

## Changes

1. `START_DVS_AI.bat`
   - Updated launcher title and banner to `4.3.0E-3-QBP-1-RC2`.
   - Retained the historical `Performance and Stability` launcher safety label.

2. Historical tests
   - Removed hard-coded `4.3.0E-3-QI-3` identity assertions from:
     - `test_v423_executor_sleep_hardening.py`
     - `test_v424_full_python_thread_attribution.py`
     - `test_v425_persistent_scan_qthread.py`

3. Centralized dynamic release identity validation
   - Added `tests/test_release_identity.py` using `APP_VERSION` as the source of truth.
   - Updated `test_v350_qualification_batch_runner.py` so it no longer couples the current edition label to a historical feature name.

## Verification

- Focused release/version tests: `26 passed`
- Full test suite: `893 passed`
- Official QBP-1 verifier: `QUALIFIED_OBSERVE_ONLY_COLLECTION`
- Eligible outcomes: `0`
- Authority granted: `false`
- Production or execution authority: `false`

## Decision Engine

Frozen Decision Engine identity remains:

- MD5: `72cf7d54e1ed6369400683358da8c0ef`
- SHA-256: `00c1db1a1684896b3c06fbf4cfaeea094337f1841dc2e3cb9dfdf9013252dbce`

This RC does not claim real-data burn-in completion or paper-authority handover.
