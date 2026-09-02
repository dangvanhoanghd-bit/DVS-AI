# DVS AI Alpha 2.22.4 — Responsive Window Geometry

The previous 1600x940 startup request was converted by Windows DPI scaling to
approximately 2277–2307 physical pixels on a 1920px display. Windows rejected
the request, causing repeated geometry negotiation.

Corrections:
- Removed the hard main-window resize.
- Open through platform-managed `showMaximized()`.
- Split the toolbar into two rows.
- Made the right result rail responsive (380–500px).
- Reduced horizontal minimum-width pressure.
- Added read-only geometry diagnostics.
- Auto Scan never mutates main-window geometry.

No trading or analysis logic changed.
