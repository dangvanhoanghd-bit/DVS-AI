# DVS AI Alpha 2.32.5-r2 — Data Pipeline Integrity Hotfix

Run normally for new databases. To explicitly migrate an existing PAPER database with a backup:

```bash
python migrate_shadow_observation_duplicates_2_32_5_r2.py data/dvs_paper_trades.db
```

The Paper Trade tab now shows runtime diagnostics. After a scan:

- `evaluated = 0`: Auto Paper is OFF or its batch was not invoked.
- `evaluated > 0`, `eligible = 0`: runtime ran, but all signals failed gates.
- `eligible > 0`, `created = 0`: inspect duplicate/capacity blocked counters.
