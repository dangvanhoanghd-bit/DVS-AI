from __future__ import annotations
import math
import pandas as pd
from dvs_ai.domain.models import StructureAnalysis

def _f(value, default=0.0):
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except Exception:
        return default

class StructureEngine:
    """
    Phân tích thanh khoản đa mốc và Effort-vs-Result kiểu Wyckoff.
    Đây là heuristic minh bạch, không khẳng định chắc chắn hành vi tổ chức.
    """

    def analyze(self, frames: dict[str, pd.DataFrame]) -> StructureAnalysis:
        d15 = frames["15m"]
        d1 = frames["1d"]

        # Mốc ngày: dùng nến ngày đã hoàn thành gần nhất.
        prev_day = d1.iloc[-2] if len(d1) >= 2 else d1.iloc[-1]
        daily_high = _f(prev_day["high"])
        daily_low = _f(prev_day["low"])

        # Tuần/tháng: loại nến cuối đang hình thành để giảm look-ahead.
        daily = d1.copy()
        daily["dt"] = pd.to_datetime(daily["timestamp"], unit="ms", utc=True)
        completed = daily.iloc[:-1].copy() if len(daily) > 2 else daily.copy()
        completed = completed.set_index("dt")

        weekly = completed.resample("W-SUN").agg(
            {"high": "max", "low": "min"}
        ).dropna()
        monthly = completed.resample("ME").agg(
            {"high": "max", "low": "min"}
        ).dropna()

        # Loại bucket tuần/tháng hiện tại nếu kỳ chưa hoàn tất.
        last_day = completed.index.max()

        if len(weekly):
            last_week_end = weekly.index[-1]
            if last_day.normalize() < last_week_end.normalize():
                weekly = weekly.iloc[:-1]

        if len(monthly):
            last_month_end = monthly.index[-1]
            if last_day.normalize() < last_month_end.normalize():
                monthly = monthly.iloc[:-1]

        weekly_high = _f(weekly.iloc[-1]["high"]) if len(weekly) else daily_high
        weekly_low = _f(weekly.iloc[-1]["low"]) if len(weekly) else daily_low
        monthly_high = _f(monthly.iloc[-1]["high"]) if len(monthly) else weekly_high
        monthly_low = _f(monthly.iloc[-1]["low"]) if len(monthly) else weekly_low

        cur = d15.iloc[-1]
        close = _f(cur["close"])
        high = _f(cur["high"])
        low = _f(cur["low"])
        open_ = _f(cur["open"])
        volume = _f(cur["volume"])

        avg_vol = _f(d15["volume"].iloc[-21:-1].mean(), 1.0)
        avg_range = _f((d15["high"]-d15["low"]).iloc[-21:-1].mean(), 1.0)
        candle_range = max(high-low, 1e-12)
        body = abs(close-open_)
        volume_valid = volume > 0 and avg_vol > 0
        vol_ratio = (
            min(10.0, max(0.0, volume / avg_vol))
            if volume_valid else 0.0
        )
        range_ratio = candle_range/max(avg_range, 1e-12)
        body_efficiency = body/candle_range

        levels = [
            ("đỉnh ngày", daily_high, "HIGH"),
            ("đáy ngày", daily_low, "LOW"),
            ("đỉnh tuần", weekly_high, "HIGH"),
            ("đáy tuần", weekly_low, "LOW"),
            ("đỉnh tháng", monthly_high, "HIGH"),
            ("đáy tháng", monthly_low, "LOW"),
        ]

        liquidity_event = "Không có sự kiện thanh khoản nổi bật"
        liquidity_score = 0.0
        sweep_volume_state = "NONE"
        warnings = []


        # Sweep needs price rejection geometry plus volume context.
        for name, level, side in reversed(levels):
            base = 78 if "tháng" in name else 70 if "tuần" in name else 62

            if side == "LOW" and low < level and close > level:
                lower_wick = (
                    max(0.0, min(open_, close) - low) / candle_range
                )
                if (
                    volume_valid
                    and vol_ratio >= 1.25
                    and lower_wick >= 0.40
                ):
                    sweep_volume_state = "HIGH_VOLUME_ABSORPTION"
                    liquidity_event = (
                        f"Quét {name} volume cao, wick mạnh, "
                        "đóng lại phía trên"
                    )
                    liquidity_score = min(100.0, base + 8)
                elif (
                    volume_valid
                    and vol_ratio <= 0.75
                    and lower_wick >= 0.50
                ):
                    sweep_volume_state = "LOW_VOLUME_EXHAUSTION"
                    liquidity_event = (
                        f"Quét {name} volume thấp, wick mạnh, "
                        "đóng lại phía trên"
                    )
                    liquidity_score = min(100.0, base + 12)
                else:
                    sweep_volume_state = "UNCONFIRMED"
                    liquidity_event = (
                        f"Quét {name} nhưng wick/volume chưa đủ xác nhận"
                    )
                    liquidity_score = max(20.0, base - 28)
                    warnings.append(
                        "Sweep cần wick và volume xác nhận mạnh hơn."
                    )
                break

            if side == "HIGH" and high > level and close < level:
                upper_wick = (
                    max(0.0, high - max(open_, close)) / candle_range
                )
                if (
                    volume_valid
                    and vol_ratio >= 1.25
                    and upper_wick >= 0.40
                ):
                    sweep_volume_state = "HIGH_VOLUME_ABSORPTION"
                    liquidity_event = (
                        f"Quét {name} volume cao, wick mạnh, "
                        "đóng lại phía dưới"
                    )
                    liquidity_score = min(100.0, base + 8)
                elif (
                    volume_valid
                    and vol_ratio <= 0.75
                    and upper_wick >= 0.50
                ):
                    sweep_volume_state = "LOW_VOLUME_EXHAUSTION"
                    liquidity_event = (
                        f"Quét {name} volume thấp, wick mạnh, "
                        "đóng lại phía dưới"
                    )
                    liquidity_score = min(100.0, base + 12)
                else:
                    sweep_volume_state = "UNCONFIRMED"
                    liquidity_event = (
                        f"Quét {name} nhưng wick/volume chưa đủ xác nhận"
                    )
                    liquidity_score = max(20.0, base - 28)
                    warnings.append(
                        "Sweep cần wick và volume xác nhận mạnh hơn."
                    )
                break

            if (
                side == "HIGH"
                and close > level
                and body_efficiency > 0.55
                and vol_ratio > 1.10
            ):
                liquidity_event = f"Breakout xác nhận trên {name}"
                liquidity_score = (
                    68 if "tháng" in name
                    else 62 if "tuần" in name
                    else 56
                )
                break

            if (
                side == "LOW"
                and close < level
                and body_efficiency > 0.55
                and vol_ratio > 1.10
            ):
                liquidity_event = f"Breakdown xác nhận dưới {name}"
                liquidity_score = (
                    68 if "tháng" in name
                    else 62 if "tuần" in name
                    else 56
                )
                break


        # Effort vs Result with explicit climax/easy-move states.
        if vol_ratio >= 1.80 and range_ratio <= 0.65:
            effort_result = "Climax: Effort cực cao, Result rất thấp"
            if close >= open_:
                wyckoff_signal = "Buying Climax/Phân phối hoặc hấp thụ tại vùng cao"
            else:
                wyckoff_signal = "Selling Climax/Hấp thụ lực bán tại vùng thấp"
            wyckoff_score = 82
            warnings.append(
                "Climax tiềm năng: cần xác nhận vị trí và nến kế tiếp."
            )
        elif vol_ratio >= 1.35 and range_ratio <= 0.85:
            effort_result = "Effort cao, Result thấp"
            if close >= open_:
                wyckoff_signal = "Có khả năng phân phối/absorbing tại vùng cao"
            else:
                wyckoff_signal = "Có khả năng hấp thụ lực bán"
            wyckoff_score = 74
            warnings.append(
                "Volume lớn nhưng biên độ nhỏ: chờ xác nhận."
            )
        elif vol_ratio >= 1.25 and range_ratio >= 1.25:
            effort_result = "Effort và Result đồng thuận"
            wyckoff_signal = "Xu hướng hiện tại có lực xác nhận"
            wyckoff_score = 66
        elif vol_ratio <= 0.75 and range_ratio >= 1.20:
            effort_result = "Easy Move: Result lớn với Effort thấp"
            wyckoff_signal = "Di chuyển dễ dàng; có thể thiếu độ bền"
            wyckoff_score = 50
            warnings.append(
                "Giá đi xa với volume thấp: tránh đuổi lệnh."
            )
        else:
            effort_result = "Effort/Result bình thường"
            wyckoff_signal = "Chưa có tín hiệu Wyckoff nổi bật"
            wyckoff_score = 35

        lower_event = liquidity_event.lower()
        if "quét đáy" in lower_event and sweep_volume_state != "UNCONFIRMED":
            variant = (
                "Silent Spring"
                if sweep_volume_state == "LOW_VOLUME_EXHAUSTION"
                else "Aggressive Spring"
            )
            wyckoff_signal = f"{variant}/Liquidity Sweep xác nhận"
            wyckoff_score = max(wyckoff_score, 76)
        elif "quét đỉnh" in lower_event and sweep_volume_state != "UNCONFIRMED":
            variant = (
                "Silent Upthrust"
                if sweep_volume_state == "LOW_VOLUME_EXHAUSTION"
                else "Aggressive Upthrust"
            )
            wyckoff_signal = f"{variant}/Liquidity Sweep xác nhận"
            wyckoff_score = max(wyckoff_score, 76)


        wyckoff_test = "NONE"
        wyckoff_test_score = 0.0

        # Evaluate several recent candidate events. Rolling support and
        # resistance are precomputed once, avoiding repeated DataFrame slices.
        if len(d15) >= 40:
            current_range = candle_range
            candidates = []
            rolling_support = (
                d15["low"].shift(1).rolling(20, min_periods=15).min()
            )
            rolling_resistance = (
                d15["high"].shift(1).rolling(20, min_periods=15).max()
            )

            for event_age in range(3, min(28, len(d15)-22)):
                event_index = len(d15) - 1 - event_age
                support = _f(
                    rolling_support.iloc[event_index],
                    low,
                )
                resistance = _f(
                    rolling_resistance.iloc[event_index],
                    high,
                )
                if support <= 0 or resistance <= 0:
                    continue

                event = d15.iloc[event_index]
                event_low = _f(event["low"])
                event_high = _f(event["high"])
                event_close = _f(event["close"])
                event_volume = _f(event["volume"])
                event_range = max(
                    event_high - event_low,
                    1e-12,
                )

                spring_event = (
                    event_low < support
                    and event_close > support
                )
                upthrust_event = (
                    event_high > resistance
                    and event_close < resistance
                )

                if spring_event:
                    distance = abs(low-support) / max(avg_range, 1e-12)
                    valid = (
                        low > event_low
                        and close > support
                        and volume < event_volume * 0.90
                        and vol_ratio <= 0.90
                        and current_range <= event_range * 0.90
                        and distance <= 1.20
                    )
                    if valid:
                        quality = (
                            70.0
                            + min(10.0, (1.0-vol_ratio)*20.0)
                            + min(5.0, max(0.0, 1.2-distance)*4.0)
                            + max(0.0, 5.0-event_age*0.15)
                        )
                        candidates.append(
                            (quality, -event_age, "TEST AFTER SPRING")
                        )

                if upthrust_event:
                    distance = abs(high-resistance) / max(avg_range, 1e-12)
                    valid = (
                        high < event_high
                        and close < resistance
                        and volume < event_volume * 0.90
                        and vol_ratio <= 0.90
                        and current_range <= event_range * 0.90
                        and distance <= 1.20
                    )
                    if valid:
                        quality = (
                            70.0
                            + min(10.0, (1.0-vol_ratio)*20.0)
                            + min(5.0, max(0.0, 1.2-distance)*4.0)
                            + max(0.0, 5.0-event_age*0.15)
                        )
                        candidates.append(
                            (quality, -event_age, "TEST AFTER UPTHRUST")
                        )

            if candidates:
                quality, _, wyckoff_test = max(candidates)
                wyckoff_test_score = min(85.0, quality)
                if wyckoff_test == "TEST AFTER SPRING":
                    wyckoff_signal = (
                        "Wyckoff Test sau Spring: "
                        "volume/spread co lại"
                    )
                else:
                    wyckoff_signal = (
                        "Wyckoff Test sau Upthrust: "
                        "volume/spread co lại"
                    )
                wyckoff_score = max(
                    wyckoff_score,
                    wyckoff_test_score,
                )

        return StructureAnalysis(
            daily_high=daily_high, daily_low=daily_low,
            weekly_high=weekly_high, weekly_low=weekly_low,
            monthly_high=monthly_high, monthly_low=monthly_low,
            liquidity_event=liquidity_event,
            wyckoff_signal=wyckoff_signal,
            effort_result=effort_result,
            liquidity_score=min(100.0, liquidity_score),
            wyckoff_score=min(100.0, wyckoff_score),
            warnings=tuple(warnings),
            sweep_volume_state=sweep_volume_state,
            wyckoff_test=wyckoff_test,
            wyckoff_test_score=wyckoff_test_score,
        )
