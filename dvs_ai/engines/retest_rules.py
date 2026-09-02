from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetestAssessment:
    confirmed: bool
    score: float
    reason: str


def breakout_buffer(price: float, atr: float) -> float:
    """Minimum meaningful breakout: ATR buffer or 0.10% of price."""
    return max(0.15 * max(atr, 0.0), abs(price) * 0.001)


def unavailable_retest(reason: str) -> RetestAssessment:
    return RetestAssessment(False, 0.0, reason)


def assess_retest(
    *,
    direction: str,
    close: float,
    high: float,
    low: float,
    level: float,
    atr: float,
    relative_volume: float,
    breakout_close: float,
    current_volume: float | None = None,
    event_volume: float | None = None,
    current_spread: float | None = None,
    event_spread: float | None = None,
) -> RetestAssessment:
    """
    Direction-aware retest validation.

    A valid retest requires:
    - meaningful breakout;
    - touch/revisit of the old level;
    - close on the correct side;
    - preferably lower volume than both baseline and breakout event;
    - preferably contracting spread.
    """
    side = direction.upper()
    buffer = breakout_buffer(level, atr)
    proximity = max(0.20 * max(atr, 0.0), abs(level) * 0.0005)

    if side == "LONG":
        breakout_ok = breakout_close >= level + buffer
        touched = low <= level + proximity
        held = close > level
    elif side == "SHORT":
        breakout_ok = breakout_close <= level - buffer
        touched = high >= level - proximity
        held = close < level
    else:
        return unavailable_retest("Direction must be LONG or SHORT.")

    if not breakout_ok:
        return unavailable_retest("Breakout chưa đủ lớn.")
    if not touched:
        return unavailable_retest("Chưa có retest.")
    if not held:
        return RetestAssessment(False, 5.0, "Retest nhưng chưa giữ được level.")

    baseline_contracts = 0 <= relative_volume <= 0.75
    event_contracts = (
        current_volume is not None
        and event_volume is not None
        and event_volume > 0
        and current_volume <= event_volume * 0.90
    )
    spread_contracts = (
        current_spread is not None
        and event_spread is not None
        and event_spread > 0
        and current_spread <= event_spread * 0.90
    )

    score = 9.0
    reason = "Retest giữ level nhưng volume chưa co rõ."

    if baseline_contracts:
        score = 13.0
        reason = "Retest giữ level với volume thấp hơn baseline."
        # Backward-compatible legacy path: callers without breakout-event
        # volume keep the previous low-volume scoring. New SmartEntry calls
        # always provide event volume and use the stricter model below.
        if event_volume is None and relative_volume <= 0.60:
            score = 20.0
            reason = "Retest chất lượng cao: giữ level và volume cạn."
    if event_contracts:
        score = max(score, 16.0)
        reason = "Retest giữ level và volume thấp hơn nến breakout."
    if baseline_contracts and event_contracts:
        score = 18.0
        reason = "Retest tốt: volume co so với baseline và breakout."
    if baseline_contracts and event_contracts and spread_contracts:
        score = 20.0
        reason = "Retest chất lượng cao: giữ level, volume và spread cùng co."

    return RetestAssessment(True, score, reason)
