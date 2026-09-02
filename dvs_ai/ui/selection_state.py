"""Central, UI-agnostic selection state for the unified desktop application.

The state deliberately contains no Qt objects.  It can therefore be tested in
isolation and used by every tab without creating signal loops.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional


def normalize_symbol(symbol: object) -> Optional[str]:
    """Return a canonical exchange symbol or ``None`` for invalid input."""
    if symbol is None:
        return None
    value = str(symbol).strip().upper()
    return value or None


@dataclass(frozen=True, slots=True)
class SelectionSnapshot:
    symbol: Optional[str] = None
    timeframe: str = "15m"
    source: str = "startup"
    revision: int = 0


class SelectionState:
    """Single source of truth for the symbol/timeframe selected in the UI."""

    def __init__(self) -> None:
        self._snapshot = SelectionSnapshot()

    @property
    def snapshot(self) -> SelectionSnapshot:
        return self._snapshot

    @property
    def symbol(self) -> Optional[str]:
        return self._snapshot.symbol

    @property
    def timeframe(self) -> str:
        return self._snapshot.timeframe

    def select(
        self,
        symbol: object,
        *,
        timeframe: Optional[str] = None,
        source: str = "unknown",
    ) -> SelectionSnapshot:
        canonical = normalize_symbol(symbol)
        selected_timeframe = str(timeframe or self._snapshot.timeframe or "15m")
        selected_source = str(source or "unknown")
        changed = (
            canonical != self._snapshot.symbol
            or selected_timeframe != self._snapshot.timeframe
            or selected_source != self._snapshot.source
        )
        if changed:
            self._snapshot = replace(
                self._snapshot,
                symbol=canonical,
                timeframe=selected_timeframe,
                source=selected_source,
                revision=self._snapshot.revision + 1,
            )
        return self._snapshot

    def clear(self, *, source: str = "clear") -> SelectionSnapshot:
        return self.select(None, timeframe="15m", source=source)
