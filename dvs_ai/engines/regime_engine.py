from __future__ import annotations
import math
from dvs_ai.domain.models import RegimeAnalysis, TimeframeAnalysis

class MarketRegimeEngine:
    def analyze(self, tf: dict[str, TimeframeAnalysis]) -> RegimeAnalysis:
        r15, r1, r4, rd = tf["15m"], tf["1h"], tf["4h"], tf["1d"]

        long_votes = sum([
            r15.ema20 > r15.ema50,
            r1.ema20 > r1.ema50,
            r4.ema20 > r4.ema50,
            rd.ema20 > rd.ema50,
        ])
        short_votes = 4 - long_votes

        adx = 0.15*r15.adx + 0.35*r1.adx + 0.35*r4.adx + 0.15*rd.adx
        cmf = 0.20*r15.cmf + 0.35*r1.cmf + 0.30*r4.cmf + 0.15*rd.cmf
        atr_pct = (r15.atr / max(r15.close, 1e-12)) * 100.0

        if atr_pct >= 2.5:
            volatility = "RẤT CAO"
        elif atr_pct >= 1.5:
            volatility = "CAO"
        elif atr_pct >= 0.7:
            volatility = "TRUNG BÌNH"
        else:
            volatility = "THẤP"

        if adx >= 25 and long_votes >= 3 and cmf > 0:
            regime, direction = "TREND", "LONG"
        elif adx >= 25 and short_votes >= 3 and cmf < 0:
            regime, direction = "TREND", "SHORT"
        elif adx < 18 and abs(cmf) < 0.08:
            regime, direction = "RANGE", "NEUTRAL"
        elif "Spring" in (r15.market_phase, r1.market_phase):
            regime, direction = "REVERSAL", "LONG"
        elif "Upthrust" in (r15.market_phase, r1.market_phase):
            regime, direction = "REVERSAL", "SHORT"
        elif cmf >= 0 and long_votes >= 2:
            regime, direction = "ACCUMULATION", "LONG"
        elif cmf < 0 and short_votes >= 2:
            regime, direction = "DISTRIBUTION", "SHORT"
        else:
            regime, direction = "TRANSITION", "NEUTRAL"

        adx_component = min(max(adx, 0.0), 60.0) / 60.0
        cmf_component = min(abs(cmf), 0.35) / 0.35
        alignment_component = abs(long_votes - short_votes) / 4.0
        raw_strength = (
            0.50 * adx_component
            + 0.30 * cmf_component
            + 0.20 * alignment_component
        )
        strength = 100.0 * (1.0 - math.exp(-1.65 * raw_strength))

        description = (
            f"{regime} nghiêng {direction}; ADX tổng hợp {adx:.1f}, "
            f"CMF tổng hợp {cmf:+.3f}, volatility {volatility}."
        )
        return RegimeAnalysis(
            regime=regime,
            direction=direction,
            strength=strength,
            volatility_state=volatility,
            description=description,
        )
