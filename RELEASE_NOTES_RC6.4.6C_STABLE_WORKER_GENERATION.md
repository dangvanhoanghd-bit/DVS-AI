# RC6.4.6C — Stable Scan Worker Generation Identity

- Replaces `self.sender() is self.worker` cleanup authority with immutable generation/scan/cycle payloads.
- Emits `finished_with_identity(int, str, int)` before legacy `finished` and before `deleteLater` can affect QObject lifetime.
- Keeps QObject IDs only as observational telemetry; no cleanup branch reads `self.sender()`.
- Adds generation launch/completion/cleanup telemetry and `STALE_GENERATION_IGNORED`.
- Decision Engine unchanged; PAPER-only constraints unchanged.
