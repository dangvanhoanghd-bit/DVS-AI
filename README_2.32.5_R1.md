# DVS AI Alpha 2.32.5-r1 — Actionable Semantics Hotfix

This maintenance release corrects the semantic value of `RecommendationResult.actionable` and
hardens the protocol verifier against regression.

- `READY_FOR_MANUAL_REVIEW` → actionable true
- `REVIEW_REQUIRED` → actionable true
- `CONTINUE_PAPER` / `COLLECT_MORE_DATA` / `ANALYSIS_ABORTED` → actionable false

This is not an execution permission. It is an observe-only marker that human review is required.
