# RC6.4.7C

- Moves `PaperTradeService.auto_consider()` to a persistent QThread worker; GUI performs only queue/identity bookkeeping.
- Limits `EpisodeIntegrityMonitorWidget` to the latest 500 rendered rows while preserving full source history.
- Treats numerically equivalent display strings such as `0`, `0.0`, and `0.00` as equal in display-integrity audit.
- Enables SQLite WAL, `synchronous=NORMAL`, explicit 3-second timeout and busy timeout for Paper Trade connections.
- Corrects build identity metadata.
- Decision Engine unchanged.
