# DVS AI Alpha 3.4.3

## Agreement Classifier Unification

- Added immutable `AgreementResult` as the canonical classification value.
- GUI display, SQLite evidence, metrics and governance now derive from one classifier.
- Removed duplicate inline classification from `main_window.py`.
- Retained a backward-compatible code-only facade for existing callers/tests.

## Shadow Qualification Dashboard

- Added Decision Core dashboard for frozen-profile progress.
- Displays paired cycles, FULL agreement ratio, unsafe hard-gate count,
  profile id/hash, qualification status, and the unchanged LEGACY paper authority.
- Dashboard is observe-only; no activation, promotion, handover or execution API
  was added.
