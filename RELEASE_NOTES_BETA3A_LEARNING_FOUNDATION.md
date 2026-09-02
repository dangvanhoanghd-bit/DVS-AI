# Release Notes — Beta 3A Learning Foundation

Beta 3A is the first implementation slice after Beta 3 Design Freeze. It implements only governed candidate and feature projection. It does not train a model or alter trading decisions.

Added:
- `dvs_ai/services/beta3_learning_foundation.py`
- `tests/test_beta3a_learning_foundation.py`
- `BETA3_TEST_FIRST_IMPLEMENTATION_SPEC.md`

Safety properties:
- source contract is `UnifiedOutcomeService.learning_ready()`;
- no direct database query;
- no new snapshot source;
- QG-13 policy identity preserved;
- QBP burn-in thresholds reused;
- full data lineage emitted as immutable dictionaries.
