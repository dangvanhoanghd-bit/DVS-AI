# DVS AI Alpha 4.3.0E-3 QBP-4 RC7

## Confidence Sort Recovery

- Fixes a lifecycle bug where `_launch_scan()` disabled table sorting and finalization only restored it when sorting was already enabled.
- Finalization now always restores column 1 (Confidence) in descending order and rebuilds the symbol-to-row index afterwards.
- The scan-runtime-unavailable failure path also restores sorting before returning.
- Decision Engine, thresholds, MAIN/SHADOW policy, Quantum governance, and execution authority are unchanged.
