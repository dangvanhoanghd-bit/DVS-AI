from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from statistics import median
from typing import Any

from dvs_ai.domain.models import MicrostructureSnapshot


class MicrostructureEngine:
    """
    Conservative L2/aggregate-trade microstructure analysis.

    It does not claim identity-level Level 3 knowledge. Spoofing is only a
    probability placeholder until multiple WebSocket book updates are stored.
    """

    @staticmethod
    def _f(value: Any, default: float = 0.0) -> float:
        try:
            result = float(value)
            return result if isfinite(result) else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(100.0, float(value)))

    @classmethod
    def analyze(
        cls,
        symbol: str,
        raw: dict[str, Any],
        last_price: float,
        oi_change_15m_pct: float = 0.0,
        funding_pct: float = 0.0,
        price_change_pct: float = 0.0,
        previous_wall_state: dict[str, Any] | None = None,
        observed_at: float | None = None,
    ) -> MicrostructureSnapshot:
        """
        `previous_wall_state`: trạng thái tường từ lần quét TRƯỚC (do
        MicrostructureService lưu lại, xem _wall_tracking), dạng
        {"bid": (wall_price, wall_notional, consecutive_streak), "ask": (...)}.
        Truyền None nếu đây là lần quét đầu tiên cho symbol này (persistence
        sẽ bắt đầu từ 0 — đúng bản chất "chưa từng xác nhận").
        """
        now_ts = (
            float(observed_at)
            if observed_at is not None
            else datetime.now(timezone.utc).timestamp()
        )

        depth = raw.get("depth") or {}
        bids = depth.get("bids") or []
        asks = depth.get("asks") or []
        trades = raw.get("agg_trades") or []
        liquidations = raw.get("liquidations") or []

        bid_levels = [
            (cls._f(row[0]), cls._f(row[1]))
            for row in bids
            if isinstance(row, (list, tuple)) and len(row) >= 2
        ]
        ask_levels = [
            (cls._f(row[0]), cls._f(row[1]))
            for row in asks
            if isinstance(row, (list, tuple)) and len(row) >= 2
        ]
        bid_notionals = [p*q for p, q in bid_levels if p > 0 and q > 0]
        ask_notionals = [p*q for p, q in ask_levels if p > 0 and q > 0]
        bid_depth = sum(bid_notionals)
        ask_depth = sum(ask_notionals)
        depth_total = bid_depth + ask_depth
        book_imbalance = (
            (bid_depth-ask_depth)/depth_total
            if depth_total > 0 else 0.0
        )

        aggressive_buy = 0.0
        aggressive_sell = 0.0
        trade_prices: list[float] = []
        for trade in trades:
            price = cls._f(trade.get("p"))
            qty = cls._f(trade.get("q"))
            notional = max(0.0, price*qty)
            trade_prices.append(price)
            # Binance m=true means buyer is maker: aggressive seller.
            if bool(trade.get("m")):
                aggressive_sell += notional
            else:
                aggressive_buy += notional

        flow_total = aggressive_buy + aggressive_sell
        delta = aggressive_buy-aggressive_sell
        delta_ratio = delta/flow_total if flow_total > 0 else 0.0
        ofi_score = cls._clamp(50.0 + 50.0*delta_ratio)

        if len(trade_prices) >= 2 and trade_prices[0] > 0:
            micro_return_pct = (
                (trade_prices[-1]-trade_prices[0])
                / trade_prices[0]*100.0
            )
        else:
            micro_return_pct = 0.0

        # Large aggressive flow with limited price result = absorption.
        effort = min(100.0, flow_total/max(last_price, 1e-9)/1000.0)
        result = min(100.0, abs(micro_return_pct)*35.0)
        absorption = cls._clamp(
            max(0.0, effort-result)
            * min(1.0, abs(delta_ratio)*2.2)
        )
        exhaustion = cls._clamp(
            abs(delta_ratio)*70.0
            if (
                abs(price_change_pct) > 1.0
                and abs(micro_return_pct) < 0.08
            )
            else abs(delta_ratio)*25.0
        )


        # Wall Intelligence V3:
        # near-touch strength + elapsed persistence + velocity + consumption +
        # refresh + removal-sensitive spoofing proxy.
        NEAR_TOUCH_LEVELS = 20
        WALL_PRICE_TOLERANCE_PCT = 0.0015
        WALL_SIZE_KEEP_RATIO = 0.60
        WALL_CONFIRMED_SECONDS = 60.0
        MAX_STREAK = 20

        def parse_previous(side_key: str) -> dict[str, float]:
            empty = {
                "price": 0.0, "notional": 0.0, "streak": 0.0,
                "first_seen_ts": 0.0, "last_seen_ts": 0.0,
                "raw_score": 0.0, "age_seconds": 0.0,
                "legacy": 0.0,
            }
            if not previous_wall_state:
                return empty
            previous = previous_wall_state.get(side_key)
            if previous is None:
                return empty
            if isinstance(previous, dict):
                return {
                    "price": cls._f(previous.get("price")),
                    "notional": cls._f(previous.get("notional")),
                    "streak": cls._f(previous.get("streak")),
                    "first_seen_ts": cls._f(previous.get("first_seen_ts")),
                    "last_seen_ts": cls._f(previous.get("last_seen_ts")),
                    "raw_score": cls._f(previous.get("raw_score")),
                    "age_seconds": cls._f(previous.get("age_seconds")),
                    "legacy": 0.0,
                }
            if isinstance(previous, (tuple, list)) and len(previous) >= 3:
                price = cls._f(previous[0])
                notional = cls._f(previous[1])
                streak = cls._f(previous[2])
                # Legacy compatibility: each historical scan represented 15 seconds.
                prior_age = max(0.0, streak*15.0)
                return {
                    "price": price,
                    "notional": notional,
                    "streak": streak,
                    "first_seen_ts": now_ts-(prior_age+15.0),
                    "last_seen_ts": now_ts-15.0,
                    "raw_score": 100.0 if notional > 0 else 0.0,
                    "age_seconds": prior_age,
                    "legacy": 1.0,
                }
            return empty

        def persistence_from_age(age_seconds: float) -> float:
            if age_seconds <= 0:
                return 0.0
            return cls._clamp(
                (age_seconds/max(WALL_CONFIRMED_SECONDS, 1e-9))**0.5*100.0
            )

        def wall_intelligence(
            levels: list[tuple[float, float]],
            side_key: str,
        ) -> dict[str, float]:
            near_touch = levels[:NEAR_TOUCH_LEVELS]
            previous = parse_previous(side_key)

            if len(near_touch) < 5:
                elapsed = max(0.001, now_ts-previous["last_seen_ts"])
                velocity = -100.0/elapsed if previous["notional"] > 0 else 0.0
                spoof = (
                    min(
                        100.0,
                        previous["raw_score"]
                        * (1.0 if previous["age_seconds"] < 20 else 0.45),
                    )
                    if previous["raw_score"] > 55 else 0.0
                )
                return {
                    "raw_score": 0.0, "price": 0.0, "notional": 0.0,
                    "persistence": 0.0, "streak": 0.0, "age_seconds": 0.0,
                    "velocity": velocity, "consumption": 0.0, "refresh": 0.0,
                    "effective": 0.0, "spoofing": spoof,
                }

            notionals = [p*q for p, q in near_touch]
            med = max(median(notionals), 1e-9)
            top3 = sorted(
                near_touch,
                key=lambda pq: pq[0]*pq[1],
                reverse=True,
            )[:3]
            top3_values = [p*q for p, q in top3]
            raw_score = cls._clamp(
                (sum(top3_values)/len(top3_values)/med-1.0)*18.0
            )
            wall_price = top3[0][0]
            wall_notional = top3[0][0]*top3[0][1]

            elapsed = max(0.001, now_ts-previous["last_seen_ts"])
            same_level = (
                previous["price"] > 0
                and abs(wall_price-previous["price"])
                <= last_price*WALL_PRICE_TOLERANCE_PCT
            )
            size_ratio = (
                wall_notional/previous["notional"]
                if previous["notional"] > 0 else 1.0
            )
            remains = (
                same_level
                and previous["notional"] > 0
                and size_ratio >= WALL_SIZE_KEEP_RATIO
                and raw_score > 0
            )

            if remains:
                first_seen = (
                    previous["first_seen_ts"]
                    if previous["first_seen_ts"] > 0 else now_ts
                )
                age = max(0.0, now_ts-first_seen)
                streak = min(int(previous["streak"])+1, MAX_STREAK)
                velocity = (size_ratio-1.0)*100.0/elapsed
            else:
                first_seen = now_ts
                age = 0.0
                streak = 0
                velocity = -100.0/elapsed if previous["notional"] > 0 else 0.0

            persistence = persistence_from_age(age)
            # Preserve old tuple-based behavior for existing installs/tests:
            # one confirmed repeat = 25 points. Dict V3 state uses real time.
            if remains and previous.get("legacy", 0.0) > 0:
                persistence = cls._clamp(streak*25.0)

            consumption_pct = (
                max(0.0, 1.0-size_ratio)*100.0 if remains else 0.0
            )
            refresh_pct = (
                max(0.0, size_ratio-1.0)*100.0 if remains else 0.0
            )
            consumption = cls._clamp(
                consumption_pct*2.2 + persistence*0.35
            )
            refresh = cls._clamp(
                refresh_pct*1.8 + persistence*0.30
            )

            effective = cls._clamp(
                raw_score*(0.35+0.65*persistence/100.0)
                + min(12.0, consumption*0.07+refresh*0.05)
            )

            disappeared = previous["raw_score"] > 55 and not remains
            current_unconfirmed = raw_score > 55 and persistence < 20
            short_lived = previous["age_seconds"] < 20
            fast_removal = abs(velocity) >= 5
            spoofing = cls._clamp(max(
                raw_score*(1.0-persistence/100.0)
                if current_unconfirmed else 0.0,
                previous["raw_score"]*(
                    1.0 if short_lived and fast_removal else 0.55
                )
                if disappeared else 0.0,
            ))

            return {
                "raw_score": raw_score,
                "price": wall_price,
                "notional": wall_notional,
                "persistence": persistence,
                "streak": float(streak),
                "age_seconds": age,
                "velocity": max(-100.0, min(100.0, velocity)),
                "consumption": consumption,
                "refresh": refresh,
                "effective": effective,
                "spoofing": spoofing,
            }

        bid_data = wall_intelligence(bid_levels, "bid")
        ask_data = wall_intelligence(ask_levels, "ask")

        bid_wall = bid_data["raw_score"]
        ask_wall = ask_data["raw_score"]
        bid_wall_price = bid_data["price"]
        ask_wall_price = ask_data["price"]
        bid_wall_notional = bid_data["notional"]
        ask_wall_notional = ask_data["notional"]
        bid_wall_persistence = bid_data["persistence"]
        ask_wall_persistence = ask_data["persistence"]
        bid_wall_streak = int(bid_data["streak"])
        ask_wall_streak = int(ask_data["streak"])
        bid_wall_age_seconds = bid_data["age_seconds"]
        ask_wall_age_seconds = ask_data["age_seconds"]
        bid_wall_velocity = bid_data["velocity"]
        ask_wall_velocity = ask_data["velocity"]
        bid_wall_consumption = bid_data["consumption"]
        ask_wall_consumption = ask_data["consumption"]
        bid_wall_refresh = bid_data["refresh"]
        ask_wall_refresh = ask_data["refresh"]
        bid_wall_effective = bid_data["effective"]
        ask_wall_effective = ask_data["effective"]
        spoofing_probability = cls._clamp(
            max(bid_data["spoofing"], ask_data["spoofing"])
        )

        long_liq = 0.0
        short_liq = 0.0
        for event in liquidations:
            side = str(event.get("side", "")).upper()
            notional = cls._f(event.get("notional"))
            if side == "SELL":
                long_liq += notional
            elif side == "BUY":
                short_liq += notional
        liq_total = long_liq + short_liq
        liquidation_impulse = cls._clamp(
            100.0*liq_total/max(flow_total, 1.0)
        )

        range_like = abs(price_change_pct) <= 1.25
        position_building = cls._clamp(
            (35.0 if range_like else 0.0)
            + min(40.0, max(0.0, oi_change_15m_pct)*12.0)
            + (15.0 if abs(funding_pct) <= 0.02 else 0.0)
            + min(10.0, abs(book_imbalance)*20.0)
        )
        effort_result = cls._clamp(
            0.60*absorption
            + 0.25*max(bid_wall_effective, ask_wall_effective)
            + 0.15*position_building
        )

        bullish = (
            0.30*ofi_score
            + 0.20*cls._clamp(50.0+book_imbalance*50.0)
            + 0.20*absorption*(1.0 if delta_ratio < 0 else 0.45)
            + 0.15*position_building
            + 0.15*bid_wall_effective
        )
        bearish = (
            0.30*(100.0-ofi_score)
            + 0.20*cls._clamp(50.0-book_imbalance*50.0)
            + 0.20*absorption*(1.0 if delta_ratio > 0 else 0.45)
            + 0.15*position_building
            + 0.15*ask_wall_effective
        )
        composite = cls._clamp(max(bullish, bearish))
        if bullish-bearish >= 8:
            operator_bias = "SMART_MONEY_LONG"
        elif bearish-bullish >= 8:
            operator_bias = "SMART_MONEY_SHORT"
        else:
            operator_bias = "NEUTRAL"

        explanation = [
            f"Book imbalance {book_imbalance:+.3f}",
            f"Aggressive delta ${delta:,.0f}",
            f"OFI proxy {ofi_score:.1f}/100",
            f"Absorption {absorption:.1f}/100",
            f"Position building {position_building:.1f}/100",
            (
                f"Wall persistence bid={bid_wall_persistence:.0f} "
                f"ask={ask_wall_persistence:.0f} "
                f"(age {bid_wall_age_seconds:.1f}s/{ask_wall_age_seconds:.1f}s)"
            ),
            (
                f"Wall velocity bid={bid_wall_velocity:+.2f}%/s "
                f"ask={ask_wall_velocity:+.2f}%/s"
            ),
            (
                f"Wall consumption bid={bid_wall_consumption:.1f} "
                f"ask={ask_wall_consumption:.1f}; "
                f"refresh bid={bid_wall_refresh:.1f} "
                f"ask={ask_wall_refresh:.1f}"
            ),
        ]
        if not liquidations:
            explanation.append(
                "Liquidation realtime chưa có: cần WebSocket forceOrder."
            )
        explanation.append(
            "REST bootstrap là L2 snapshot; không phải Level 3."
        )

        quality = (
            "GOOD"
            if bid_levels and ask_levels and len(trades) >= 50
            else "PARTIAL"
        )
        return MicrostructureSnapshot(
            symbol=symbol,
            generated_at=datetime.fromtimestamp(
                now_ts, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S"),
            data_quality=quality,
            bid_depth_usd=bid_depth,
            ask_depth_usd=ask_depth,
            book_imbalance=book_imbalance,
            aggressive_buy_usd=aggressive_buy,
            aggressive_sell_usd=aggressive_sell,
            trade_delta_usd=delta,
            cvd_proxy_usd=delta,
            ofi_score=ofi_score,
            absorption_score=absorption,
            exhaustion_score=exhaustion,
            bid_wall_score=bid_wall,
            ask_wall_score=ask_wall,
            spoofing_probability=spoofing_probability,
            long_liquidation_usd=long_liq,
            short_liquidation_usd=short_liq,
            liquidation_impulse=liquidation_impulse,
            position_building_score=position_building,
            effort_result_score=effort_result,
            composite_operator_score=composite,
            operator_bias=operator_bias,
            explanation=tuple(explanation),
            liquidation_data_available=bool(liquidations),
            websocket_ready=False,
            bid_wall_price=bid_wall_price,
            bid_wall_notional=bid_wall_notional,
            ask_wall_price=ask_wall_price,
            ask_wall_notional=ask_wall_notional,
            bid_wall_persistence=bid_wall_persistence,
            ask_wall_persistence=ask_wall_persistence,
            bid_wall_streak=bid_wall_streak,
            ask_wall_streak=ask_wall_streak,
            bid_wall_age_seconds=bid_wall_age_seconds,
            ask_wall_age_seconds=ask_wall_age_seconds,
            bid_wall_velocity_pct_per_sec=bid_wall_velocity,
            ask_wall_velocity_pct_per_sec=ask_wall_velocity,
            bid_wall_consumption_score=bid_wall_consumption,
            ask_wall_consumption_score=ask_wall_consumption,
            bid_wall_refresh_score=bid_wall_refresh,
            ask_wall_refresh_score=ask_wall_refresh,
            bid_wall_effective_score=bid_wall_effective,
            ask_wall_effective_score=ask_wall_effective,
        )
