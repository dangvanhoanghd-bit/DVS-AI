# DVS AI Alpha 4.1.0-C-r1

## Live Episode Capture + Gate Effectiveness & Cohort Analytics

- Baseline: 4.1.0-C.
- Merged the audited Live Episode Capture integration from 4.1.0-B-r2.
- Completed scan results are recorded by SignalRecorder and then captured into the canonical outcome infrastructure.
- Uses the existing data/dvs_paper_trades.db database; no parallel decision database is introduced.
- Gate Effectiveness, Calibration, Cohort Analytics, Candidate Funnel, JSON and HTML exports from 4.1.0-C are retained.
- Decision Engine and every source file under dvs_ai/engines remain byte-for-byte unchanged from 4.1.0-C.
- Capture failures are isolated and logged without stopping the scan pipeline.
