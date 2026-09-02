from __future__ import annotations
from dvs_ai.domain.models import (
    AlignmentAnalysis, MarketSnapshot, RiskAnalysis,
    TimeframeAnalysis, RegimeAnalysis, TradePlan
)


class RiskEngine:
    def __init__(self, config=None):
        self.config = config

    def _cfg(self, name, default):
        return float(getattr(self.config, name, default))


    def resolve_mmr(
        self,
        notional: float,
        tiers: tuple[tuple[float, float, float], ...] | None = None,
    ) -> tuple[float, float, str]:
        """
        Resolve maintenance margin for an optional notional bracket table.

        Tier format:
            (notional_cap, maintenance_margin_rate, maintenance_amount)

        No verified symbol table is bundled in this release. Without tiers,
        the configured fixed MMR is returned as a deterministic approximation.
        """
        fixed = max(
            0.0,
            self._cfg("maintenance_margin_rate", 0.005),
        )
        if not tiers:
            return fixed, 0.0, "FIXED_APPROXIMATION"

        value = max(0.0, float(notional))
        ordered = sorted(tiers, key=lambda item: float(item[0]))
        for cap, rate, maintenance_amount in ordered:
            if value <= float(cap):
                return (
                    max(0.0, float(rate)),
                    max(0.0, float(maintenance_amount)),
                    "TIER_TABLE",
                )
        _, rate, maintenance_amount = ordered[-1]
        return (
            max(0.0, float(rate)),
            max(0.0, float(maintenance_amount)),
            "TIER_TABLE_MAX",
        )


    def _futures_risk(
        self,
        direction: str,
        plan: TradePlan,
        r15: TimeframeAnalysis,
    ):
        leverage = max(1.0, self._cfg("leverage", 5.0))
        mmr, _, _ = self.resolve_mmr(0.0)
        fee = max(0.0, self._cfg("taker_fee_rate", 0.0005))
        base_buffer = max(0.0, self._cfg("liquidation_buffer_pct", 0.003))
        equity = max(1.0, self._cfg("account_equity_usdt", 1000.0))
        risk_pct = max(0.1, self._cfg("risk_per_trade_pct", 1.0))
        exposure_multiple = max(1.0, self._cfg("max_exposure_multiple", 8.0))

        entry = (plan.entry_low + plan.entry_high) / 2.0
        if entry <= 0:
            raise ValueError("Entry phải lớn hơn 0.")

        if direction == "LONG" and plan.invalidation >= entry:
            raise ValueError("LONG invalidation phải thấp hơn entry.")
        if direction == "SHORT" and plan.invalidation <= entry:
            raise ValueError("SHORT invalidation phải cao hơn entry.")

        stop_distance = abs(entry - plan.invalidation)
        atr_pct = max(0.0, r15.atr / entry)
        dynamic_buffer = min(
            base_buffer * 3.0,
            max(base_buffer, base_buffer * (1.0 + atr_pct * 400.0)),
        )

        # Conservative isolated USDT perpetual approximation.
        # resolve_mmr() currently returns the fixed configured approximation
        # unless a verified symbol/notional bracket table is supplied.
        # `mmr` is the configured bracket estimate. Binance applies tiered
        # maintenance-margin brackets by symbol/notional; therefore the UI
        # labels liquidation as an estimate and the exposure cap limits
        # bracket drift.
        if direction == "LONG":
            liquidation = entry * (
                1.0 - 1.0 / leverage + mmr + fee
            )
            safe_boundary = plan.invalidation * (1.0 - dynamic_buffer)
            liquidation_safe = liquidation < safe_boundary
            denominator = (
                1.0 + mmr + fee - safe_boundary / entry
            )
        else:
            liquidation = entry * (
                1.0 + 1.0 / leverage - mmr - fee
            )
            safe_boundary = plan.invalidation * (1.0 + dynamic_buffer)
            liquidation_safe = liquidation > safe_boundary
            denominator = (
                safe_boundary / entry - 1.0 + mmr + fee
            )

        epsilon = 1e-8
        if denominator <= epsilon:
            max_safe_leverage = 125.0
            constraint_state = "STOP_GEOMETRY_NOT_LIMITING"
        else:
            max_safe_leverage = min(125.0, max(1.0, 1.0 / denominator))
            constraint_state = "STOP_LIMITED"

        liquidation_distance_pct = abs(entry - liquidation) / entry * 100.0
        risk_amount = equity * risk_pct / 100.0

        # Fees + a small slippage allowance are included in risk sizing.
        slippage = self._cfg("paper_slippage_rate", 0.0005)
        effective_stop_distance = (
            stop_distance + entry * (2.0 * fee + slippage)
        )
        risk_based_notional = (
            risk_amount * entry / max(effective_stop_distance, epsilon)
        )
        exposure_cap = equity * exposure_multiple
        safe_leverage_cap = equity * max_safe_leverage * 0.85
        configured_margin_cap = equity * leverage
        position_notional = min(
            risk_based_notional,
            exposure_cap,
            safe_leverage_cap,
            configured_margin_cap,
        )
        margin_required = position_notional / leverage

        return {
            "leverage": leverage,
            "liquidation_price": liquidation,
            "liquidation_distance_pct": liquidation_distance_pct,
            "max_safe_leverage": max_safe_leverage,
            "liquidation_safe": liquidation_safe,
            "position_notional": max(0.0, position_notional),
            "margin_required": max(0.0, margin_required),
            "risk_amount": risk_amount,
            "dynamic_buffer_used": dynamic_buffer,
            "effective_stop_distance": effective_stop_distance,
            "exposure_cap": exposure_cap,
            "leverage_constraint_state": constraint_state,
        }

    def analyze(
        self,
        snap: MarketSnapshot,
        tf: dict[str, TimeframeAnalysis],
        alignment: AlignmentAnalysis,
        regime: RegimeAnalysis,
        direction: str,
        trade_plan: TradePlan | None = None,
    ) -> RiskAnalysis:
        r15 = tf["15m"]
        atr_pct = r15.atr / max(r15.close, 1e-12) * 100.0
        volatility_risk = min(30.0, atr_pct * 10.0)

        funding_abs = abs(snap.funding_pct)
        funding_risk = min(18.0, funding_abs * 180.0)
        if direction == "LONG" and snap.funding_pct < 0:
            funding_risk *= 0.6
        if direction == "SHORT" and snap.funding_pct > 0:
            funding_risk *= 0.6

        oi_abs = max(abs(snap.oi_change_15m_pct), abs(snap.oi_change_1h_pct))
        oi_risk = min(20.0, oi_abs * 8.0)

        if direction == "LONG":
            extension = max(0.0, r15.close-r15.ema20) / max(r15.atr,1e-12)
        else:
            extension = max(0.0, r15.ema20-r15.close) / max(r15.atr,1e-12)
        extension_risk = min(22.0, max(0.0, extension-1.0)*9.0)

        conflict_risk = 22.0 if alignment.label == "MÂU THUẪN" else (
            10.0 if "NGHIÊNG" in alignment.label else 3.0
        )
        if regime.regime == "RANGE":
            conflict_risk += 5.0
        elif regime.regime == "TRANSITION":
            conflict_risk += 8.0

        futures = {
            "leverage": 1.0, "liquidation_price": 0.0,
            "liquidation_distance_pct": 0.0, "max_safe_leverage": 1.0,
            "liquidation_safe": True, "position_notional": 0.0,
            "margin_required": 0.0, "risk_amount": 0.0,
            "dynamic_buffer_used": 0.0, "effective_stop_distance": 0.0,
            "exposure_cap": 0.0, "leverage_constraint_state": "NO_PLAN",
        }
        liquidation_penalty = 0.0
        if trade_plan is not None:
            futures = self._futures_risk(direction, trade_plan, r15)
            if not futures["liquidation_safe"]:
                liquidation_penalty = 35.0
            elif futures["leverage"] > futures["max_safe_leverage"] * 0.85:
                liquidation_penalty = 12.0

        risk_score = min(
            100.0,
            volatility_risk + funding_risk + oi_risk
            + extension_risk + conflict_risk + liquidation_penalty
        )

        if risk_score >= 75:
            level, size_factor = "RẤT CAO", 0.25
        elif risk_score >= 55:
            level, size_factor = "CAO", 0.50
        elif risk_score >= 35:
            level, size_factor = "TRUNG BÌNH", 0.75
        else:
            level, size_factor = "THẤP", 1.00

        warnings = []
        if volatility_risk >= 18: warnings.append("Biến động ATR cao.")
        if funding_risk >= 10: warnings.append("Funding lệch đáng kể.")
        if oi_risk >= 10: warnings.append("OI thay đổi mạnh.")
        if extension_risk >= 10: warnings.append("Giá cách EMA20 quá xa.")
        if conflict_risk >= 18: warnings.append("Các khung thời gian mâu thuẫn.")
        if trade_plan is not None:
            if not futures["liquidation_safe"]:
                warnings.append(
                    "NGUY HIỂM: thanh lý có thể xảy ra trước invalidation."
                )
            if futures["leverage"] > futures["max_safe_leverage"]:
                warnings.append("Đòn bẩy vượt mức tối đa an toàn.")
            if futures["effective_stop_distance"] / max(r15.close,1e-12) < 0.001:
                warnings.append("Stop quá gần sau khi tính phí/trượt giá.")
            warnings.append(
                "Liquidation là ước tính; tier MMR thực tế có thể thay đổi."
            )
            warnings.append(
                "MMR source: FIXED_APPROXIMATION "
                "(chưa nạp bracket theo symbol/notional)."
            )

        return RiskAnalysis(
            risk_score=risk_score, risk_level=level,
            volatility_risk=volatility_risk, funding_risk=funding_risk,
            oi_risk=oi_risk, extension_risk=extension_risk,
            conflict_risk=conflict_risk, size_factor=size_factor,
            warnings=tuple(warnings), **futures,
        )
