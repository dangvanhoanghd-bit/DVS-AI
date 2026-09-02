# DVS AI Alpha 3.4.4 — Selection Crash Stability Hotfix

- Replaced per-request QThread creation/destruction with one persistent worker thread.
- Added non-reentrant, coalescing guard around the full coin-selection render path.
- Added Python exception logging to `logs/gui_crash.log`.
- Added native fault capture through `faulthandler` to `logs/native_fault.log`.
- Added fail-closed protection around Unified Core shadow request submission.
- No change to Legacy paper authority, Risk Gate, Exchange, Testnet or LIVE paths.
