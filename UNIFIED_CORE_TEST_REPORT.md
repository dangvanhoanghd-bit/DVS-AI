# Unified Core Test Report

- New integration tests: 3 passed.
- Full regression suite: 594 passed in 6.44 seconds.
- Compile check: `python -m compileall -q dvs_ai` passed.

## New integration coverage

- Scientific AVAILABLE run -> strategy fusion -> authorized decision -> risk -> filled paper order.
- Missing scientific run -> fail-closed decision -> rejected paper order -> alert.
- Event handler exception isolation -> cycle continues -> diagnostic alert.
