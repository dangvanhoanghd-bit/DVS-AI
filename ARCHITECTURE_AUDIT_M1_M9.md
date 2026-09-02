# DVS AI Alpha — M1–M9 Architecture Audit

## Source set reviewed

Fourteen supplied milestone archives were extracted and compared by relative Python path and SHA-256 content.

## Findings

- The M9.1 hardened archive contains all 407 Python files present in the union of the supplied M1–M9 archives.
- No Python module from an earlier supplied milestone is absent from the M9.1 hardened baseline.
- Earlier milestone archives differ mainly in files that were subsequently revised; therefore blindly overlaying old archives would regress newer fixes.
- The main architectural gap was not missing source files. It was the absence of a single application-level runtime that joins scientific authorization, strategy fusion, risk, paper execution, monitoring, and event diagnostics.
- The legacy product/UI/data/scanner layers remain large and are not rewritten in this sprint. They feed the unified boundary through a normalized `MarketSnapshot` and an existing scientific `pipeline_run_id`.

## Integration decision

Use M9.1 hardened as the canonical baseline. Do not copy older files over newer files. Add a unified application kernel and shared event bus on top of the cumulative source tree.

## Remaining debt

- Wire the desktop GUI/startup command directly to `DVSAICore`.
- Add a production adapter that converts the existing scanner/domain result to `MarketSnapshot` without UI coupling.
- Add persistent event transport if multi-process execution is introduced.
- Add end-to-end tests using recorded Binance data instead of deterministic fixtures.
- Keep live exchange execution disabled until a separately audited live-readiness milestone.
