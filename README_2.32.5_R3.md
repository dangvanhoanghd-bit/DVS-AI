# DVS AI Alpha 2.32.5-r3 — Runtime Contract & DB Alignment Hotfix

Fixes Quantum UI `KeyError: base_validation` with a fail-closed report contract.
All PAPER-related services now use one explicit canonical SQLite path.
Shadow observation startup migration runs before runtime threads and diagnostics expose the absolute DB path, schema/index state and duplicate archive count.
New timestamps remain UTC ISO-8601. Existing mixed timestamps are not rewritten automatically.
