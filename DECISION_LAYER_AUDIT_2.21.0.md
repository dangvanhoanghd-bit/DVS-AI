# DVS AI Alpha 2.21.0 — Decision Layer Audit

## Corrected findings

1. Footprint could resurrect READY after Direction Confirmation had BLOCKed it.
2. Position Building was counted inside Footprint and again as a full Decision weight.
3. Missing OI history was treated as zero persistence/acceleration evidence.
4. Arithmetic confidence fusion allowed a strong layer to compensate for a weak one.
5. Status could change after Footprint while action/timing/priority stayed stale.
6. PaperTradeService normalized `lab` twice.

## Preserved invariants

- Decision Engine remains the sole decision authority.
- Risk, liquidation and R:R hard gates cannot be offset by quality.
- MAIN/SHADOW thresholds were not lowered.
- Execution stays PAPER by default and LIVE automation remains disabled.
