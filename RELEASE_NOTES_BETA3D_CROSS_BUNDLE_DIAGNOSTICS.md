# Release Notes — Beta 3D Cross-Bundle Comparative Diagnostics

Implemented a read-only cross-bundle data diagnostics layer on top of Beta 3B and Beta 3C.

Key additions:
- verified, rebuildable bundle registry
- explicit Type A/B/C comparison classification
- raw change metrics separated from descriptive labels
- burn-in-aware comparison suppression
- bundle lineage graph and anomaly detection
- hard-constraint, Pareto, deterministic lexicographic promotion
- absolute eligibility fallback capped at `ELIGIBLE_CANDIDATE`

Decision Engine and existing bundle formats are unchanged.
