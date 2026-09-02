# DVS AI Alpha 4.1.0-H

## Integrity History & Incident Ledger

- Adds a separate audit database at `data/dvs_integrity_ledger.db`.
- Canonical episode data remains read-only.
- Persists each integrity snapshot and its issue set.
- Tracks incident lifecycle: NEW, ONGOING, RESOLVED, REOPENED.
- Tracks first seen, last seen, age, occurrence count, and recurrence count.
- Adds the read-only `Integrity History` tab with incident and snapshot timelines.
- Incident identity uses issue code + entity + entity ID; changing detail text does not duplicate incidents.
- Decision Engine, scores, thresholds, gates, activation and outcome logic remain frozen.
