# DVS AI Alpha 2.22.7 — UI Performance Profiler

## Purpose

Measure the short UI stalls seen in the two screen recordings instead of
guessing which widget is responsible.

## Instrumented sections

- `on_finished_total`
- `show_selected`
- `refresh_summary`
- `refresh_paper_trade_tab`
- `refresh_learning_center`
- `refresh_microstructure_tab`
- `refresh_history_tab`

## Runtime logs

Slow section:

`UI_SLOW_SECTION name=show_selected elapsed_ms=...`

Event-loop stall:

`UI_EVENT_LOOP_STALL level=WARNING delay_ms=... section=...`

Per-scan report:

`UI_PERFORMANCE_REPORT reason=scan_finished report=...`

## Installation

Copy into `dvs_ai/ui/`:

- `main_window.py`
- `ui_geometry_manager.py`
- `ui_performance_profiler.py`

No `.pyc` files are required.
