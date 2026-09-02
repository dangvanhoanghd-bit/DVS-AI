# Model Registry Specification

Each Model Slot is an immutable self-sealed manifest. The registry is a derived index. Even `EMPTY` slots carry Policy Identity, Extraction Identity, Feature Schema Identity, source bundle, source split, and hashes.

Frozen states: `EMPTY`, `RESERVED`, `TRAINING`, `TRAINED_UNVALIDATED`, `VALIDATED`, `REJECTED`.
