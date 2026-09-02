# Beta 4A Feature Matrix Builder RC1 — Test Report

Executed in the extracted repository workspace.

- Focused M2 tests: **9 passed**
- All Beta 4A tests: **44 passed**
- Full repository regression: **1167 passed**
- Python compile verification: **PASS**

Primary test coverage:

- schema identity changes when categorical order changes;
- deterministic output independent of source row iteration and mapping order;
- frozen column ordering;
- missing feature exclusion and strict hard-block mode;
- unseen categorical exclusion without dynamic columns;
- M4 hard-block propagation;
- split/bundle/schema identity consistency;
- stable machine-readable manifest output.
