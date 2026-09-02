# DVS AI Beta 1B — Outcome Resolution Lifecycle

- Adds append-only `candidate_outcome_events` timeline.
- Tracks entry/follow-up/TP1/TP2/terminal lifecycle without changing Decision Engine.
- Makes outcome persistence transactional and claim-owned.
- Prevents terminal outcome overwrite and duplicate terminal events.
- Learning samples remain gated by resolved outcome + immutable feature snapshot.
- Observe-only; no execution authority, threshold, MAIN/SHADOW, Quantum, or Decision Engine changes.
