from __future__ import annotations
import threading
import time

import sqlite3
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from dvs_ai.domain.models import CoinAnalysis, EntryStatus


class PaperTradeService:
    PILOT_ID = "PILOT_5L_5S_V1"
    TP1_CLOSE_FRACTION = 0.50
    RUNNER_FRACTION = 0.50

    def __init__(
        self,
        provider,
        decision_engine,
        db_path: str = "data/dvs_paper_trades.db",
        config=None,
        observation_runtime=None,
    ) -> None:
        self.provider = provider
        self.decision_engine = decision_engine
        self.db_path = Path(db_path)
        self.config = config
        self.observation_runtime = observation_runtime
        self._diagnostics = {
            "evaluated": 0, "main_eligible": 0, "shadow_eligible": 0,
            "created": 0, "duplicate_blocked": 0, "capacity_blocked": 0,
            "gate_blocked": 0, "invalid_direction": 0, "errors": 0,
        }
        # Giữ PILOT_ID cũ làm MAIN để tương thích database và test cũ.
        self.MAIN_PILOT_ID = self.PILOT_ID
        self.SHADOW_PILOT_ID = "SHADOW_50L_50S_V1"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        # RC6.4.7A-r1: bounded wait prevents the GUI thread from hanging
        # indefinitely on a locked SQLite database.
        con = sqlite3.connect(self.db_path, timeout=3.0)
        con.execute("PRAGMA busy_timeout=3000")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        return con

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS paper_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pilot_id TEXT NOT NULL,
                    lab TEXT NOT NULL DEFAULT 'MAIN',
                    created_at TEXT NOT NULL,
                    signal_time TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    entry_low REAL NOT NULL,
                    entry_high REAL NOT NULL,
                    planned_entry REAL NOT NULL,
                    fill_price REAL,
                    fill_time TEXT,
                    invalidation REAL NOT NULL,
                    tp1 REAL NOT NULL,
                    tp2 REAL NOT NULL,
                    rr_planned REAL NOT NULL,
                    confidence REAL NOT NULL,
                    entry_score REAL NOT NULL,
                    risk_score REAL NOT NULL,
                    smart_money_score REAL NOT NULL,
                    wyckoff_score REAL NOT NULL,
                    regime TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    oi_state TEXT NOT NULL,
                    funding REAL NOT NULL,
                    mfe_r REAL DEFAULT 0,
                    mae_r REAL DEFAULT 0,
                    result TEXT DEFAULT 'OPEN',
                    r_multiple REAL DEFAULT 0,
                    tp1_realized_r REAL DEFAULT 0,
                    tp1_hit_time TEXT,
                    closed_at TEXT,
                    close_price REAL,
                    last_checked_at TEXT,
                    slippage_rate REAL DEFAULT 0,
                    realized_slippage_rate REAL DEFAULT 0,
                    outcome_detail TEXT,
                    setup_tags TEXT,
                    note TEXT,
                    reasoning_text TEXT,
                    market_narrative TEXT
                )
            """)
            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_paper_status
                ON paper_trades(status, created_at)
            """)
            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_paper_symbol
                ON paper_trades(symbol, direction, status)
            """)

            # Migration cho database Alpha 2.2/2.3 đã tồn tại.
            columns = {
                row[1] for row in con.execute(
                    "PRAGMA table_info(paper_trades)"
                ).fetchall()
            }
            if "tp1_realized_r" not in columns:
                con.execute(
                    "ALTER TABLE paper_trades "
                    "ADD COLUMN tp1_realized_r REAL DEFAULT 0"
                )
            if "tp1_hit_time" not in columns:
                con.execute(
                    "ALTER TABLE paper_trades "
                    "ADD COLUMN tp1_hit_time TEXT"
                )
            if "setup_tags" not in columns:
                con.execute(
                    "ALTER TABLE paper_trades "
                    "ADD COLUMN setup_tags TEXT"
                )
            if "lab" not in columns:
                con.execute(
                    "ALTER TABLE paper_trades "
                    "ADD COLUMN lab TEXT DEFAULT 'MAIN'"
                )
                con.execute(
                    "UPDATE paper_trades SET lab='MAIN' "
                    "WHERE lab IS NULL OR lab=''"
                )
            if "last_checked_at" not in columns:
                con.execute(
                    "ALTER TABLE paper_trades "
                    "ADD COLUMN last_checked_at TEXT"
                )
            if "slippage_rate" not in columns:
                con.execute(
                    "ALTER TABLE paper_trades "
                    "ADD COLUMN slippage_rate REAL DEFAULT 0"
                )
            if "realized_slippage_rate" not in columns:
                con.execute(
                    "ALTER TABLE paper_trades "
                    "ADD COLUMN realized_slippage_rate REAL DEFAULT 0"
                )
            if "outcome_detail" not in columns:
                con.execute(
                    "ALTER TABLE paper_trades "
                    "ADD COLUMN outcome_detail TEXT"
                )
            if "reasoning_text" not in columns:
                con.execute(
                    "ALTER TABLE paper_trades "
                    "ADD COLUMN reasoning_text TEXT"
                )
            if "market_narrative" not in columns:
                con.execute(
                    "ALTER TABLE paper_trades "
                    "ADD COLUMN market_narrative TEXT"
                )
            if "evidence_snapshot_json" not in columns:
                con.execute(
                    "ALTER TABLE paper_trades "
                    "ADD COLUMN evidence_snapshot_json TEXT"
                )
            for name in (
                "candidate_id", "outcome_id", "decision_id",
                "decision_engine_profile_hash", "trade_plan_profile_hash",
            ):
                if name not in columns:
                    con.execute(f"ALTER TABLE paper_trades ADD COLUMN {name} TEXT")
            con.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_candidate_bound
                ON paper_trades(candidate_id) WHERE candidate_id IS NOT NULL
            """)
            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_paper_outcome_bound
                ON paper_trades(outcome_id) WHERE outcome_id IS NOT NULL
            """)

            con.execute("""
                CREATE TABLE IF NOT EXISTS signal_evaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    eligible INTEGER NOT NULL,
                    entry_ready INTEGER NOT NULL,
                    confidence REAL NOT NULL,
                    entry_score REAL NOT NULL,
                    risk_score REAL NOT NULL,
                    rr_planned REAL NOT NULL,
                    rejection_reasons TEXT,
                    source TEXT NOT NULL,
                    lab TEXT NOT NULL DEFAULT 'MAIN'
                )
            """)
            eval_columns = {
                row[1] for row in con.execute(
                    "PRAGMA table_info(signal_evaluations)"
                ).fetchall()
            }
            if "lab" not in eval_columns:
                con.execute(
                    "ALTER TABLE signal_evaluations "
                    "ADD COLUMN lab TEXT DEFAULT 'MAIN'"
                )

            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_signal_eval_time
                ON signal_evaluations(created_at)
            """)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _to_ms(text: str) -> int:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)

    @staticmethod
    def _entry_score(a: CoinAnalysis, direction: str) -> float:
        return (
            a.long_entry_score if direction == "LONG"
            else a.short_entry_score
        )


    def _thresholds(self, lab: str) -> dict[str, float]:
        lab = lab.upper()
        cfg = self.config

        if lab == "SHADOW":
            return {
                "confidence": float(getattr(cfg, "shadow_confidence", 55)),
                "entry": float(getattr(cfg, "shadow_entry", 50)),
                "risk": float(getattr(cfg, "shadow_risk_max", 60)),
                "rr": float(getattr(cfg, "shadow_rr_min", 1.5)),
            }

        return {
            "confidence": float(getattr(cfg, "main_confidence", 70)),
            "entry": float(getattr(cfg, "main_entry", 65)),
            "risk": float(getattr(cfg, "main_risk_max", 50)),
            "rr": float(getattr(cfg, "main_rr_min", 1.8)),
        }


    def eligibility(
        self,
        a: CoinAnalysis,
        direction: str,
        lab: str = "MAIN",
    ) -> tuple[bool, list[str]]:
        direction = direction.upper()
        lab = lab.upper()
        score = self._entry_score(a, direction)
        thresholds = self._thresholds(lab)
        reasons = []

        rank_limit = (
            int(getattr(self.config, "opportunity_main_top_n", 3))
            if lab == "MAIN"
            else int(getattr(self.config, "opportunity_shadow_top_n", 5))
        )
        opportunity_rank = int(getattr(a, "opportunity_rank", 999))
        opportunity_score = float(getattr(a, "opportunity_score", 0.0))
        minimum_opportunity = float(
            getattr(
                self.config,
                "shadow_opportunity_min_score"
                if lab == "SHADOW"
                else "opportunity_min_score",
                28.0 if lab == "SHADOW" else 52.0,
            )
        )
        if lab == "MAIN":
            opportunity_ok = (
                getattr(a, "opportunity_gate", "UNRANKED") == "RANKED"
                and opportunity_rank <= rank_limit
                and opportunity_score >= minimum_opportunity
            )
        else:
            opportunity_ok = (
                opportunity_rank <= rank_limit
                and opportunity_score >= minimum_opportunity
            )

        micro = getattr(a, "microstructure", None)
        micro_gate = str(
            getattr(a, "microstructure_gate", "NOT_AVAILABLE")
        )
        micro_reasons: list[str] = []
        micro_ok = True

        # MAIN remains governed by its existing hard gates. The stricter
        # Microstructure cleaning below applies to SHADOW research samples.
        if lab == "SHADOW" and micro is not None:
            min_cos = float(
                getattr(
                    self.config,
                    "microstructure_min_cos",
                    48.0,
                )
            )
            min_absorption = float(
                getattr(
                    self.config,
                    "microstructure_shadow_min_absorption",
                    18.0,
                )
            )
            min_ofi_edge = float(
                getattr(
                    self.config,
                    "microstructure_shadow_min_ofi_edge",
                    6.0,
                )
            )
            min_building = float(
                getattr(
                    self.config,
                    "microstructure_shadow_min_building",
                    15.0,
                )
            )

            opposing = micro_gate in (
                "WEAK_CONFLICT",
                "CONFLICT",
                "STRONG_CONFLICT",
            )
            if opposing:
                micro_reasons.append("MICROSTRUCTURE_CONFLICT")
                micro_reasons.append("MICRO_OPPOSING_BIAS")
            if micro.composite_operator_score < min_cos:
                micro_reasons.append("MICRO_LOW_COS")
            ofi_edge = abs(float(micro.ofi_score)-50.0)
            low_components = (
                micro.absorption_score < min_absorption
                and ofi_edge < min_ofi_edge
                and micro.position_building_score < min_building
            )
            if low_components:
                micro_reasons.append("MICRO_NO_CONFIRMATION")
                micro_reasons.append("LOW_ABSORPTION")
                micro_reasons.append("LOW_POSITION_BUILDING")
                micro_reasons.append("LOW_ORDERFLOW_CONFIRMATION")

            # Tường "nhìn có vẻ mạnh" (raw score cao) nhưng CHƯA từng
            # được xác nhận qua lần quét nào trước đó (persistence=0) rất
            # có thể là lệnh vừa đặt, có thể bị rút bất kỳ lúc nào
            # (spoofing) — không nên tin dùng ngay ở lần xuất hiện đầu
            # tiên. Chỉ áp dụng cho phía tường LIÊN QUAN đến hướng giao
            # dịch: LONG cần Bid Wall (hỗ trợ), SHORT cần Ask Wall (kháng cự).
            relevant_wall_score = (
                micro.bid_wall_score if direction == "LONG" else micro.ask_wall_score
            )
            relevant_wall_persistence = (
                micro.bid_wall_persistence if direction == "LONG"
                else micro.ask_wall_persistence
            )
            if relevant_wall_score > 55.0:
                if relevant_wall_persistence <= 0.0:
                    micro_reasons.append("MICRO_WALL_UNSTABLE")
                elif relevant_wall_persistence < 50.0:
                    micro_reasons.append("MICRO_LOW_WALL_PERSISTENCE")

            relevant_velocity = (
                micro.bid_wall_velocity_pct_per_sec
                if direction == "LONG"
                else micro.ask_wall_velocity_pct_per_sec
            )
            if micro.spoofing_probability >= 70.0:
                micro_reasons.append("MICRO_WALL_SPOOFING_RISK")
            if relevant_wall_score > 55.0 and relevant_velocity <= -5.0:
                micro_reasons.append("MICRO_WALL_FAST_REMOVAL")

            fatal_micro_reasons = [
                reason
                for reason in micro_reasons
                if reason in (
                    "MICROSTRUCTURE_CONFLICT",
                    "MICRO_OPPOSING_BIAS",
                    "MICRO_WALL_FAST_REMOVAL",
                )
            ]
            if micro.spoofing_probability >= 85.0:
                fatal_micro_reasons.append(
                    "MICRO_WALL_SPOOFING_RISK"
                )
            micro_ok = (
                not fatal_micro_reasons
                if bool(
                    getattr(
                        self.config,
                        "shadow_fatal_micro_only",
                        True,
                    )
                )
                else not micro_reasons
            )

        correct_direction = a.direction == direction
        ready = (
            a.entry_status == EntryStatus.READY
            or "READY" in a.action
        )
        setup_or_ready = (
            ready
            or a.entry_status == EntryStatus.SETUP
            or "SETUP" in a.action
            or "WATCH" in a.action
        )

        lifecycle = str(
            getattr(a, "trend_lifecycle", "UNFORMED")
            or "UNFORMED"
        )
        gate_text = str(
            getattr(a, "maturity_gate", "")
            or ""
        )
        discovery_state = (
            lifecycle in (
                "EARLY_FORMATION",
                "FIRST_RETEST",
                "CONFIRMED_TREND",
            )
            and "BLOCK_" not in gate_text
            and a.entry_status != EntryStatus.RUNNING
        )

        footprint_gate = str(
            getattr(a, "footprint_gate", "NOT_APPLIED")
            or "NOT_APPLIED"
        )
        direction_gate = str(
            getattr(a, "direction_confirmation_gate", "BLOCK")
            or "BLOCK"
        )
        fatal_footprint_tokens = (
            "LIQUIDATION_UNSAFE",
            "RR_TOO_LOW",
            "MARKET_BIAS_BLOCK",
            "FOOTPRINT_DIRECTION_CONFLICT",
        )
        research_wait_candidate = (
            lab == "SHADOW"
            and bool(
                getattr(
                    self.config,
                    "shadow_allow_wait_discovery",
                    True,
                )
            )
            and a.entry_status == EntryStatus.WAIT
            and direction_gate in ("WATCH", "CONFIRMED")
            and getattr(a, "maturity_gate", "") != "EXHAUSTION"
            and not any(
                token in footprint_gate
                for token in fatal_footprint_tokens
            )
            and opportunity_ok
        )

        state_ok = (
            ready
            if lab == "MAIN"
            else (
                setup_or_ready
                or discovery_state
                or research_wait_candidate
            )
        )

        effective_confidence = thresholds["confidence"]
        effective_entry = thresholds["entry"]
        if research_wait_candidate:
            effective_confidence = float(
                getattr(
                    self.config,
                    "shadow_research_confidence",
                    34.0,
                )
            )
            effective_entry = float(
                getattr(
                    self.config,
                    "shadow_research_entry",
                    35.0,
                )
            )
            reasons.append("SHADOW_DISCOVERY_CANDIDATE")

        if not correct_direction:
            reasons.append("Hướng AI hiện tại không trùng hướng lệnh.")
        if not opportunity_ok:
            reasons.append(
                f"Opportunity #{opportunity_rank}, "
                f"Score {opportunity_score:.1f}; "
                f"yêu cầu Top {rank_limit} và "
                f"Score ≥ {minimum_opportunity:.1f}."
            )
        if not state_ok:
            required = "READY" if lab == "MAIN" else "EARLY/RETEST/SETUP"
            reasons.append(f"Tín hiệu chưa đạt {required}.")
        reasons.extend(micro_reasons)
        if a.confidence_score < effective_confidence:
            reasons.append(
                f"Confidence {a.confidence_score:.0f} "
                f"< {effective_confidence:.0f}."
            )
        if score < effective_entry:
            reasons.append(
                f"Entry Score {score:.0f} < {effective_entry:.0f}."
            )
        if a.risk.risk_score > thresholds["risk"]:
            reasons.append(
                f"Risk {a.risk.risk_score:.0f} > {thresholds['risk']:.0f}."
            )
        liquidation_safe = bool(getattr(a.risk, "liquidation_safe", True))
        if not liquidation_safe:
            reasons.append("Giá thanh lý không an toàn so với invalidation.")
        if a.trade_plan.rr_to_tp2 < thresholds["rr"]:
            reasons.append(
                f"R:R {a.trade_plan.rr_to_tp2:.2f} "
                f"< {thresholds['rr']:.1f}."
            )

        eligible = (
            correct_direction
            and opportunity_ok
            and micro_ok
            and state_ok
            and a.confidence_score >= effective_confidence
            and score >= effective_entry
            and a.risk.risk_score <= thresholds["risk"]
            and a.trade_plan.rr_to_tp2 >= thresholds["rr"]
            and liquidation_safe
        )
        return eligible, reasons



    def _setup_tags(self, a: CoinAnalysis, direction: str) -> str:
        tags = []
        r15 = a.timeframes["15m"]

        if r15.spring:
            tags.append("SPRING")
        if r15.upthrust:
            tags.append("UPTHRUST")

        explanation = " | ".join(a.smart_entry.explanation).upper()
        if "LONG RETEST" in explanation and "20/20" in explanation:
            tags.append("LONG_RETEST")
        elif "LONG RETEST" in explanation and "16/20" in explanation:
            tags.append("LONG_RETEST")
        if "SHORT RETEST" in explanation and "20/20" in explanation:
            tags.append("SHORT_RETEST")
        elif "SHORT RETEST" in explanation and "16/20" in explanation:
            tags.append("SHORT_RETEST")

        if a.smart_entry.fake_breakdown_score >= 55:
            tags.append("FAKE_BREAKDOWN")
        if a.smart_entry.fake_breakout_score >= 55:
            tags.append("FAKE_BREAKOUT")
        if a.smart_entry.absorption_score >= 60:
            tags.append("ABSORPTION")
        if a.smart_entry.weak_hand_score >= 60:
            tags.append("WEAK_HAND")
        if "BULLISH" in a.smart_entry.cmf_rsi_divergence:
            tags.append("BULLISH_DIVERGENCE")
        if "BEARISH" in a.smart_entry.cmf_rsi_divergence:
            tags.append("BEARISH_DIVERGENCE")

        if a.structure.wyckoff_score >= 60:
            tags.append("WYCKOFF_STRONG")
        if a.structure.liquidity_score >= 60:
            tags.append("LIQUIDITY_EVENT")

        sweep_state = str(
            getattr(a.structure, "sweep_volume_state", "NONE") or "NONE"
        )
        if sweep_state != "NONE":
            tags.append(f"SWEEP_{sweep_state}")

        structure_test = str(
            getattr(a.structure, "wyckoff_test", "NONE") or "NONE"
        )
        if structure_test == "TEST AFTER SPRING":
            tags.append("STRUCT_TEST_AFTER_SPRING")
        elif structure_test == "TEST AFTER UPTHRUST":
            tags.append("STRUCT_TEST_AFTER_UPTHRUST")

        if getattr(a.trade_plan, "plan_repaired", False):
            tags.append("PLAN_REPAIRED")

        rank = int(getattr(a, "opportunity_rank", 999))
        if rank < 999:
            tags.append(f"OPPORTUNITY_TOP_{rank}")
        footprint_score = float(getattr(a, "footprint_score", 0.0))
        position_score = float(getattr(a, "position_building_score", 0.0))
        depth = str(getattr(a, "footprint_confirmation_depth", "NONE"))
        alignment = str(getattr(a, "footprint_direction_alignment", "NOT_APPLIED"))
        early = float(getattr(a, "early_entry_score", 0.0))
        tags.append(f"FOOTPRINT_SCORE_{int(footprint_score//10)*10}")
        tags.append(f"POSITION_BUILDING_{int(position_score//10)*10}")
        tags.append(f"FOOTPRINT_DEPTH_{depth}")
        tags.append(f"SMART_MONEY_{alignment}")
        footprint_gate = str(
            getattr(a, "footprint_gate", "NOT_APPLIED")
        )
        tags.append(
            "FOOTPRINT_GATE_"
            + footprint_gate.replace(":", "_").replace("|", "_")
        )
        position_regime = str(
            getattr(a, "position_building_regime", "UNKNOWN")
        )
        tags.append(f"POSITION_REGIME_{position_regime}")
        tags.append(
            f"POSITION_PERSISTENCE_{int(float(getattr(a, 'position_persistence_score', 0.0))//10)*10}"
        )
        tags.append(
            f"POSITION_ACCELERATION_{int(float(getattr(a, 'position_acceleration_score', 0.0))//10)*10}"
        )
        tags.append(
            f"POSITION_CONFIDENCE_{int(float(getattr(a, 'position_confidence_score', 0.0))//10)*10}"
        )
        tags.append(
            f"FOOTPRINT_CHAIN_{int(float(getattr(a, 'footprint_chain_completeness', 0.0))//10)*10}"
        )
        for block in getattr(a, "reasoning_hard_blocks", ()):
            tags.append(
                "REASON_BLOCK_"
                + str(block).upper().replace(" ", "_")[:80]
            )
        footprint = getattr(a, "footprint", None)
        component_scores = getattr(footprint, "component_scores", {}) if footprint else {}
        tags.append(f"OB_SCORE_{int(float(component_scores.get('order_block', 0))//10)*10}")
        tags.append(f"FVG_SCORE_{int(float(component_scores.get('fvg', 0))//10)*10}")
        tags.append(f"BOS_SCORE_{int(float(component_scores.get('bos_choch', 0))//10)*10}")
        tags.append(f"LIQ_SCORE_{int(float(component_scores.get('liquidity_sweep', 0))//10)*10}")
        tags.append("EARLY_ENTRY_HIGH" if early >= 70 else "EARLY_ENTRY_LOW" if early < 40 else "EARLY_ENTRY_MEDIUM")

        score = float(getattr(a, "opportunity_score", 0.0))
        micro = getattr(a, "microstructure", None)
        if micro is not None:
            tags.append(
                f"MICRO_{getattr(a, 'microstructure_gate', 'OBSERVE')}"
            )
            if micro.composite_operator_score >= 70:
                tags.append("MICRO_COS_HIGH")
            elif micro.composite_operator_score < 48:
                tags.append("MICRO_COS_LOW")
        if score >= 75:
            tags.append("OPPORTUNITY_A")
        elif score >= 62:
            tags.append("OPPORTUNITY_B")

        lifecycle = str(
            getattr(a, "trend_lifecycle", "UNFORMED")
            or "UNFORMED"
        )
        tags.append(f"TREND_{lifecycle}")
        maturity = float(
            getattr(a, "trend_maturity_score", 0.0)
        )
        if maturity > 82:
            tags.append("MATURITY_EXHAUSTION")
        elif maturity > 68:
            tags.append("MATURITY_LATE")
        elif maturity >= 48:
            tags.append("MATURITY_CONFIRMED")
        elif maturity >= 22:
            tags.append("MATURITY_EARLY")
        else:
            tags.append("MATURITY_UNFORMED")

        tags.append(f"DIRECTION_{direction}")
        tags.append(f"REGIME_{a.regime.regime}")
        return "|".join(dict.fromkeys(tags))


    def _record_evaluation(
        self,
        a: CoinAnalysis,
        direction: str,
        eligible: bool,
        reasons: list[str],
        source: str,
        lab: str,
    ) -> None:
        score = self._entry_score(a, direction)
        ready = int(
            a.entry_status == EntryStatus.READY
            or "READY" in a.action
        )
        with self._connect() as con:
            con.execute("""
                INSERT INTO signal_evaluations (
                    created_at,symbol,direction,eligible,entry_ready,
                    confidence,entry_score,risk_score,rr_planned,
                    rejection_reasons,source,lab
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                self._now(),
                a.symbol,
                direction,
                int(bool(eligible)),
                ready,
                float(a.confidence_score),
                float(score),
                float(a.risk.risk_score),
                float(a.trade_plan.rr_to_tp2),
                "|".join(reasons),
                source,
                lab.upper(),
            ))


    def _pilot_id(self, lab: str) -> str:
        return (
            self.SHADOW_PILOT_ID
            if lab.upper() == "SHADOW"
            else self.MAIN_PILOT_ID
        )


    def _limit(self, lab: str, direction: str) -> int:
        cfg = self.config
        lab = lab.upper()
        direction = direction.upper()
        if lab == "SHADOW":
            return int(
                getattr(
                    cfg,
                    "shadow_long_limit" if direction == "LONG"
                    else "shadow_short_limit",
                    50,
                )
            )
        return int(
            getattr(
                cfg,
                "main_long_limit" if direction == "LONG"
                else "main_short_limit",
                25,
            )
        )


    def counts(self, lab: str = "MAIN") -> dict[str, int]:
        # Fix: capacity must reflect currently-open slots, not lifetime
        # total. Without this status filter, once `limit` trades of a
        # given direction have EVER been created for a pilot_id+lab
        # (including ones already CLOSED long ago), create_trade() would
        # permanently refuse new trades of that direction, since closed
        # trades were never excluded from the count. This matches the
        # same status set already used for "currently open" elsewhere in
        # this file (has_open_trade(), _diagnostics()).
        with self._connect() as con:
            rows = con.execute("""
                SELECT direction, COUNT(*)
                FROM paper_trades
                WHERE pilot_id=? AND lab=?
                  AND status IN ('PENDING','ACTIVE','TP1_HIT')
                GROUP BY direction
            """, (self._pilot_id(lab), lab.upper())).fetchall()
        result = {"LONG": 0, "SHORT": 0}
        for direction, count in rows:
            result[str(direction)] = int(count)
        return result


    def has_open_trade(
        self,
        symbol: str,
        direction: str,
        lab: str = "MAIN",
    ) -> bool:
        with self._connect() as con:
            row = con.execute("""
                SELECT 1 FROM paper_trades
                WHERE symbol=? AND direction=? AND lab=?
                  AND status IN ('PENDING','ACTIVE','TP1_HIT')
                LIMIT 1
            """, (symbol, direction, lab.upper())).fetchone()
        return row is not None



    @staticmethod
    def _evidence_snapshot(a: CoinAnalysis, direction: str) -> str:
        direction = direction.upper()
        smart_entry_score = float(getattr(
            a.smart_entry,
            "long_opportunity_index" if direction == "LONG" else "short_opportunity_index",
            getattr(a, "long_entry_score" if direction == "LONG" else "short_entry_score", 0.0),
        ))
        market_map = {
            "PASS": 80.0,
            "COUNTERTREND_CONFIRMED": 65.0,
            "DOWNGRADE_OPPOSING": 40.0,
            "BLOCK_OPPOSING_STRONG": 25.0,
        }
        order_quality = 1.0
        footprint = getattr(a, "footprint", None)
        if footprint is not None:
            metadata = getattr(footprint, "metadata", {}) or {}
            try:
                order_quality = float(metadata.get("order_flow_confidence_multiplier", 1.0))
            except (TypeError, ValueError):
                order_quality = 0.0
        if not math.isfinite(order_quality):
            order_quality = 0.0
        order_quality = max(0.0, min(1.0, order_quality))
        order_flow_gate = "UNKNOWN"
        if footprint is not None:
            metadata = getattr(footprint, "metadata", {}) or {}
            order_flow_gate = str(
                metadata.get("order_flow_quality_gate", "UNKNOWN")
            ).upper()
        payload = {
            "TIMING": {"score": float(getattr(a, "early_entry_score", 0.0)), "quality": 1.0, "available": True},
            "ENTRY": {"score": float(smart_entry_score), "quality": 1.0, "available": True},
            "ORDER_FLOW": {"score": float(getattr(a, "footprint_score", 0.0)), "quality": order_quality, "available": footprint is not None},
            "DIRECTION": {"score": float(getattr(a, "direction_confirmation_score", 0.0)), "quality": 1.0, "available": True},
            "MARKET": {"score": float(market_map.get(getattr(a, "market_bias_gate", ""), 40.0)), "quality": 1.0, "available": True},
            "_TRUTH": {
                "schema": "DVS_QUANTUM_TRAINING_V1",
                "calibration_state": str(getattr(
                    a, "probability_calibration_state", "NOT_EVALUATED"
                )).upper(),
                "drift_state": str(getattr(
                    a, "calibration_drift_state", "NOT_EVALUATED"
                )).upper(),
                "order_flow_quality": order_flow_gate,
                "evidence_reliability_state": str(getattr(
                    a, "evidence_reliability_state", "NOT_EVALUATED"
                )).upper(),
            },
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


    def diagnostics(self) -> dict[str, Any]:
        with self._connect() as con:
            active = int(con.execute("""
                SELECT COUNT(*) FROM paper_trades
                WHERE status IN ('PENDING','ACTIVE','TP1_HIT')
            """).fetchone()[0])
            last_created = con.execute("SELECT MAX(created_at) FROM paper_trades").fetchone()[0]
            db_path = str(self.db_path.resolve())
        return {**self._diagnostics, "active_trades": active,
                "last_trade_created_at": last_created, "db_path": db_path}

    def create_trade(
        self,
        a: CoinAnalysis,
        direction: str,
        source: str = "MANUAL",
        enforce_thresholds: bool = True,
        lab: str = "MAIN",
        observation_id: int | None = None,
        candidate_id: str | None = None,
        outcome_id: str | None = None,
        decision_id: str | None = None,
        decision_engine_profile_hash: str | None = None,
        trade_plan_profile_hash: str | None = None,
        require_unified_identity: bool = False,
    ) -> tuple[bool, str]:
        direction = direction.upper()
        lab = lab.upper()
        if require_unified_identity and not all((candidate_id, outcome_id, decision_id)):
            self._diagnostics["gate_blocked"] += 1
            return False, "UNIFIED_IDENTITY_NOT_READY"
        if direction not in ("LONG", "SHORT"):
            self._diagnostics["invalid_direction"] += 1
            return False, "Hướng lệnh không hợp lệ."

        counts = self.counts(lab)
        limit = self._limit(lab, direction)
        if counts[direction] >= limit:
            self._diagnostics["capacity_blocked"] += 1
            return False, f"{lab} đã đủ {limit} lệnh {direction}."

        if self.has_open_trade(a.symbol, direction, lab):
            self._diagnostics["duplicate_blocked"] += 1
            return False, (
                f"{a.symbol} đã có lệnh {direction} {lab} đang mở/chờ."
            )

        eligible, reasons = self.eligibility(a, direction, lab)
        if enforce_thresholds and not eligible:
            self._diagnostics["gate_blocked"] += 1
            return False, "Không đạt ngưỡng: " + " ".join(reasons)

        plan = self.decision_engine._trade_plan(
            direction,
            a.snapshot.last_price,
            a.timeframes["15m"],
        )
        entry_mid = (plan.entry_low + plan.entry_high) / 2.0
        score = self._entry_score(a, direction)
        now = self._now()

        with self._connect() as con:
            cur=con.execute("""
                INSERT INTO paper_trades (
                    pilot_id,lab,created_at,signal_time,symbol,direction,source,status,
                    entry_low,entry_high,planned_entry,invalidation,tp1,tp2,
                    rr_planned,confidence,entry_score,risk_score,
                    smart_money_score,wyckoff_score,regime,phase,oi_state,
                    funding,slippage_rate,setup_tags,note,evidence_snapshot_json,
                    candidate_id,outcome_id,decision_id,
                    decision_engine_profile_hash,trade_plan_profile_hash
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                self._pilot_id(lab),
                lab,
                now,
                a.generated_at,
                a.symbol,
                direction,
                source,
                "PENDING",
                plan.entry_low,
                plan.entry_high,
                entry_mid,
                plan.invalidation,
                plan.tp1,
                plan.tp2,
                plan.rr_to_tp2,
                a.confidence_score,
                score,
                a.risk.risk_score,
                a.smart_entry.smart_money_probability,
                a.structure.wyckoff_score,
                a.regime.regime,
                a.phase_summary,
                a.oi_state,
                a.snapshot.funding_pct,
                float(getattr(self.config, 'paper_slippage_rate', 0.0005)),
                self._setup_tags(a, direction),
                "Paper trade; không đặt lệnh thật.",
                self._evidence_snapshot(a, direction),
                candidate_id, outcome_id, decision_id,
                decision_engine_profile_hash, trade_plan_profile_hash,
            ))
            paper_trade_id=int(cur.lastrowid)
        self._diagnostics["created"] += 1
        if self.observation_runtime is not None:
            self.observation_runtime.bind_trade(observation_id, paper_trade_id)
        return True, (
            f"Đã tạo lệnh {lab} {direction} cho {a.symbol}."
        )


    def auto_consider_shadow_only(
        self,
        a: CoinAnalysis,
        unified_identity=None,
        *,
        source: str = "AUTO_SHADOW_RECOVERY",
    ) -> tuple[bool, str]:
        """Evaluate and create SHADOW only; MAIN is never considered here.

        This recovery path is used when the GUI scan has no live-capture
        identity submission. It remains PAPER-only and cannot create MAIN.
        """
        direction = a.direction
        self._diagnostics["evaluated"] += 1
        identity = {
            "candidate_id": getattr(
                unified_identity,
                "candidate_id",
                None,
            ),
            "outcome_id": getattr(
                unified_identity,
                "outcome_id",
                None,
            ),
            "decision_id": getattr(
                unified_identity,
                "decision_id",
                None,
            ),
            "decision_engine_profile_hash": getattr(
                unified_identity,
                "decision_engine_profile_hash",
                None,
            ),
            "trade_plan_profile_hash": getattr(
                unified_identity,
                "trade_plan_profile_hash",
                None,
            ),
            "require_unified_identity": unified_identity is not None,
        }

        shadow_ok, shadow_reasons = self.eligibility(
            a,
            direction,
            lab="SHADOW",
        )
        if shadow_ok:
            self._diagnostics["shadow_eligible"] += 1

        observation_id = None
        if self.observation_runtime is not None:
            observation_id = self.observation_runtime.record_pair(
                a,
                direction=direction,
                main_ok=False,
                shadow_ok=shadow_ok,
                main_reasons=[
                    "MAIN_NOT_EVALUATED_SHADOW_ONLY_RECOVERY"
                ],
                shadow_reasons=shadow_reasons,
            )

        self._record_evaluation(
            a,
            direction,
            shadow_ok,
            shadow_reasons,
            source=str(source),
            lab="SHADOW",
        )
        if shadow_ok:
            return self.create_trade(
                a,
                direction,
                source=str(source),
                enforce_thresholds=True,
                lab="SHADOW",
                observation_id=observation_id,
                **identity,
            )

        self._diagnostics["gate_blocked"] += 1
        return False, "Không đạt ngưỡng Shadow Paper."

    def auto_consider(self, a: CoinAnalysis, unified_identity=None) -> tuple[bool, str]:
        direction = a.direction
        self._diagnostics["evaluated"] += 1
        identity = {
            "candidate_id": getattr(unified_identity, "candidate_id", None),
            "outcome_id": getattr(unified_identity, "outcome_id", None),
            "decision_id": getattr(unified_identity, "decision_id", None),
            "decision_engine_profile_hash": getattr(unified_identity, "decision_engine_profile_hash", None),
            "trade_plan_profile_hash": getattr(unified_identity, "trade_plan_profile_hash", None),
            "require_unified_identity": unified_identity is not None,
        }

        main_ok, main_reasons = self.eligibility(a, direction, lab="MAIN")
        shadow_ok, shadow_reasons = self.eligibility(a, direction, lab="SHADOW")
        if main_ok:
            self._diagnostics["main_eligible"] += 1
        if shadow_ok:
            self._diagnostics["shadow_eligible"] += 1
        observation_id = None
        if self.observation_runtime is not None:
            observation_id = self.observation_runtime.record_pair(
                a, direction=direction, main_ok=main_ok, shadow_ok=shadow_ok,
                main_reasons=main_reasons, shadow_reasons=shadow_reasons,
            )

        self._record_evaluation(a,direction,main_ok,main_reasons,source="AUTO",lab="MAIN")
        self._record_evaluation(a,direction,shadow_ok,shadow_reasons,source="AUTO",lab="SHADOW")
        if main_ok:
            return self.create_trade(a,direction,source="AUTO_MAIN",enforce_thresholds=True,lab="MAIN",observation_id=observation_id,**identity)
        if shadow_ok:
            return self.create_trade(
                a,direction,source=("AUTO_SHADOW_DISCOVERY" if a.entry_status == EntryStatus.WAIT else "AUTO_SHADOW"),
                enforce_thresholds=True,lab="SHADOW",observation_id=observation_id,**identity,
            )
        self._diagnostics["gate_blocked"] += 1
        return False, "Không đạt ngưỡng Main hoặc Shadow Paper."




    def _fetch_candles_chunked(
        self,
        symbol: str,
        since_text: str,
        *,
        cancel_event: threading.Event | None = None,
        deadline_monotonic=None,
    ) -> list[list[Any]]:
        chunk = int(getattr(self.config, "paper_fetch_chunk", 1000))
        max_chunks = int(getattr(self.config, "paper_max_chunks", 8))
        since_ms = self._to_ms(since_text)
        def cancellation_requested() -> bool:
            deadline = deadline_monotonic() if callable(deadline_monotonic) else deadline_monotonic
            return bool((cancel_event is not None and cancel_event.is_set()) or
                        (deadline is not None and time.monotonic() >= float(deadline)))

        output = []
        for _ in range(max_chunks):
            if cancellation_requested():
                raise InterruptedError("paper trade candle fetch cancelled during shutdown")
            candles = self.provider.exchange.fetch_ohlcv(
                symbol, timeframe="1m", since=since_ms, limit=chunk
            )
            if cancellation_requested():
                raise InterruptedError("paper trade candle fetch cancelled after provider call")
            if not candles:
                break
            output.extend(candles)
            if len(candles) < chunk:
                break
            next_since = int(candles[-1][0]) + 1
            if next_since <= since_ms:
                break
            since_ms = next_since
        return output


    def _sync_unified_lifecycle(
        self, con: sqlite3.Connection, *, trade_id: int, candidate_id: str | None,
        outcome_id: str | None, current_status: str, result: str | None,
        event_time: str | None, fill_time: str | None, fill_price: float | None,
        close_price: float | None, realized_r: float, mfe_r: float, mae_r: float,
        detail: str | None,
    ) -> None:
        """Project a directly-bound Paper lifecycle into Unified Outcome atomically.

        New automatic trades are required to carry exact IDs.  Unbound legacy
        rows are intentionally left untouched and must be handled by an audited
        migration, never by fuzzy runtime matching.
        """
        if not candidate_id or not outcome_id:
            return
        identity = con.execute(
            """SELECT c.candidate_id,o.outcome_id FROM decision_candidates c
               JOIN candidate_outcomes o ON o.candidate_id=c.candidate_id
               WHERE c.candidate_id=? AND o.outcome_id=?""",
            (candidate_id, outcome_id),
        ).fetchone()
        if identity is None:
            raise RuntimeError("PAPER_UNIFIED_IDENTITY_MISMATCH")

        now = self._now()
        event_type = "TRACKING_UPDATED"
        candidate_status = "WAITING_ENTRY"
        outcome_status = "PENDING"
        outcome_time = None
        outcome_price = None
        outcome_detail = detail or current_status

        if current_status == "ACTIVE":
            candidate_status = "ACTIVE"
            event_type = "ENTRY_FILLED"
        elif current_status == "TP1_HIT":
            candidate_status = "TP1_HIT"
            event_type = "TP1_HIT"
        elif current_status == "CLOSED":
            normalized = str(result or "").upper()
            outcome_time = event_time or now
            outcome_price = close_price
            if normalized == "TP2" or realized_r > 0:
                candidate_status = outcome_status = "WIN"
                event_type = "RESOLVED_WIN"
            elif normalized in {"STOP", "PARTIAL_STOP"} or realized_r < 0:
                candidate_status = outcome_status = "LOSS"
                event_type = "RESOLVED_LOSS"
            elif normalized == "EXPIRED":
                candidate_status = outcome_status = "EXPIRED_UNFILLED"
                event_type = "RESOLVED_EXPIRED_UNFILLED"
            elif normalized in {"AMBIGUOUS", "PARTIAL_AMBIGUOUS"}:
                candidate_status = outcome_status = "AMBIGUOUS"
                event_type = "RESOLVED_AMBIGUOUS"
            else:
                candidate_status = outcome_status = "BREAKEVEN"
                event_type = "RESOLVED_BREAKEVEN"

        con.execute(
            """UPDATE decision_candidates SET status=?,
                   fill_time=COALESCE(?,fill_time),fill_price=COALESCE(?,fill_price),
                   expiration_reason=CASE WHEN ?='EXPIRED_UNFILLED' THEN 'PAPER_EXPIRED' ELSE expiration_reason END
               WHERE candidate_id=?""",
            (candidate_status, fill_time, fill_price, candidate_status, candidate_id),
        )
        con.execute(
            """UPDATE candidate_outcomes SET status=?,outcome_detail=?,outcome_time=?,
                   outcome_price=?,realized_r=?,mfe_r=?,mae_r=?,
                   resolution_claim_id=NULL,resolution_claimed_at=NULL,
                   resolver_version='PAPER_LIFECYCLE_BRIDGE_V1',updated_at=?
               WHERE outcome_id=?""",
            (outcome_status, outcome_detail, outcome_time, outcome_price,
             realized_r, mfe_r, mae_r, now, outcome_id),
        )
        con.execute(
            """INSERT OR IGNORE INTO candidate_outcome_events(
                   event_id,candidate_id,outcome_id,event_type,event_time,price,
                   realized_r,mfe_r,mae_r,detail,resolver_version,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (uuid4().hex, candidate_id, outcome_id, event_type,
             event_time or fill_time or now,
             outcome_price if outcome_price is not None else fill_price,
             realized_r, mfe_r, mae_r,
             f"PAPER_TRADE_ID={trade_id};{outcome_detail}",
             "PAPER_LIFECYCLE_BRIDGE_V1", now),
        )

    def update_open_trades(self, limit: int | None = None,
                           cancel_event: threading.Event | None = None,
                           deadline_monotonic=None) -> dict[str, int]:
        limit = int(
            limit or getattr(self.config, "paper_update_limit", 200)
        )
        with self._connect() as con:
            rows = con.execute("""
                SELECT id,created_at,symbol,direction,status,
                       entry_low,entry_high,planned_entry,fill_price,fill_time,
                       invalidation,tp1,tp2,
                       COALESCE(tp1_realized_r,0),tp1_hit_time,
                       last_checked_at,COALESCE(slippage_rate,0),
                   COALESCE(realized_slippage_rate,0),outcome_detail,
                   candidate_id,outcome_id,decision_id,
                   decision_engine_profile_hash,trade_plan_profile_hash
                FROM paper_trades
                WHERE status IN ('PENDING','ACTIVE','TP1_HIT')
                ORDER BY COALESCE(last_checked_at,created_at) ASC
                LIMIT ?
            """, (limit,)).fetchall()

        stats = {"checked": 0, "updated": 0, "errors": 0, "expired": 0}

        def cancellation_requested() -> bool:
            deadline = deadline_monotonic() if callable(deadline_monotonic) else deadline_monotonic
            return bool((cancel_event is not None and cancel_event.is_set()) or
                        (deadline is not None and time.monotonic() >= float(deadline)))

        for row in rows:
            if cancellation_requested():
                raise InterruptedError("paper trade update cancelled during shutdown")
            stats["checked"] += 1
            try:
                result = self._update_one(
                    row, cancel_event=cancel_event, deadline_monotonic=deadline_monotonic
                )
                stats["updated"] += 1
                if result == "EXPIRED":
                    stats["expired"] += 1
            except InterruptedError:
                raise
            except Exception:
                stats["errors"] += 1
        return stats


    def _update_one(self, row: tuple, *, cancel_event: threading.Event | None = None,
                    deadline_monotonic=None) -> str | None:
        def cancellation_requested() -> bool:
            deadline = deadline_monotonic() if callable(deadline_monotonic) else deadline_monotonic
            return bool((cancel_event is not None and cancel_event.is_set()) or
                        (deadline is not None and time.monotonic() >= float(deadline)))

        if cancellation_requested():
            raise InterruptedError("paper trade update cancelled before row processing")

        legacy_row = len(row) == 15
        if legacy_row:
            (
                trade_id, created_at, symbol, direction, status,
                entry_low, entry_high, planned_entry, fill_price, fill_time,
                invalidation, tp1, tp2,
                stored_tp1_realized_r, tp1_hit_time,
            ) = row
            last_checked_at = None
            slippage_rate = 0.0
            realized_slippage_rate = 0.0
            stored_outcome_detail = None
            candidate_id = outcome_id = decision_id = None
            decision_engine_profile_hash = trade_plan_profile_hash = None
        elif len(row) == 17:
            (
                trade_id, created_at, symbol, direction, status,
                entry_low, entry_high, planned_entry, fill_price, fill_time,
                invalidation, tp1, tp2,
                stored_tp1_realized_r, tp1_hit_time,
                last_checked_at, slippage_rate,
            ) = row
            realized_slippage_rate = 0.0
            stored_outcome_detail = None
            candidate_id = outcome_id = decision_id = None
            decision_engine_profile_hash = trade_plan_profile_hash = None
        else:
            (
                trade_id, created_at, symbol, direction, status,
                entry_low, entry_high, planned_entry, fill_price, fill_time,
                invalidation, tp1, tp2,
                stored_tp1_realized_r, tp1_hit_time,
                last_checked_at, slippage_rate,
                realized_slippage_rate, stored_outcome_detail,
                candidate_id, outcome_id, decision_id,
                decision_engine_profile_hash, trade_plan_profile_hash,
            ) = row


        expiry_days = int(
            getattr(self.config, "paper_trade_expiry_days", 7)
        )
        created_dt = datetime.strptime(
            created_at, "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=timezone.utc)
        if (
            not legacy_row
            and (datetime.now(timezone.utc) - created_dt).days >= expiry_days
        ):
            with self._connect() as con:
                con.execute("""
                    UPDATE paper_trades
                    SET status='CLOSED', result='EXPIRED',
                        closed_at=?, last_checked_at=?
                    WHERE id=?
                """, (self._now(), self._now(), trade_id))
                self._sync_unified_lifecycle(
                    con, trade_id=trade_id, candidate_id=candidate_id, outcome_id=outcome_id,
                    current_status="CLOSED", result="EXPIRED", event_time=self._now(),
                    fill_time=fill_time, fill_price=fill_price, close_price=None, realized_r=0.0,
                    mfe_r=0.0, mae_r=0.0, detail="PAPER_EXPIRED",
                )
            if self.observation_runtime is not None:
                self.observation_runtime.close_trade(trade_id, 0.0, result="EXPIRED", closed_at=self._now())
            return "EXPIRED"

        since = last_checked_at or fill_time or created_at
        candles = self._fetch_candles_chunked(
            symbol, since, cancel_event=cancel_event, deadline_monotonic=deadline_monotonic
        )
        if not candles:
            return None

        current_status = status
        fill = float(fill_price) if fill_price is not None else None
        fill_ts = fill_time
        max_favorable = 0.0
        max_adverse = 0.0
        result = None
        tp1_realized_r = float(stored_tp1_realized_r or 0.0)
        r_multiple = tp1_realized_r
        tp1_ts = tp1_hit_time
        close_price = None
        closed_at = None
        last_seen = since
        outcome_detail = stored_outcome_detail

        for ts, o, h, l, c, v in candles:
            if cancellation_requested():
                raise InterruptedError("paper trade update cancelled during candle evaluation")
            h, l, c = float(h), float(l), float(c)
            ts_text = datetime.fromtimestamp(
                ts / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S")
            last_seen = ts_text

            if current_status == "PENDING":
                intersects = l <= float(entry_high) and h >= float(entry_low)
                if not intersects:
                    continue

                raw_fill = min(max(float(planned_entry), l), h)
                base_slip = float(slippage_rate or 0.0)
                if bool(
                    getattr(
                        self.config,
                        "paper_slippage_randomized",
                        True,
                    )
                ):
                    stddev = float(
                        getattr(
                            self.config,
                            "paper_slippage_stddev",
                            0.00025,
                        )
                    )
                    rng = random.Random(
                        f"{trade_id}:{symbol}:{direction}"
                    )
                    realized_slippage_rate = max(
                        0.0,
                        min(
                            base_slip * 3.0 + stddev,
                            rng.gauss(base_slip, stddev),
                        ),
                    )
                else:
                    realized_slippage_rate = base_slip

                fill = (
                    raw_fill * (1.0 + realized_slippage_rate)
                    if direction == "LONG"
                    else raw_fill * (1.0 - realized_slippage_rate)
                )
                fill_ts = ts_text
                current_status = "ACTIVE"

                if direction == "LONG":
                    both = l <= float(invalidation) and h >= float(tp1)
                else:
                    both = h >= float(invalidation) and l <= float(tp1)
                if both:
                    result = "AMBIGUOUS"
                    outcome_detail = "AMBIGUOUS_ENTRY_CANDLE"
                    current_status = "CLOSED"
                    r_multiple = 0.0
                    closed_at = ts_text
                    close_price = c
                    break

            if current_status not in ("ACTIVE", "TP1_HIT") or fill is None:
                continue

            risk = max(abs(fill - float(invalidation)), 1e-12)
            tp1_r_full = abs(float(tp1)-fill) / risk
            tp2_r_full = abs(float(tp2)-fill) / risk

            if direction == "LONG":
                max_favorable = max(max_favorable, (h-fill)/risk)
                max_adverse = min(max_adverse, (l-fill)/risk)
                stop_hit = l <= float(invalidation)
                tp1_hit = h >= float(tp1)
                tp2_hit = h >= float(tp2)
            else:
                max_favorable = max(max_favorable, (fill-l)/risk)
                max_adverse = min(max_adverse, (fill-h)/risk)
                stop_hit = h >= float(invalidation)
                tp1_hit = l <= float(tp1)
                tp2_hit = l <= float(tp2)

            if current_status == "TP1_HIT":
                if stop_hit and tp2_hit:
                    result = "PARTIAL_AMBIGUOUS"
                    outcome_detail = "AMBIGUOUS_AFTER_TP1"
                    current_status = "CLOSED"
                    r_multiple = tp1_realized_r
                    close_price = c
                    closed_at = ts_text
                    break
                if stop_hit:
                    result = "PARTIAL_STOP"
                    current_status = "CLOSED"
                    r_multiple = tp1_realized_r - self.RUNNER_FRACTION
                    close_price = float(invalidation)
                    closed_at = ts_text
                    break
                if tp2_hit:
                    result = "TP2"
                    current_status = "CLOSED"
                    r_multiple = (
                        tp1_realized_r + self.RUNNER_FRACTION * tp2_r_full
                    )
                    close_price = float(tp2)
                    closed_at = ts_text
                    break
                continue

            if stop_hit and (tp1_hit or tp2_hit):
                result = "AMBIGUOUS"
                outcome_detail = "AMBIGUOUS_ACTIVE_CANDLE"
                current_status = "CLOSED"
                r_multiple = 0.0
                close_price = c
                closed_at = ts_text
                break
            if stop_hit:
                result = "STOP"
                current_status = "CLOSED"
                r_multiple = -1.0
                close_price = float(invalidation)
                closed_at = ts_text
                break
            if tp2_hit:
                tp1_realized_r = self.TP1_CLOSE_FRACTION * tp1_r_full
                tp1_ts = tp1_ts or ts_text
                result = "TP2"
                current_status = "CLOSED"
                r_multiple = (
                    tp1_realized_r + self.RUNNER_FRACTION * tp2_r_full
                )
                close_price = float(tp2)
                closed_at = ts_text
                break
            if tp1_hit:
                current_status = "TP1_HIT"
                tp1_realized_r = self.TP1_CLOSE_FRACTION * tp1_r_full
                tp1_ts = tp1_ts or ts_text
                r_multiple = tp1_realized_r

        with self._connect() as con:
            con.execute("""
                UPDATE paper_trades
                SET status=?, fill_price=?, fill_time=?,
                    mfe_r=MAX(COALESCE(mfe_r,0),?),
                    mae_r=MIN(COALESCE(mae_r,0),?),
                    result=COALESCE(?,result),
                    r_multiple=?, tp1_realized_r=?,
                    tp1_hit_time=COALESCE(?,tp1_hit_time),
                    closed_at=COALESCE(?,closed_at),
                    close_price=COALESCE(?,close_price),
                    last_checked_at=?,
                    realized_slippage_rate=?,
                    outcome_detail=COALESCE(?,outcome_detail)
                WHERE id=?
            """, (
                current_status,
                fill,
                fill_ts,
                max_favorable,
                max_adverse,
                result,
                r_multiple,
                tp1_realized_r,
                tp1_ts,
                closed_at,
                close_price,
                last_seen,
                realized_slippage_rate,
                outcome_detail,
                trade_id,
            ))
            self._sync_unified_lifecycle(
                con, trade_id=trade_id, candidate_id=candidate_id, outcome_id=outcome_id,
                current_status=current_status, result=result, event_time=closed_at or tp1_ts or fill_ts or last_seen,
                fill_time=fill_ts, fill_price=fill, close_price=close_price, realized_r=r_multiple,
                mfe_r=max_favorable, mae_r=abs(max_adverse), detail=outcome_detail or result or current_status,
            )
        if result is not None and current_status == "CLOSED" and self.observation_runtime is not None:
            self.observation_runtime.close_trade(trade_id, r_multiple, result=result, closed_at=closed_at)
        return result

    def latest(self, limit: int = 100) -> list[tuple]:
        with self._connect() as con:
            return con.execute("""
                SELECT id,lab,created_at,symbol,direction,source,status,
                       entry_low,entry_high,fill_price,invalidation,tp1,tp2,
                       confidence,entry_score,risk_score,result,r_multiple,
                       mfe_r,mae_r,outcome_detail,
                       realized_slippage_rate
                FROM paper_trades
                ORDER BY id DESC LIMIT ?
            """, (int(limit),)).fetchall()

    def statistics(self, lab: str = "MAIN") -> dict[str, float]:
        lab = lab.upper()
        with self._connect() as con:
            row = con.execute("""
                SELECT
                    COUNT(*),
                    SUM(CASE WHEN direction='LONG' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN direction='SHORT' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN status='CLOSED' THEN 1 ELSE 0 END),
                    SUM(
                        CASE
                            WHEN status='CLOSED' AND r_multiple>0
                            THEN 1 ELSE 0
                        END
                    ),
                    SUM(
                        CASE
                            WHEN status='CLOSED' AND r_multiple<0
                            THEN 1 ELSE 0
                        END
                    ),
                    SUM(
                        CASE
                            WHEN status='CLOSED' AND r_multiple=0
                            THEN 1 ELSE 0
                        END
                    ),
                    COALESCE(
                        AVG(
                            CASE
                                WHEN status='CLOSED'
                                THEN r_multiple
                            END
                        ),0
                    ),
                    COALESCE(
                        SUM(
                            CASE
                                WHEN r_multiple>0
                                THEN r_multiple ELSE 0
                            END
                        ),0
                    ),
                    ABS(
                        COALESCE(
                            SUM(
                                CASE
                                    WHEN r_multiple<0
                                    THEN r_multiple ELSE 0
                                END
                            ),0
                        )
                    ),
                    SUM(
                        CASE
                            WHEN result IN ('AMBIGUOUS','PARTIAL_AMBIGUOUS')
                            THEN 1 ELSE 0
                        END
                    ),
                    SUM(
                        CASE WHEN result='EXPIRED'
                        THEN 1 ELSE 0 END
                    )
                FROM paper_trades
                WHERE pilot_id=? AND lab=?
            """, (self._pilot_id(lab), lab)).fetchone()

        closed = int(row[3] or 0)
        wins = int(row[4] or 0)
        gross_win = float(row[8] or 0.0)
        gross_loss = float(row[9] or 0.0)
        ambiguous = int(row[10] or 0)
        expired = int(row[11] or 0)
        determinate = max(0, closed - ambiguous - expired)

        if gross_loss > 0:
            profit_factor = gross_win / gross_loss
        elif gross_win > 0:
            profit_factor = float("inf")
        else:
            profit_factor = 0.0

        return {
            "total": int(row[0] or 0),
            "longs": int(row[1] or 0),
            "shorts": int(row[2] or 0),
            "closed": closed,
            "wins": wins,
            "losses": int(row[5] or 0),
            "breakeven": int(row[6] or 0),
            "win_rate": (
                wins / determinate * 100.0 if determinate else 0.0
            ),
            "avg_r": float(row[7] or 0.0),
            "profit_factor": profit_factor,
            "ambiguous": ambiguous,
            "expired": expired,
            "determinate": determinate,
        }
