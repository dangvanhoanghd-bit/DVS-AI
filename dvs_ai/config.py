from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json


@dataclass(frozen=True)
class AppConfig:
    watchlist: tuple[str, ...]
    timeframes: tuple[str, ...]
    refresh_seconds: int
    ohlcv_limit: int
    top_n: int
    scan_workers: int
    market_cache_ttl_seconds: float

    universe_enabled: bool
    universe_size: int
    deep_scan_size: int
    min_quote_volume_24h: float

    main_long_limit: int
    main_short_limit: int
    shadow_long_limit: int
    shadow_short_limit: int

    main_confidence: float
    main_entry: float
    main_risk_max: float
    main_rr_min: float

    shadow_confidence: float
    shadow_entry: float
    shadow_risk_max: float
    shadow_rr_min: float

    opportunity_main_top_n: int
    opportunity_shadow_top_n: int
    opportunity_min_score: float
    shadow_opportunity_min_score: float
    shadow_allow_wait_discovery: bool
    shadow_research_confidence: float
    shadow_research_entry: float
    shadow_fatal_micro_only: bool
    confidence_calibration_max_boost: float
    microstructure_enabled: bool
    microstructure_top_n: int
    microstructure_weight: float
    microstructure_confirm_bonus: float
    microstructure_conflict_penalty: float
    microstructure_min_cos: float
    microstructure_shadow_min_absorption: float
    microstructure_shadow_min_ofi_edge: float
    microstructure_shadow_min_building: float

    account_equity_usdt: float
    risk_per_trade_pct: float
    leverage: float
    maintenance_margin_rate: float
    taker_fee_rate: float
    liquidation_buffer_pct: float
    max_exposure_multiple: float
    paper_slippage_rate: float
    paper_trade_expiry_days: int
    paper_update_limit: int
    paper_fetch_chunk: int
    paper_max_chunks: int
    paper_slippage_randomized: bool
    paper_slippage_stddev: float
    quantum_enabled: bool
    quantum_min_closed: int
    quantum_reoptimize_every: int
    quantum_validation_ratio: float
    quantum_auto_apply_shadow: bool

    execution_mode: str
    execution_live_enabled: bool
    execution_daily_loss_limit: float
    execution_max_consecutive_losses: int
    execution_max_open_exposure: float
    execution_max_daily_trades: int
    execution_max_api_error_rate: float
    execution_max_market_data_age_seconds: float

    evidence_fusion_family_weights: dict[str, float]
    evidence_fusion_source_multipliers: dict[str, float]
    evidence_fusion_contradiction_penalty: float
    evidence_fusion_contradiction_cap: float
    evidence_fusion_reliability_enabled: bool



def _safe_execution_mode(value: object) -> str:
    mode = str(value or "PAPER").strip().upper()
    return mode if mode in {"PAPER", "TESTNET", "LIVE"} else "PAPER"


def _safe_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def load_config(path: str | Path = "config.json") -> AppConfig:
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))

    watchlist = tuple(
        str(x).strip().upper()
        for x in raw.get("watchlist", [])
        if str(x).strip()
    )
    timeframes = tuple(
        str(x)
        for x in raw.get("timeframes", ["15m", "1h", "4h", "1d"])
    )

    return AppConfig(
        watchlist=watchlist,
        timeframes=timeframes,
        refresh_seconds=max(15, int(raw.get("refresh_seconds", 60))),
        ohlcv_limit=max(220, int(raw.get("ohlcv_limit", 260))),
        top_n=max(1, int(raw.get("top_n", 5))),
        scan_workers=min(
            12,
            max(2, int(raw.get("scan_workers", 6))),
        ),
        market_cache_ttl_seconds=min(
            120.0,
            max(
                5.0,
                float(raw.get("market_cache_ttl_seconds", 25.0)),
            ),
        ),

        universe_enabled=bool(raw.get("universe_enabled", True)),
        universe_size=min(200, max(20, int(raw.get("universe_size", 120)))),
        deep_scan_size=min(80, max(10, int(raw.get("deep_scan_size", 40)))),
        min_quote_volume_24h=max(
            0.0, float(raw.get("min_quote_volume_24h", 20_000_000))
        ),

        main_long_limit=max(1, int(raw.get("main_long_limit", 25))),
        main_short_limit=max(1, int(raw.get("main_short_limit", 25))),
        shadow_long_limit=max(1, int(raw.get("shadow_long_limit", 50))),
        shadow_short_limit=max(1, int(raw.get("shadow_short_limit", 50))),

        main_confidence=float(raw.get("main_confidence", 70)),
        main_entry=float(raw.get("main_entry", 65)),
        main_risk_max=float(raw.get("main_risk_max", 50)),
        main_rr_min=float(raw.get("main_rr_min", 1.8)),

        shadow_confidence=float(raw.get("shadow_confidence", 55)),
        shadow_entry=float(raw.get("shadow_entry", 50)),
        shadow_risk_max=float(raw.get("shadow_risk_max", 60)),
        shadow_rr_min=float(raw.get("shadow_rr_min", 1.5)),

        opportunity_main_top_n=min(
            10, max(1, int(raw.get("opportunity_main_top_n", 3)))
        ),
        opportunity_shadow_top_n=min(
            20, max(1, int(raw.get("opportunity_shadow_top_n", 5)))
        ),
        opportunity_min_score=min(
            100.0,
            max(0.0, float(raw.get("opportunity_min_score", 52.0))),
        ),
        shadow_opportunity_min_score=min(
            100.0,
            max(0.0, float(raw.get("shadow_opportunity_min_score", 28.0))),
        ),
        shadow_allow_wait_discovery=bool(
            raw.get("shadow_allow_wait_discovery", True)
        ),
        shadow_research_confidence=min(
            100.0,
            max(0.0, float(raw.get("shadow_research_confidence", 34.0))),
        ),
        shadow_research_entry=min(
            100.0,
            max(0.0, float(raw.get("shadow_research_entry", 35.0))),
        ),
        shadow_fatal_micro_only=bool(
            raw.get("shadow_fatal_micro_only", True)
        ),
        microstructure_enabled=bool(raw.get("microstructure_enabled", True)),
        microstructure_top_n=min(
            20, max(1, int(raw.get("microstructure_top_n", 8)))
        ),
        microstructure_weight=min(
            0.50,
            max(0.0, float(raw.get("microstructure_weight", 0.25))),
        ),
        microstructure_confirm_bonus=min(
            10.0,
            max(0.0, float(raw.get("microstructure_confirm_bonus", 6.0))),
        ),
        microstructure_conflict_penalty=min(
            20.0,
            max(0.0, float(raw.get("microstructure_conflict_penalty", 12.0))),
        ),
        microstructure_min_cos=min(
            100.0,
            max(0.0, float(raw.get("microstructure_min_cos", 48.0))),
        ),
        microstructure_shadow_min_absorption=min(
            100.0,
            max(
                0.0,
                float(
                    raw.get(
                        "microstructure_shadow_min_absorption",
                        18.0,
                    )
                ),
            ),
        ),
        microstructure_shadow_min_ofi_edge=min(
            50.0,
            max(
                0.0,
                float(
                    raw.get(
                        "microstructure_shadow_min_ofi_edge",
                        6.0,
                    )
                ),
            ),
        ),
        microstructure_shadow_min_building=min(
            100.0,
            max(
                0.0,
                float(
                    raw.get(
                        "microstructure_shadow_min_building",
                        15.0,
                    )
                ),
            ),
        ),
        confidence_calibration_max_boost=min(
            10.0,
            max(
                0.0,
                float(
                    raw.get(
                        "confidence_calibration_max_boost",
                        5.0,
                    )
                ),
            ),
        ),

        account_equity_usdt=max(
            1.0, float(raw.get("account_equity_usdt", 1000.0))
        ),
        risk_per_trade_pct=min(
            10.0, max(0.1, float(raw.get("risk_per_trade_pct", 1.0)))
        ),
        leverage=min(125.0, max(1.0, float(raw.get("leverage", 5.0)))),
        maintenance_margin_rate=min(
            0.05,
            max(0.0, float(raw.get("maintenance_margin_rate", 0.005))),
        ),
        taker_fee_rate=min(
            0.01, max(0.0, float(raw.get("taker_fee_rate", 0.0005)))
        ),
        liquidation_buffer_pct=min(
            0.05,
            max(0.0, float(raw.get("liquidation_buffer_pct", 0.003))),
        ),
        max_exposure_multiple=min(
            20.0, max(1.0, float(raw.get("max_exposure_multiple", 8.0)))
        ),
        paper_slippage_rate=min(
            0.01, max(0.0, float(raw.get("paper_slippage_rate", 0.0005)))
        ),
        paper_trade_expiry_days=max(
            1, int(raw.get("paper_trade_expiry_days", 7))
        ),
        paper_update_limit=max(
            30, int(raw.get("paper_update_limit", 200))
        ),
        paper_fetch_chunk=min(
            1500, max(100, int(raw.get("paper_fetch_chunk", 1000)))
        ),
        paper_max_chunks=min(
            20, max(1, int(raw.get("paper_max_chunks", 8)))
        ),
        paper_slippage_randomized=bool(
            raw.get("paper_slippage_randomized", True)
        ),
        paper_slippage_stddev=min(
            0.01,
            max(0.0, float(raw.get("paper_slippage_stddev", 0.00025))),
        ),
        quantum_enabled=bool(raw.get("quantum_enabled", True)),
        quantum_min_closed=max(40, int(raw.get("quantum_min_closed", 80))),
        quantum_reoptimize_every=max(10, int(raw.get("quantum_reoptimize_every", 25))),
        quantum_validation_ratio=min(0.40, max(0.20, float(raw.get("quantum_validation_ratio", 0.30)))),
        quantum_auto_apply_shadow=bool(raw.get("quantum_auto_apply_shadow", False)),

        execution_mode=_safe_execution_mode(
            raw.get("execution_mode", "PAPER")
        ),
        execution_live_enabled=bool(
            raw.get("execution_live_enabled", False)
        ),
        execution_daily_loss_limit=max(
            1.0,
            _safe_float(
                raw.get("execution_daily_loss_limit", 50.0),
                50.0,
            ),
        ),
        execution_max_consecutive_losses=max(
            1,
            _safe_int(
                raw.get("execution_max_consecutive_losses", 4),
                4,
            ),
        ),
        execution_max_open_exposure=max(
            0.0,
            _safe_float(
                raw.get("execution_max_open_exposure", 5000.0),
                5000.0,
            ),
        ),
        execution_max_daily_trades=max(
            1,
            _safe_int(
                raw.get("execution_max_daily_trades", 30),
                30,
            ),
        ),
        execution_max_api_error_rate=min(
            1.0,
            max(
                0.0,
                _safe_float(
                    raw.get("execution_max_api_error_rate", 0.25),
                    0.25,
                ),
            ),
        ),
        execution_max_market_data_age_seconds=max(
            1.0,
            _safe_float(
                raw.get(
                    "execution_max_market_data_age_seconds",
                    15.0,
                ),
                15.0,
            ),
        ),
        evidence_fusion_family_weights={
            str(k).upper(): max(0.0, _safe_float(v, 0.0))
            for k, v in dict(raw.get("evidence_fusion_family_weights", {
                "TIMING": 0.22, "ENTRY": 0.18, "ORDER_FLOW": 0.32,
                "DIRECTION": 0.16, "MARKET": 0.12,
            })).items()
        },
        evidence_fusion_source_multipliers={
            str(k).upper(): min(1.0, max(0.0, _safe_float(v, 0.0)))
            for k, v in dict(raw.get("evidence_fusion_source_multipliers", {
                "FULL": 1.0, "PROXY": 0.82, "BOOTSTRAP": 0.55,
                "SIMULATED": 0.35, "UNKNOWN": 0.70,
            })).items()
        },
        evidence_fusion_contradiction_penalty=min(
            40.0, max(0.0, _safe_float(raw.get("evidence_fusion_contradiction_penalty", 14.0), 14.0))
        ),
        evidence_fusion_contradiction_cap=min(
            100.0, max(0.0, _safe_float(raw.get("evidence_fusion_contradiction_cap", 68.0), 68.0))
        ),
        evidence_fusion_reliability_enabled=bool(
            raw.get("evidence_fusion_reliability_enabled", True)
        ),
    )
