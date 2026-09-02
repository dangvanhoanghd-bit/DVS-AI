# DVS AI Alpha 4.3.0D-1 — Historical Replay Foundation

Implemented the first real 4.3.0D code slice:

- deterministic FIRST_ELIGIBLE_PLAN provenance validation;
- policy scope, Decision Engine checksum, TradePlan hash and source-row identity checks;
- explicit INVALID_REPLAY state;
- future/outcome field exclusion from replay evidence;
- self-sealed JSONL replay bundle and independent verifier;
- no optimizer, recommendation, SHADOW write, MAIN write, or execution authority.

This slice does not yet implement historical ablation or uncertainty estimation.
