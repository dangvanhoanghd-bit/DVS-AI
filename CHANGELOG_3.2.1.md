# DVS AI Alpha 3.2.1 — UI Projection Recovery

- Replaced invalid QLabel.setHtml() call with QLabel.setText() rich-text rendering.
- Isolated Smart Entry, Decision Core and Liquidity/Wyckoff projections so one UI failure cannot blank other tabs.
- Added shared-selection projection for Liquidity/Wyckoff.
- Restored Easy Mode summary rendering after Smart Entry projection errors.
- Updated Windows launcher identity to 3.2.1.
- No changes to Decision, Risk, Paper, Exchange, Testnet or LIVE order paths.
