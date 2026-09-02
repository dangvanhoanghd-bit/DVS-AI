from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence

class EntryStatus(str, Enum):
    WAIT = "WAIT"
    SETUP = "SETUP"
    READY = "READY"
    RUNNING = "RUNNING"

@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    last_price: float
    mark_price: float
    change_24h_pct: float
    quote_volume_24h: float
    funding_pct: float
    open_interest: float
    oi_change_15m_pct: float
    oi_change_1h_pct: float

@dataclass(frozen=True)
class TimeframeAnalysis:
    timeframe: str
    close: float
    price_change_pct: float
    cmf: float
    rsi: float
    ema20: float
    ema50: float
    ema200: float
    adx: float
    atr: float
    relative_volume: float
    support: float
    resistance: float
    spring: bool
    upthrust: bool
    market_phase: str
    long_trend_score: float
    short_trend_score: float
    long_entry_score: float
    short_entry_score: float
    opens: tuple[float, ...]
    highs: tuple[float, ...]
    lows: tuple[float, ...]
    closes: tuple[float, ...]
    cmf_values: tuple[float, ...]
    rsi_values: tuple[float, ...]
    spring_type: str = "NONE"
    upthrust_type: str = "NONE"
    wyckoff_test_long: bool = False
    wyckoff_test_short: bool = False
    wyckoff_test_score: float = 0.0
    long_trend_maturity: float = 0.0
    short_trend_maturity: float = 0.0
    long_trend_lifecycle: str = "UNFORMED"
    short_trend_lifecycle: str = "UNFORMED"
    bars_since_long_cross: int = 999
    bars_since_short_cross: int = 999
    long_retest_count: int = 0
    short_retest_count: int = 0


@dataclass(frozen=True)
class StructureAnalysis:
    daily_high: float
    daily_low: float
    weekly_high: float
    weekly_low: float
    monthly_high: float
    monthly_low: float
    liquidity_event: str
    wyckoff_signal: str
    effort_result: str
    liquidity_score: float
    wyckoff_score: float
    warnings: tuple[str, ...]
    sweep_volume_state: str = "NONE"
    wyckoff_test: str = "NONE"
    wyckoff_test_score: float = 0.0


@dataclass(frozen=True)
class RegimeAnalysis:
    regime: str
    direction: str
    strength: float
    volatility_state: str
    description: str

@dataclass(frozen=True)
class AlignmentAnalysis:
    label: str
    long_score: float
    short_score: float
    aligned_timeframes: tuple[str, ...]
    conflicting_timeframes: tuple[str, ...]
    description: str

@dataclass(frozen=True)
class RiskAnalysis:
    risk_score: float
    risk_level: str
    volatility_risk: float
    funding_risk: float
    oi_risk: float
    extension_risk: float
    conflict_risk: float
    size_factor: float
    warnings: tuple[str, ...]
    leverage: float = 1.0
    liquidation_price: float = 0.0
    liquidation_distance_pct: float = 0.0
    max_safe_leverage: float = 1.0
    liquidation_safe: bool = True
    position_notional: float = 0.0
    margin_required: float = 0.0
    risk_amount: float = 0.0
    dynamic_buffer_used: float = 0.0
    effective_stop_distance: float = 0.0
    exposure_cap: float = 0.0
    leverage_constraint_state: str = "UNKNOWN"


@dataclass(frozen=True)
class SmartEntryAnalysis:
    panic_flush_score: float
    weak_hand_score: float
    absorption_score: float
    fake_breakdown_score: float
    fake_breakout_score: float
    cmf_rsi_divergence: str
    long_opportunity_index: float
    short_opportunity_index: float
    smart_money_probability: float
    state: str
    explanation: tuple[str, ...]
    long_pressure_score: float = 0.0
    short_pressure_score: float = 0.0
    long_structure_score: float = 0.0
    short_structure_score: float = 0.0
    long_context_score: float = 0.0
    short_context_score: float = 0.0
    smart_money_direction: str = "NEUTRAL"
    independent_group_count: int = 0
    audit_flags: tuple[str, ...] = ()

@dataclass(frozen=True)
class TradePlan:
    direction: str
    entry_low: float
    entry_high: float
    invalidation: float
    tp1: float
    tp2: float
    rr_to_tp2: float
    confirmations: tuple[str, ...]
    cancellation_rules: tuple[str, ...]
    plan_repaired: bool = False
    plan_repair_reason: str = ""


@dataclass(frozen=True)
class MicrostructureSnapshot:
    symbol: str
    generated_at: str
    data_quality: str
    bid_depth_usd: float
    ask_depth_usd: float
    book_imbalance: float
    aggressive_buy_usd: float
    aggressive_sell_usd: float
    trade_delta_usd: float
    cvd_proxy_usd: float
    ofi_score: float
    absorption_score: float
    exhaustion_score: float
    bid_wall_score: float
    ask_wall_score: float
    spoofing_probability: float
    long_liquidation_usd: float
    short_liquidation_usd: float
    liquidation_impulse: float
    position_building_score: float
    effort_result_score: float
    composite_operator_score: float
    operator_bias: str
    explanation: tuple[str, ...]
    liquidation_data_available: bool = False
    websocket_ready: bool = False
    bid_wall_price: float = 0.0
    bid_wall_notional: float = 0.0
    ask_wall_price: float = 0.0
    ask_wall_notional: float = 0.0
    bid_wall_persistence: float = 0.0
    ask_wall_persistence: float = 0.0
    bid_wall_streak: int = 0
    ask_wall_streak: int = 0
    bid_wall_age_seconds: float = 0.0
    ask_wall_age_seconds: float = 0.0
    bid_wall_velocity_pct_per_sec: float = 0.0
    ask_wall_velocity_pct_per_sec: float = 0.0
    bid_wall_consumption_score: float = 0.0
    ask_wall_consumption_score: float = 0.0
    bid_wall_refresh_score: float = 0.0
    ask_wall_refresh_score: float = 0.0
    bid_wall_effective_score: float = 0.0
    ask_wall_effective_score: float = 0.0


@dataclass(frozen=True)
class CoinAnalysis:
    symbol: str
    snapshot: MarketSnapshot
    timeframes: Mapping[str, TimeframeAnalysis]
    long_trend_score: float
    short_trend_score: float
    long_entry_score: float
    short_entry_score: float
    direction: str
    entry_status: EntryStatus
    priority_status: str
    oi_state: str
    phase_summary: str
    confidence_score: float
    reasons: tuple[str, ...]
    trade_plan: TradePlan
    structure: StructureAnalysis
    regime: RegimeAnalysis
    alignment: AlignmentAnalysis
    risk: RiskAnalysis
    smart_entry: SmartEntryAnalysis
    action: str
    timing: str
    generated_at: str
    trend_maturity_score: float = 0.0
    trend_lifecycle: str = "UNFORMED"
    maturity_15m: float = 0.0
    maturity_1h: float = 0.0
    maturity_gate: str = "NONE"
    market_bias_code: str = "NEUTRAL"
    market_bias_gate: str = "NOT_APPLIED"
    direction_confirmation_score: float = 0.0
    direction_confirmation_gate: str = "NOT_APPLIED"
    confidence_before_context: float = 0.0
    confidence_context_adjustment: float = 0.0
    opportunity_score: float = 0.0
    opportunity_rank: int = 999
    opportunity_gate: str = "UNRANKED"
    opportunity_base_score: float = 0.0
    opportunity_bonus: float = 0.0
    opportunity_penalty: float = 0.0
    opportunity_penalty_reason: str = "NONE"
    opportunity_percentile: float = 0.0
    microstructure: MicrostructureSnapshot | None = None
    microstructure_gate: str = "NOT_AVAILABLE"
    footprint: object | None = None
    footprint_raw_score: float = 0.0
    footprint_score: float = 0.0
    footprint_context_multiplier: float = 1.0
    footprint_confirmation_depth: str = "NONE"
    footprint_direction_alignment: str = "NOT_APPLIED"
    footprint_gate: str = "NOT_APPLIED"
    position_building_score: float = 0.0
    position_building_regime: str = "UNKNOWN"
    early_entry_score: float = 0.0
    smart_money_alignment_score: float = 0.0
    decision_quality_score: float = 0.0
    reasoning_headline: str = ""
    reasoning_support: tuple[str, ...] = ()
    reasoning_conflicts: tuple[str, ...] = ()
    reasoning_hard_blocks: tuple[str, ...] = ()
    market_narrative: tuple[str, ...] = ()
    next_confirmation: tuple[str, ...] = ()
    reasoning_text: str = ""
    footprint_chain: tuple[str, ...] = ()
    footprint_chain_text: str = ""
    footprint_chain_completeness: float = 0.0
    position_persistence_score: float = 0.0
    position_acceleration_score: float = 0.0
    position_confidence_score: float = 0.0
    decision_quality_active_weight: float = 0.0
    decision_quality_components: tuple[str, ...] = ()
    decision_hard_reasons: tuple[str, ...] = ()
    confidence_fusion_method: str = "LEGACY"
    calibrated_probability: float = 0.0
    probability_calibration_state: str = "NOT_EVALUATED"
    probability_calibration_samples: int = 0
    probability_calibration_method: str = "NONE"
    adaptive_probability: float = 0.0
    adaptive_confidence_state: str = "NOT_EVALUATED"
    adaptive_confidence_adjustment: float = 0.0
    adaptive_confidence_samples: int = 0
    adaptive_confidence_context: str = "NONE"
    calibration_drift_state: str = "NOT_EVALUATED"
    calibration_drift_samples: int = 0
    calibration_drift_brier_delta: float = 0.0
    calibration_drift_ece_delta: float = 0.0
    calibration_drift_psi: float = 0.0
    evidence_reliability_state: str = "NOT_EVALUATED"
    evidence_reliability_summary: tuple[str, ...] = ()
    evidence_reliability_method: str = "NONE"
    composite_exhaustion: object | None = None
    composite_distribution_progress: float = 0.0
    composite_selling_pressure: float = 0.0
    composite_exhaustion_score: float = 0.0
    bottom_formation_probability: float = 0.0
    bottom_formation_state: str = "NOT_EVALUATED"
    composite_timeline: tuple[str, ...] = ()
    explainable_narrative: object | None = None
    explainable_headline: str = ""
    explainable_blockers: tuple[str, ...] = ()
    explainable_next_confirmation: tuple[str, ...] = ()

@dataclass(frozen=True)
class MarketBrief:
    btc_bias: str
    alt_breadth_long_pct: float
    market_bias: str
    risk_level: str
    summary: str
    bias_code: str = "NEUTRAL"
    bias_strength: float = 0.0
