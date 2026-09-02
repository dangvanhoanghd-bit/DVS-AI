# RC6.4.7F-r3 — Bounded UI Reference Owner Attribution

Build: `RC6.4.7F-r3-BOUNDED-UI-REFERENCE-OWNER-ATTRIBUTION`

Changes:
- Atomic one-OS-write JSONL records.
- Exact token transitions for `MainWindow.current_analysis`.
- Exact token transitions for `MainWindow._truth_dashboard_pending_analysis`.
- Exact token transitions for `TruthDashboard._last_analysis`.
- Explicit lifecycle for `QTimer.singleShot.truth_dashboard_seed_closure`.
- Primitive-only QObject snapshots (parent class, child count, visibility, enabled state).
- Decision Engine unchanged.
