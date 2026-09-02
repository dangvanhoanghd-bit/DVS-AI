## 4.0.5 - Actionable Evidence Quality Gate

- Corrected Qualification Batch regime/phase extraction to use `analysis.regime.regime` and `analysis.phase_summary`.
- Added frozen governance gates `minimum_actionable_count=30` and `minimum_actionable_ratio=5%`.
- Prevented trivial NO_ACTION agreement from reaching governance readiness.
- Added actionable evidence metrics, gap reporting, and `UNOBSERVABLE` decision-confidence semantics.
- Preserved Legacy paper authority, SHADOW_ONLY Unified Core, append-only evidence, and all execution locks.

## 4.0.4 - Qualification Performance & Launcher Stability

- Fixed CMD launcher parsing caused by an unescaped ampersand.
- Added lazy Evidence refresh and on-demand Replay/Decision Graph construction.
- Removed heavy read-only UI projection work from the scan completion path.

# Alpha 2.29.3 — Historical Evidence Platform Complete

- Added unified HistoricalEvidenceRepository and candidate dossiers.
- Added integrity audit across lifecycle, snapshots and readiness references.
- Added ranked historical comparison and lifecycle/readiness details to Truth Dashboard V2.
- Preserved archived candidate evidence.
- 426/426 tests PASS; MAIN immutable; LIVE disabled.

# Alpha 2.29.2 — Historical Readiness Trend Audit

- Added multi-snapshot historical readiness audit.
- Added append-only readiness trend events.
- Prevented one strong snapshot from triggering readiness.
- Added drift, drawdown, Brier, coverage, dispersion, and trend guardrails.
- Integrated guarded OBSERVING -> READY_FOR_REVIEW transition.
- MAIN remains immutable; LIVE execution remains disabled.

# Alpha 2.29.1 — Historical Snapshot Runtime Integration

- Added deterministic snapshot runtime driven by closed PAPER observations.
- Added snapshot-key uniqueness and replay-safe deduplication.
- Added automatic APPLIED_TO_SHADOW → OBSERVING transition on first real snapshot.
- Added expectancy, drawdown, win rate, profit factor, Brier, ECE, reliability, drift and regime metrics.
- MAIN immutable; LIVE execution disabled.

## 2.30.0 — Commercial Truth Dashboard V3
- Rebuilt Truth Dashboard inside a responsive QScrollArea.
- Added readable KPI cards, AI Health and Next Action summaries.
- Stacked historical charts and added independent table sizing/scrolling.
- Throttled heavy history refreshes to 10 seconds.
- Preserved observe-only boundaries; MAIN and LIVE remain locked.

## 2.31.0 — Operational Validation Platform
- Added AI Health, Data Coverage, Confidence Distribution, Regime Validation and Alert Center.
- Added append-only health history and Truth Dashboard Operational Validation Center.
- No Decision, Quantum, Promotion or Execution behavior changed.

## 2.33.0-M1
- Added read-only Scientific Backend Integration Bridge and Truth Dashboard status card.


## 4.0.1 — Explainable Decision Timeline & Graph
- Added a deterministic Decision Graph generated only from persisted Evidence records.
- Added node-level Inspector with status, stored evidence context and descriptive confidence contribution.
- Added Timeline and Decision Graph views inside the read-only Replay workspace.
- Fixed Evidence selection so the selected record is immediately loaded into Replay.
- Preserved SHADOW_ONLY, quantity 0, Legacy paper authority and all execution locks.

## 4.0.3 - Audit Hardening Hotfix
- Preserve persisted confidence with a descriptive `baseline_confidence` node when no reason/event evidence exists.
- Enforce and expose the Decision Graph confidence-conservation invariant.
- Replace silent Batch Runner item failures with structured diagnostics and traceback logging.
- Add bounded rotating JSONL failure journal and per-item failure signal.
- Keep bounded FIFO, persistent QThread, Shadow-only Unified Core, and Legacy Paper Authority unchanged.
