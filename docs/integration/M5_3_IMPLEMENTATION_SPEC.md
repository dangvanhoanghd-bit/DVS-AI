# M5.3 Scientific Ledger

Implements an append-only, hash-chained scientific audit ledger. Each transition records run ID, sequence, UTC timestamp, stage, before/after state, success, reason codes, optional artifact reference, previous hash and event hash.

The ledger is independent from GUI, exchange, execution, runtime and databases. Storage is dependency injected. Included stores: in-memory and append-only JSON Lines.
