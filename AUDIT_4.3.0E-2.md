# Audit — DVS AI Alpha 4.3.0E-2

## Safety boundary

- Decision Engine mutation: forbidden
- Trade execution: forbidden
- MAIN/SHADOW write: forbidden
- Recommendation authority: forbidden
- Causal claims: forbidden

## Statistical controls

- Family-wise error: Holm-Bonferroni
- Bootstrap unit: market-event cluster
- Stability dimensions: fold, regime, symbol, sign, parameter neighborhood
- Missing required diagnostics: fail closed
