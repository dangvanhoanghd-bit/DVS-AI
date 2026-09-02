from __future__ import annotations
from dvs_ai.domain.models import AlignmentAnalysis, TimeframeAnalysis

class MultiTimeframeEngine:
    WEIGHTS = {"15m": 30.0, "1h": 35.0, "4h": 25.0, "1d": 10.0}

    def analyze(self, tf: dict[str, TimeframeAnalysis]) -> AlignmentAnalysis:
        long_score = 0.0
        short_score = 0.0
        aligned_long = []
        aligned_short = []

        for name, weight in self.WEIGHTS.items():
            r = tf[name]
            long_bias = (
                r.ema20 > r.ema50
                and r.cmf >= 0
                and r.rsi >= 48
            )
            short_bias = (
                r.ema20 < r.ema50
                and r.cmf < 0
                and r.rsi <= 52
            )
            if long_bias:
                long_score += weight
                aligned_long.append(name)
            if short_bias:
                short_score += weight
                aligned_short.append(name)

        if long_score >= 70 and short_score <= 25:
            label = "ĐỒNG PHA LONG"
            aligned = aligned_long
            conflicting = aligned_short
        elif short_score >= 70 and long_score <= 25:
            label = "ĐỒNG PHA SHORT"
            aligned = aligned_short
            conflicting = aligned_long
        elif long_score >= 50 and short_score < 40:
            label = "NGHIÊNG LONG"
            aligned = aligned_long
            conflicting = aligned_short
        elif short_score >= 50 and long_score < 40:
            label = "NGHIÊNG SHORT"
            aligned = aligned_short
            conflicting = aligned_long
        else:
            label = "MÂU THUẪN"
            aligned = aligned_long if long_score >= short_score else aligned_short
            conflicting = aligned_short if long_score >= short_score else aligned_long

        description = (
            f"{label}; Long alignment {long_score:.0f}/100, "
            f"Short alignment {short_score:.0f}/100."
        )
        return AlignmentAnalysis(
            label=label,
            long_score=long_score,
            short_score=short_score,
            aligned_timeframes=tuple(aligned),
            conflicting_timeframes=tuple(conflicting),
            description=description,
        )
