# Unified Core Implementation Report

## Added packages

- `dvs_ai/core/events.py`
- `dvs_ai/core/event_bus.py`
- `dvs_ai/application/models.py`
- `dvs_ai/application/kernel.py`

## Runtime flow

1. Accept normalized market snapshot and scientific run id.
2. Publish `market.snapshot.accepted`.
3. Evaluate all M9 strategy plugins and fuse their outputs.
4. Publish `strategy.signal.fused`.
5. Authorize through the M5 ledger and M6 decision gate.
6. Publish `scientific.decision.created`.
7. Apply M7 risk limits and execute paper-only order.
8. Publish `paper.order.completed`.
9. Record M8 heartbeat and alerts.

## Safety properties

- Missing or invalid scientific run fails closed.
- Neutral/unauthorized decisions cannot create a filled paper order.
- Risk checks remain mandatory.
- Event subscriber failures are isolated and surfaced through alerts.
- No live exchange order path was added.
