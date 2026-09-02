from __future__ import annotations

import math

from dvs_ai.domain.models import SmartEntryAnalysis
from dvs_ai.engines.retest_rules import assess_retest, unavailable_retest


def _f(value, default=0.0):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except Exception:
        return default


def _clamp(value):
    return max(0.0, min(100.0, float(value)))


def _correlated_cluster(*scores):
    """One vote for correlated observations, with limited confirmation."""
    ordered = sorted((_clamp(x) for x in scores), reverse=True)
    if not ordered:
        return 0.0
    strongest = ordered[0]
    second = ordered[1] if len(ordered) > 1 else 0.0
    return _clamp(0.72*strongest + 0.28*second)


def _harmonic_consensus(scores):
    values = [_clamp(x) for x in scores if _clamp(x) > 0.0]
    if not values:
        return 0.0
    return _clamp(len(values) / sum(1.0/value for value in values))


class SmartEntryEngine:

    @staticmethod
    def _retest_context(d15, r15):
        """
        Breakout must be completed at least two candles before the current retest.
        No synthetic/current-price level is used when data is insufficient.
        """
        if len(d15) < 35:
            unavailable = unavailable_retest(
                "Không đủ dữ liệu xác định breakout/retest."
            )
            return unavailable, unavailable

        current = d15.iloc[-1]
        history = d15.iloc[:-8]
        breakout_window = d15.iloc[-8:-2]
        if len(history) < 20 or len(breakout_window) < 2:
            unavailable = unavailable_retest(
                "Không đủ dữ liệu nền cho retest."
            )
            return unavailable, unavailable

        old_resistance = _f(history["high"].tail(30).max(), r15.resistance)
        old_support = _f(history["low"].tail(30).min(), r15.support)
        atr = max(_f(r15.atr), _f(r15.close) * 0.001)

        long_candidates = breakout_window[
            breakout_window["close"] >= old_resistance + max(
                0.15 * atr, abs(old_resistance) * 0.001
            )
        ]
        short_candidates = breakout_window[
            breakout_window["close"] <= old_support - max(
                0.15 * atr, abs(old_support) * 0.001
            )
        ]

        def build(direction, candidates, level):
            if len(candidates) == 0:
                return unavailable_retest("Không có breakout hoàn tất phù hợp.")
            # Most recent completed breakout event has priority.
            event = candidates.iloc[-1]
            return assess_retest(
                direction=direction,
                close=_f(current["close"]),
                high=_f(current["high"]),
                low=_f(current["low"]),
                level=level,
                atr=atr,
                relative_volume=max(0.0, min(_f(r15.relative_volume), 10.0)),
                breakout_close=_f(event["close"]),
                current_volume=max(0.0, _f(current["volume"])),
                event_volume=max(0.0, _f(event["volume"])),
                current_spread=max(
                    0.0, _f(current["high"]) - _f(current["low"])
                ),
                event_spread=max(
                    0.0, _f(event["high"]) - _f(event["low"])
                ),
            )

        return (
            build("LONG", long_candidates, old_resistance),
            build("SHORT", short_candidates, old_support),
        )

    def analyze(self, frames, tf, snap, structure, alignment, regime):
        d15 = frames["15m"]
        r15 = tf["15m"]
        cur = d15.iloc[-1]
        prev = d15.iloc[-2]

        close = _f(cur["close"])
        open_ = _f(cur["open"])
        high = _f(cur["high"])
        low = _f(cur["low"])
        volume = _f(cur["volume"])

        atr = max(r15.atr, close * 0.001)
        candle_range = max(high - low, 1e-12)
        body_ratio = abs(close - open_) / candle_range
        move_atr = abs(close - _f(prev["close"], close)) / atr

        avg_vol = _f(d15["volume"].iloc[-21:-1].mean(), 1.0)
        volume_valid = volume > 0 and avg_vol > 0
        vol_ratio = (
            min(10.0, max(0.0, volume / avg_vol))
            if volume_valid else 0.0
        )

        # Một nguồn sự thật duy nhất: chuỗi từ IndicatorEngine.
        cmf_values = r15.cmf_values
        rsi_values = r15.rsi_values
        cmf_now = _f(cmf_values[-1], r15.cmf) if cmf_values else r15.cmf
        cmf_prev = (
            _f(cmf_values[-4], cmf_now)
            if len(cmf_values) >= 4 else cmf_now
        )
        rsi_now = _f(rsi_values[-1], r15.rsi) if rsi_values else r15.rsi
        rsi_prev = (
            _f(rsi_values[-4], rsi_now)
            if len(rsi_values) >= 4 else rsi_now
        )
        price_prev = _f(d15["close"].iloc[-4], close)

        long_retest, short_retest = self._retest_context(d15, r15)
        long_retest_quality = min(70.0, long_retest.score * 3.5)
        short_retest_quality = min(70.0, short_retest.score * 3.5)

        panic = 0.0
        if close < open_:
            panic += min(24, move_atr * 12)
        if vol_ratio >= 1.2:
            panic += min(24, (vol_ratio - 1) * 22)
        if rsi_now <= 35:
            panic += 22
        if body_ratio >= 0.6:
            panic += 14
        if low < r15.support:
            panic += 16
        panic = min(100, panic)

        blowoff = 0.0
        if close > open_:
            blowoff += min(24, move_atr * 12)
        if vol_ratio >= 1.2:
            blowoff += min(24, (vol_ratio - 1) * 22)
        if rsi_now >= 65:
            blowoff += 22
        if body_ratio >= 0.6:
            blowoff += 14
        if high > r15.resistance:
            blowoff += 16
        blowoff = min(100, blowoff)

        # Directional pressure evidence. Absence of bullish evidence is
        # not bearish evidence; both sides are measured independently.
        weak_long = 0.0
        if rsi_now < rsi_prev - 8:
            weak_long += 24
        if cmf_now > 0:
            weak_long += 24
        if cmf_now >= cmf_prev - 0.03:
            weak_long += 16
        if close < price_prev:
            weak_long += 12
        if snap.oi_change_15m_pct <= 0.15:
            weak_long += 12
        if vol_ratio >= 1.1:
            weak_long += 12
        weak_long = _clamp(weak_long)

        weak_short = 0.0
        if rsi_now > rsi_prev + 8:
            weak_short += 24
        if cmf_now < 0:
            weak_short += 24
        if cmf_now <= cmf_prev + 0.03:
            weak_short += 16
        if close > price_prev:
            weak_short += 12
        if snap.oi_change_15m_pct <= 0.15:
            weak_short += 12
        if vol_ratio >= 1.1:
            weak_short += 12
        weak_short = _clamp(weak_short)

        avg_range = _f(
            (d15["high"] - d15["low"]).iloc[-21:-1].mean(),
            candle_range,
        )
        result_ratio = candle_range / max(avg_range, 1e-12)
        near_support = (close-r15.support)/atr <= 0.8
        near_resistance = (r15.resistance-close)/atr <= 0.8

        absorption_long = 0.0
        if volume_valid and vol_ratio >= 1.35 and result_ratio <= 1.0:
            absorption_long += 34
        if cmf_now > cmf_prev:
            absorption_long += 20
        if close > low+candle_range*0.45:
            absorption_long += 18
        if snap.oi_change_15m_pct <= 0.10:
            absorption_long += 12
        if "hấp thụ" in structure.wyckoff_signal.lower():
            absorption_long += 16
        if not near_support:
            absorption_long *= 0.45
        absorption_long = _clamp(absorption_long)

        absorption_short = 0.0
        if volume_valid and vol_ratio >= 1.35 and result_ratio <= 1.0:
            absorption_short += 34
        if cmf_now < cmf_prev:
            absorption_short += 20
        if close < high-candle_range*0.45:
            absorption_short += 18
        if snap.oi_change_15m_pct <= 0.10:
            absorption_short += 12
        if "hấp thụ" in structure.wyckoff_signal.lower():
            absorption_short += 16
        if not near_resistance:
            absorption_short *= 0.45
        absorption_short = _clamp(absorption_short)

        weak = max(weak_long, weak_short)
        absorption = max(absorption_long, absorption_short)

        # Spring/Upthrust gồm cả biến thể volume cao và volume thấp.
        fake_down = 0.0
        if r15.spring:
            fake_down += 58 if r15.spring_type == "SILENT" else 52
            if "quét đáy" in structure.liquidity_event.lower():
                fake_down += 18
            if cmf_now >= 0:
                fake_down += 14
            if r15.spring_type == "SILENT" and vol_ratio <= 0.85:
                fake_down += 10
            elif r15.spring_type == "AGGRESSIVE" and vol_ratio >= 1.15:
                fake_down += 8
        structure_test = str(
            getattr(structure, "wyckoff_test", "NONE")
        )
        if r15.wyckoff_test_long:
            fake_down += 8
        if structure_test == "TEST AFTER SPRING":
            fake_down += 8 if r15.wyckoff_test_long else 3
        fake_down = min(100, fake_down)

        fake_up = 0.0
        if r15.upthrust:
            fake_up += 58 if r15.upthrust_type == "SILENT" else 52
            if "quét đỉnh" in structure.liquidity_event.lower():
                fake_up += 18
            if cmf_now <= 0:
                fake_up += 14
            if r15.upthrust_type == "SILENT" and vol_ratio <= 0.85:
                fake_up += 10
            elif r15.upthrust_type == "AGGRESSIVE" and vol_ratio >= 1.15:
                fake_up += 8
        if r15.wyckoff_test_short:
            fake_up += 8
        if structure_test == "TEST AFTER UPTHRUST":
            fake_up += 8 if r15.wyckoff_test_short else 3
        fake_up = min(100, fake_up)

        if close < price_prev and cmf_now > cmf_prev and rsi_now <= rsi_prev:
            divergence = "BULLISH CMF DIVERGENCE"
        elif close > price_prev and cmf_now < cmf_prev and rsi_now >= rsi_prev:
            divergence = "BEARISH CMF DIVERGENCE"
        elif rsi_now < rsi_prev - 8 and cmf_now > 0:
            divergence = "RSI DROP / CMF HOLDS"
        elif rsi_now > rsi_prev + 8 and cmf_now < 0:
            divergence = "RSI PUMP / CMF WEAK"
        else:
            divergence = "NONE"


        # Balanced evidence weights. Retest is capped and cannot dominate.
        long_extension = max(0.0, close - r15.ema20) / atr
        short_extension = max(0.0, r15.ema20 - close) / atr
        long_extension_penalty = min(
            18.0, max(0.0, long_extension - 1.8) * 8.0
        )
        short_extension_penalty = min(
            18.0, max(0.0, short_extension - 1.8) * 8.0
        )

        strong_downtrend = (
            r15.ema20 < r15.ema50
            and r15.adx >= 28
            and close < r15.ema20
        )
        strong_uptrend = (
            r15.ema20 > r15.ema50
            and r15.adx >= 28
            and close > r15.ema20
        )
        if strong_downtrend and not near_support:
            fake_down *= 0.55
        if strong_uptrend and not near_resistance:
            fake_up *= 0.55

        spring_structure = (
            structure.wyckoff_score
            if "spring" in str(structure.wyckoff_signal).lower()
            else 0.0
        )
        upthrust_structure = (
            structure.wyckoff_score
            if "upthrust" in str(structure.wyckoff_signal).lower()
            else 0.0
        )

        # One vote per independent evidence group.
        long_pressure = _correlated_cluster(
            panic, weak_long, absorption_long
        )
        short_pressure = _correlated_cluster(
            blowoff, weak_short, absorption_short
        )
        long_structure = max(
            fake_down, long_retest_quality, spring_structure
        )
        short_structure = max(
            fake_up, short_retest_quality, upthrust_structure
        )
        long_context = _clamp(
            0.55*alignment.long_score
            + 0.45*(100 if regime.direction == "LONG" else 40)
        )
        short_context = _clamp(
            0.55*alignment.short_score
            + 0.45*(100 if regime.direction == "SHORT" else 40)
        )

        loi = (
            0.40*long_pressure
            + 0.40*long_structure
            + 0.20*long_context
            - long_extension_penalty
        )
        soi = (
            0.40*short_pressure
            + 0.40*short_structure
            + 0.20*short_context
            - short_extension_penalty
        )

        long_funding_penalty = min(
            14.0,
            max(0.0, abs(snap.funding_pct)-0.04)/0.11*14.0,
        ) if snap.funding_pct > 0 else 0.0
        short_funding_penalty = min(
            14.0,
            max(0.0, abs(snap.funding_pct)-0.04)/0.11*14.0,
        ) if snap.funding_pct < 0 else 0.0
        loi -= long_funding_penalty
        soi -= short_funding_penalty

        if snap.oi_change_15m_pct > 3.0 and long_extension > 1.2:
            loi -= 7.0
        if snap.oi_change_15m_pct > 3.0 and short_extension > 1.2:
            soi -= 7.0

        if divergence == "BULLISH CMF DIVERGENCE":
            loi += 6.0
        if divergence == "BEARISH CMF DIVERGENCE":
            soi += 6.0
        loi = _clamp(loi)
        soi = _clamp(soi)

        if loi >= soi:
            dominant_direction = "LONG"
            dominant_groups = (
                long_pressure, long_structure, long_context
            )
        else:
            dominant_direction = "SHORT"
            dominant_groups = (
                short_pressure, short_structure, short_context
            )

        independent_group_count = sum(
            value >= 55.0 for value in dominant_groups
        )
        consensus = _harmonic_consensus(dominant_groups)
        depth_multiplier = (
            1.0 if independent_group_count >= 3
            else 0.88 if independent_group_count == 2
            else 0.70
        )
        smp = _clamp(consensus*depth_multiplier)
        audit_flags = (
            "GROUPED_CORRELATED_PRESSURE",
            "GROUPED_CORRELATED_STRUCTURE",
            "NO_INVERSE_EVIDENCE",
            "SMP_INDEPENDENT_GROUP_CONSENSUS",
        )

        edge_gap = 5.0
        long_ready = loi >= 78 and (
            fake_down >= 55 or long_retest.confirmed
        )
        short_ready = soi >= 78 and (
            fake_up >= 55 or short_retest.confirmed
        )

        if long_ready and loi >= soi + edge_gap:
            state = "SMART LONG READY"
        elif short_ready and soi >= loi + edge_gap:
            state = "SMART SHORT READY"
        elif long_ready and short_ready:
            if loi > soi:
                state = "SMART LONG READY"
            elif soi > loi:
                state = "SMART SHORT READY"
            else:
                state = "SPECIAL WATCH"
        elif loi >= 60 and loi >= soi + edge_gap:
            state = "SHAKEOUT LONG WATCH"
        elif soi >= 60 and soi >= loi + edge_gap:
            state = "UPTHRUST SHORT WATCH"
        elif max(loi, soi) >= 45:
            state = "SPECIAL WATCH"
        else:
            state = "NO EDGE"

        explanation = (
            f"Panic flush {panic:.0f}/100",
            f"Weak-hand L/S {weak_long:.0f}/{weak_short:.0f}",
            f"Absorption L/S {absorption_long:.0f}/{absorption_short:.0f}",
            f"Pressure groups L/S {long_pressure:.0f}/{short_pressure:.0f}",
            (
                f"Spring {r15.spring_type}; Indicator Test Long="
                f"{r15.wyckoff_test_long}"
            ),
            (
                f"Structure Test="
                f"{getattr(structure, 'wyckoff_test', 'NONE')} "
                f"({getattr(structure, 'wyckoff_test_score', 0.0):.0f}/100)"
            ),
            (
                f"Sweep Volume="
                f"{getattr(structure, 'sweep_volume_state', 'NONE')}; "
                "diagnostic only, not scored twice"
            ),
            f"Confirmed fake breakdown {fake_down:.0f}/100",
            (
                f"Upthrust {r15.upthrust_type}; Indicator Test Short="
                f"{r15.wyckoff_test_short}"
            ),
            f"Confirmed fake breakout {fake_up:.0f}/100",
            f"Long Retest {long_retest.score:.0f}/20: {long_retest.reason}",
            f"Short Retest {short_retest.score:.0f}/20: {short_retest.reason}",
            f"CMF/RSI: {divergence}",
            f"Structure groups L/S {long_structure:.0f}/{short_structure:.0f}",
            f"Context groups L/S {long_context:.0f}/{short_context:.0f}",
            f"LOI {loi:.0f}/100 | SOI {soi:.0f}/100",
            (
                f"Smart Money Probability {smp:.0f}/100 · "
                f"{dominant_direction} · "
                f"{independent_group_count}/3 independent groups"
            ),
        )
        return SmartEntryAnalysis(
            panic,
            weak,
            absorption,
            fake_down,
            fake_up,
            divergence,
            loi,
            soi,
            smp,
            state,
            explanation,
            long_pressure,
            short_pressure,
            long_structure,
            short_structure,
            long_context,
            short_context,
            dominant_direction,
            independent_group_count,
            audit_flags,
        )
