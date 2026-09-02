# DVS AI Alpha 2.22.6 — UI Geometry Framework

This patch separates UI geometry management from `MainWindow`.

Files to copy into `dvs_ai/ui/`:

- `main_window.py`
- `ui_geometry_manager.py`

Main changes:

- Single startup geometry authority.
- Responsive COMPACT / STANDARD / WIDE breakpoints.
- Bounded repaint freeze during Auto Scan final refresh.
- Tab and scroll preservation without forcing native window geometry.
- User maximize/fullscreen/manual resizing remain authoritative.
- Non-recursive geometry diagnostics.

No trading or analysis logic was changed.
