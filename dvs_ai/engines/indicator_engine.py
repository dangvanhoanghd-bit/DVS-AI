from __future__ import annotations
import math
import pandas as pd
import pandas_ta as ta
from dvs_ai.domain.models import TimeframeAnalysis


def _f(value: object, default: float = 0.0) -> float:
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


class IndicatorEngine:
    @staticmethod
    def _spring_variants(df, support, resistance, rel_volume, cmf_series):
        cur = df.iloc[-1]
        close = _f(cur.close)
        high = _f(cur.high)
        low = _f(cur.low)
        candle_range = max(high - low, 1e-12)
        lower_wick = max(0.0, min(_f(cur.open), close) - low) / candle_range
        upper_wick = max(0.0, high - max(_f(cur.open), close)) / candle_range
        prev_cmf = _f(cmf_series.iloc[-3]) if len(cmf_series) >= 3 else _f(cmf_series.iloc[-1])
        cmf_now = _f(cmf_series.iloc[-1])

        swept_low = low < support and close > support
        swept_high = high > resistance and close < resistance

        spring_type = "NONE"
        if swept_low and rel_volume >= 1.15 and lower_wick >= 0.25:
            spring_type = "AGGRESSIVE"
        elif (
            swept_low
            and rel_volume <= 0.85
            and lower_wick >= 0.35
            and cmf_now >= prev_cmf - 0.04
        ):
            spring_type = "SILENT"

        upthrust_type = "NONE"
        if swept_high and rel_volume >= 1.15 and upper_wick >= 0.25:
            upthrust_type = "AGGRESSIVE"
        elif (
            swept_high
            and rel_volume <= 0.85
            and upper_wick >= 0.35
            and cmf_now <= prev_cmf + 0.04
        ):
            upthrust_type = "SILENT"

        return spring_type, upthrust_type

    @staticmethod
    def _wyckoff_test(df):
        """
        Test sau Spring/Upthrust:
        - tìm cú quét trong 12 nến trước;
        - nến hiện tại quay lại vùng quét nhưng không phá đáy/đỉnh;
        - volume và spread co lại so với nến Spring/Upthrust.
        """
        if len(df) < 35:
            return False, False, 0.0

        cur = df.iloc[-1]
        avg_vol = _f(df.volume.iloc[-22:-2].mean(), 1.0)
        avg_range = _f((df.high - df.low).iloc[-22:-2].mean(), 1.0)
        cur_range = max(_f(cur.high) - _f(cur.low), 1e-12)
        cur_vol_ratio = _f(cur.volume) / max(avg_vol, 1e-12)

        long_test = False
        short_test = False
        score = 0.0

        for idx in range(len(df) - 3, max(20, len(df) - 14), -1):
            history = df.iloc[max(0, idx - 20):idx]
            if len(history) < 15:
                continue
            support = _f(history.low.min())
            resistance = _f(history.high.max())
            event = df.iloc[idx]
            event_range = max(_f(event.high) - _f(event.low), 1e-12)
            event_vol = _f(event.volume)

            spring_event = _f(event.low) < support and _f(event.close) > support
            if spring_event:
                near_zone = _f(cur.low) <= support + 0.35 * event_range
                holds = _f(cur.low) > _f(event.low) and _f(cur.close) > support
                volume_contracts = _f(cur.volume) < event_vol and cur_vol_ratio <= 0.90
                spread_contracts = cur_range <= min(avg_range, event_range) * 0.95
                if near_zone and holds and volume_contracts and spread_contracts:
                    long_test = True
                    score = max(score, 78.0)
                    break

            upthrust_event = _f(event.high) > resistance and _f(event.close) < resistance
            if upthrust_event:
                near_zone = _f(cur.high) >= resistance - 0.35 * event_range
                holds = _f(cur.high) < _f(event.high) and _f(cur.close) < resistance
                volume_contracts = _f(cur.volume) < event_vol and cur_vol_ratio <= 0.90
                spread_contracts = cur_range <= min(avg_range, event_range) * 0.95
                if near_zone and holds and volume_contracts and spread_contracts:
                    short_test = True
                    score = max(score, 78.0)
                    break

        return long_test, short_test, score


    @staticmethod
    def _trend_maturity(
        df,
        ema20_series,
        ema50_series,
        close,
        ema20,
        ema50,
        atr,
        adx,
        cmf,
        direction,
        test_confirmed,
    ):
        """
        Directional trend maturity, not trend strength.

        A high value means the move is old/extended, not necessarily attractive.
        It combines directional extension, ADX persistence, age since the latest
        EMA20 reclaim/loss and repeated EMA20 retests.
        """
        side = str(direction).upper()
        if side not in ("LONG", "SHORT"):
            raise ValueError(
                f"Unsupported maturity direction: {direction}"
            )
        confirmed_test = bool(test_confirmed)
        atr_safe = max(atr, close * 0.002, 1e-12)

        if side == "LONG":
            directional = ema20 > ema50 and close >= ema20
            extension20 = max(0.0, close - ema20) / atr_safe
            extension50 = max(0.0, close - ema50) / atr_safe
        else:
            directional = ema20 < ema50 and close <= ema20
            extension20 = max(0.0, ema20 - close) / atr_safe
            extension50 = max(0.0, ema50 - close) / atr_safe

        recent_close = df.close.tail(60).reset_index(drop=True)
        recent_ema20 = ema20_series.tail(60).reset_index(drop=True)
        signed = recent_close - recent_ema20
        if side == "SHORT":
            signed = -signed

        cross_age = 999
        for idx in range(len(signed)-1, 0, -1):
            if _f(signed.iloc[idx]) >= 0 and _f(signed.iloc[idx-1]) < 0:
                cross_age = len(signed)-1-idx
                break

        touches = 0
        start = max(0, len(recent_close)-24)
        for idx in range(start, len(recent_close)):
            distance = abs(
                _f(recent_close.iloc[idx]) - _f(recent_ema20.iloc[idx])
            ) / atr_safe
            if distance <= 0.35:
                touches += 1

        if not directional:
            score = min(
                22.0,
                0.55 * min(40.0, adx)
                + 4.0 * max(extension20-0.5, 0.0),
            )
            lifecycle = "UNFORMED"
        else:
            extension_component = min(
                100.0,
                max(0.0, (extension20-0.35)*23.0)
                + max(0.0, (extension50-1.2)*7.0),
            )
            adx_component = min(
                100.0,
                max(0.0, adx-15.0)*3.0,
            )
            age_component = (
                18.0 if cross_age <= 2
                else 35.0 if cross_age <= 6
                else 55.0 if cross_age <= 14
                else 75.0 if cross_age <= 28
                else 92.0
            )
            retest_component = min(100.0, touches*16.0)
            crowding_component = min(
                100.0,
                max(0.0, (cmf if side == "LONG" else -cmf)-0.08)*260.0,
            )

            score = (
                0.40*extension_component
                + 0.25*adx_component
                + 0.22*age_component
                + 0.08*retest_component
                + 0.05*crowding_component
            )
            if confirmed_test and cross_age <= 10:
                score = min(score, 58.0)

            if extension20 > 4.5 or extension50 > 6.5:
                score = max(score, 86.0)

            if score < 22:
                lifecycle = "UNFORMED"
            elif score < 48:
                lifecycle = "EARLY_FORMATION"
            elif score < 68:
                lifecycle = (
                    "FIRST_RETEST"
                    if confirmed_test or touches <= 2
                    else "CONFIRMED_TREND"
                )
            elif score < 82:
                lifecycle = "LATE_TREND"
            else:
                lifecycle = "EXHAUSTION"

        return (
            max(0.0, min(100.0, score)),
            lifecycle,
            int(cross_age),
            int(touches),
        )


    def analyze(self, df: pd.DataFrame, timeframe: str) -> TimeframeAnalysis:
        cmf_s = ta.cmf(df.high, df.low, df.close, df.volume, length=20)
        rsi_s = ta.rsi(df.close, length=14)
        ema20_s = ta.ema(df.close, length=20)
        ema50_s = ta.ema(df.close, length=50)
        ema200_length = 200 if len(df) >= 200 else max(60, min(len(df)-5, 100))
        ema200_s = ta.ema(df.close, length=ema200_length)
        adx_df = ta.adx(df.high, df.low, df.close, length=14)
        atr_s = ta.atr(df.high, df.low, df.close, length=14)

        cmf = _f(cmf_s.iloc[-1])
        rsi = _f(rsi_s.iloc[-1])
        ema20 = _f(ema20_s.iloc[-1])
        ema50 = _f(ema50_s.iloc[-1])
        ema200 = _f(ema200_s.iloc[-1])
        adx = _f(adx_df["ADX_14"].iloc[-1])
        atr = _f(atr_s.iloc[-1])

        current = df.iloc[-1]
        close = _f(current.close)
        previous = _f(df.close.iloc[-2], close)
        price_change = (close - previous) / max(previous, 1e-12) * 100.0
        vol_mean = _f(df.volume.shift(1).rolling(20).mean().iloc[-1])
        rel_volume = _f(current.volume) / vol_mean if vol_mean > 0 else 0.0

        lookback = min(20, len(df)-2)
        support = _f(df.low.iloc[-lookback-1:-1].min())
        resistance = _f(df.high.iloc[-lookback-1:-1].max())

        spring_type, upthrust_type = self._spring_variants(
            df, support, resistance, rel_volume, cmf_s
        )
        spring = spring_type != "NONE"
        upthrust = upthrust_type != "NONE"
        test_long, test_short, test_score = self._wyckoff_test(df)

        high20, low20 = _f(df.high.tail(20).max()), _f(df.low.tail(20).min())
        range_pct = (high20-low20)/max(close,1e-12)*100.0
        phase = self._phase(
            cmf, rsi, ema20, ema50, ema200, adx,
            spring, upthrust, test_long, test_short, range_pct
        )

        lt, st = self._trend_scores(cmf,rsi,ema20,ema50,ema200,adx,rel_volume)

        (
            long_maturity,
            long_lifecycle,
            bars_since_long_cross,
            long_retest_count,
        ) = self._trend_maturity(
            df, ema20_s, ema50_s, close, ema20, ema50,
            atr, adx, cmf, "LONG", test_long,
        )
        (
            short_maturity,
            short_lifecycle,
            bars_since_short_cross,
            short_retest_count,
        ) = self._trend_maturity(
            df, ema20_s, ema50_s, close, ema20, ema50,
            atr, adx, cmf, "SHORT", test_short,
        )

        le, se = self._entry_scores(
            df, cmf, rsi, ema20, ema50, atr, rel_volume,
            spring_type, upthrust_type, test_long, test_short,
            support, resistance, cmf_s, rsi_s
        )

        return TimeframeAnalysis(
            timeframe=timeframe, close=close, price_change_pct=price_change,
            cmf=cmf, rsi=rsi, ema20=ema20, ema50=ema50, ema200=ema200,
            adx=adx, atr=atr, relative_volume=rel_volume,
            support=support, resistance=resistance, spring=spring,
            upthrust=upthrust, market_phase=phase,
            long_trend_score=lt, short_trend_score=st,
            long_entry_score=le, short_entry_score=se,
            opens=tuple(_f(x) for x in df.open.tail(80)),
            highs=tuple(_f(x) for x in df.high.tail(80)),
            lows=tuple(_f(x) for x in df.low.tail(80)),
            closes=tuple(_f(x) for x in df.close.tail(80)),
            cmf_values=tuple(_f(x) for x in cmf_s.tail(80)),
            rsi_values=tuple(_f(x) for x in rsi_s.tail(80)),
            spring_type=spring_type,
            upthrust_type=upthrust_type,
            wyckoff_test_long=test_long,
            wyckoff_test_short=test_short,
            wyckoff_test_score=test_score,
            long_trend_maturity=long_maturity,
            short_trend_maturity=short_maturity,
            long_trend_lifecycle=long_lifecycle,
            short_trend_lifecycle=short_lifecycle,
            bars_since_long_cross=bars_since_long_cross,
            bars_since_short_cross=bars_since_short_cross,
            long_retest_count=long_retest_count,
            short_retest_count=short_retest_count,
        )

    @staticmethod
    def _phase(cmf,rsi,e20,e50,e200,adx,spring,upthrust,test_long,test_short,range_pct):
        if test_long: return "Wyckoff Test Long"
        if test_short: return "Wyckoff Test Short"
        if spring: return "Spring"
        if upthrust: return "Upthrust"
        if e20 > e50 > e200 and cmf > .05 and adx >= 20: return "Markup"
        if e20 < e50 < e200 and cmf < -.05 and adx >= 20: return "Markdown"
        if range_pct < 8 and cmf >= 0: return "Accumulation"
        if range_pct < 8 and cmf < 0: return "Distribution"
        if rsi >= 72: return "Overheat"
        if rsi <= 28: return "Capitulation?"
        if e20 > e50 and cmf > 0: return "Early Markup"
        if e20 < e50 and cmf < 0: return "Early Markdown"
        return "Transition"

    @staticmethod
    def _trend_scores(cmf,rsi,e20,e50,e200,adx,rv):
        long = max(0,min(32,(cmf+.04)*105))
        short = max(0,min(32,(-cmf+.04)*105))
        if 48 <= rsi <= 65: long += 20
        elif 40 <= rsi < 48: long += 10
        if 35 <= rsi <= 52: short += 20
        elif 52 < rsi <= 60: short += 9
        long += 14 if e20 > e50 else 0
        short += 14 if e20 < e50 else 0
        long += 8 if e50 > e200 else 0
        short += 8 if e50 < e200 else 0
        trend = min(12,max(0,(adx-15)*.75))
        long += trend if e20 > e50 else 0
        short += trend if e20 < e50 else 0
        if rv >= 1.2:
            long += 7 if cmf >= 0 else 0
            short += 7 if cmf < 0 else 0
        return min(100,long), min(100,short)

    @staticmethod
    def _entry_scores(
        df, cmf, rsi, e20, e50, atr, rv,
        spring_type, upthrust_type, test_long, test_short,
        support, resistance, cmf_series, rsi_series
    ):
        close = _f(df.close.iloc[-1])
        prev_index = -3 if len(df) >= 25 else -2
        prev_cmf = _f(cmf_series.iloc[prev_index])
        prev_rsi = _f(rsi_series.iloc[prev_index])
        long, short = 0.0, 0.0
        if cmf > prev_cmf: long += 24
        if cmf < prev_cmf: short += 24
        if rsi > prev_rsi and 38 <= rsi <= 64: long += 20
        if rsi < prev_rsi and 36 <= rsi <= 62: short += 20
        dist_support = (close-support)/max(atr,1e-12)
        dist_res = (resistance-close)/max(atr,1e-12)
        if 0 <= dist_support <= 1.2: long += 18
        if 0 <= dist_res <= 1.2: short += 18

        if spring_type == "AGGRESSIVE": long += 22
        elif spring_type == "SILENT": long += 27
        if upthrust_type == "AGGRESSIVE": short += 22
        elif upthrust_type == "SILENT": short += 27
        if test_long: long += 18
        if test_short: short += 18

        if e20 > e50: long += 8
        if e20 < e50: short += 8
        if rv >= 1.15:
            long += 5 if cmf >= 0 else 0
            short += 5 if cmf < 0 else 0

        long_extension = max(0.0, close - e20) / max(atr, 1e-12)
        short_extension = max(0.0, e20 - close) / max(atr, 1e-12)
        if long_extension > 2.2: long -= 22
        if short_extension > 2.2: short -= 22
        return max(0,min(100,long)), max(0,min(100,short))
