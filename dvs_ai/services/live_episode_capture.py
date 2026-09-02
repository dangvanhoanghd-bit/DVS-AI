from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

from dvs_ai.domain.models import CoinAnalysis
from dvs_ai.services.outcome_infrastructure import (
    OutcomeInfrastructureStore,
    decision_engine_profile_hash,
)
from dvs_ai.services.setup_episode_service import EvaluationCapture, SetupEpisodeService


@dataclass(frozen=True)
class UnifiedCaptureIdentity:
    episode_id: str
    candidate_id: str | None
    created_candidate_id: str | None
    outcome_id: str | None
    decision_id: str | None
    decision_engine_profile_hash: str | None
    trade_plan_profile_hash: str | None

    @property
    def complete(self) -> bool:
        return bool(self.candidate_id and self.outcome_id and self.decision_id)


class LiveEpisodeCapture:
    """Read-only adapter from a completed scan result into episode infrastructure."""

    def __init__(self, store: OutcomeInfrastructureStore, decision_engine: Any, config: Any) -> None:
        self.store = store
        self.episodes = SetupEpisodeService(store)
        self.decision_hash = decision_engine_profile_hash(self._profile_payload(decision_engine, config))

    @staticmethod
    def _profile_payload(decision_engine: Any, config: Any) -> dict[str, Any]:
        config_values = {}
        for key, value in vars(config).items() if hasattr(config, "__dict__") else ():
            if isinstance(value, (str, int, float, bool, type(None), list, tuple, dict)):
                config_values[key] = value
        return {
            "engine_class": type(decision_engine).__name__,
            "weights": dict(getattr(decision_engine, "WEIGHTS", {})),
            "config": config_values,
        }

    @staticmethod
    def _directional_entry(a: CoinAnalysis) -> float:
        return float(a.long_entry_score if a.direction == "LONG" else a.short_entry_score)

    @staticmethod
    def _directional_trend(a: CoinAnalysis) -> float:
        return float(a.long_trend_score if a.direction == "LONG" else a.short_trend_score)

    @staticmethod
    def _gate_set(a: CoinAnalysis) -> tuple[str, ...]:
        gates: set[str] = set(str(x) for x in (a.decision_hard_reasons or ()) if str(x).strip())
        gates.update(str(x) for x in (a.reasoning_hard_blocks or ()) if str(x).strip())
        if a.entry_status.value == "WAIT":
            gates.add("ENTRY_STATUS_WAIT")
        if float(a.risk.risk_score) >= 55.0:
            gates.add("RISK_GE_55")
        if str(a.direction_confirmation_gate).upper() not in {"WATCH", "CONFIRMED", "PASS"}:
            gates.add(f"DIRECTION_CONFIRMATION_{str(a.direction_confirmation_gate).upper()}")
        if str(a.microstructure_gate).upper() in {"BLOCK", "CONFLICT", "REJECT", "FAILED"}:
            gates.add(f"MICROSTRUCTURE_{str(a.microstructure_gate).upper()}")
        return tuple(sorted(gates))

    @staticmethod
    def _trace(a: CoinAnalysis, gate_set: tuple[str, ...]) -> dict[str, Any]:
        tf15 = a.timeframes["15m"]
        return {
            "schema_version": "live-evaluation-trace-v1",
            "symbol": a.symbol,
            "evaluated_at": a.generated_at,
            "direction": a.direction,
            "entry_status": a.entry_status.value,
            "scores": {
                "trend_directional": LiveEpisodeCapture._directional_trend(a),
                "entry_directional": LiveEpisodeCapture._directional_entry(a),
                "long_trend": float(a.long_trend_score),
                "long_entry": float(a.long_entry_score),
                "short_trend": float(a.short_trend_score),
                "short_entry": float(a.short_entry_score),
                "confidence": float(a.confidence_score),
                "smart_money_probability": float(a.smart_entry.smart_money_probability),
                "risk_score": float(a.risk.risk_score),
                "opportunity_score": float(a.opportunity_score),
                "direction_confirmation_score": float(a.direction_confirmation_score),
            },
            "states": {
                "regime": a.regime.regime,
                "lifecycle": a.trend_lifecycle,
                "phase": a.phase_summary,
                "risk_level": a.risk.risk_level,
                "smart_money_state": a.smart_entry.state,
                "direction_confirmation_gate": a.direction_confirmation_gate,
                "opportunity_gate": a.opportunity_gate,
                "microstructure_gate": a.microstructure_gate,
                "market_bias_gate": a.market_bias_gate,
            },
            "structure": {
                "support_15m": float(tf15.support),
                "resistance_15m": float(tf15.resistance),
                "atr_15m": float(tf15.atr),
                "spring": bool(tf15.spring),
                "upthrust": bool(tf15.upthrust),
            },
            "trade_plan": asdict(a.trade_plan),
            "gate_set": list(gate_set),
        }

    def capture_with_identity(self, a: CoinAnalysis) -> UnifiedCaptureIdentity:
        tf15 = a.timeframes["15m"]
        plan = a.trade_plan
        evaluation_id = uuid4().hex
        level = tf15.support if a.direction == "LONG" else tf15.resistance
        gates = self._gate_set(a)
        feature_snapshot = self._trace(a, gates)
        event_type = "SPRING" if tf15.spring else "UPTHRUST" if tf15.upthrust else "NONE"
        episode_id, candidate_id = self.episodes.capture(EvaluationCapture(
            symbol=a.symbol, direction=a.direction, evaluated_at=a.generated_at,
            entry_score=self._directional_entry(a), confidence=float(a.confidence_score),
            opportunity_score=float(a.opportunity_score), gate_set=gates,
            decision_engine_profile_hash=self.decision_hash, level=float(level),
            atr_15m=float(tf15.atr), lifecycle=a.trend_lifecycle, event_type=event_type,
            event_timestamp=None, entry_low=plan.entry_low, entry_high=plan.entry_high,
            invalidation=plan.invalidation, tp1=plan.tp1, tp2=plan.tp2,
            market_data_valid=True, evaluation_id=evaluation_id, feature_snapshot=feature_snapshot,
        ))
        self.store.record_diagnostic_trace(
            evaluation_id=evaluation_id, episode_id=episode_id,
            decision_hash=self.decision_hash, trace=feature_snapshot,
        )
        resolved_candidate_id = candidate_id
        identity = None
        if hasattr(self.store, "connect"):
            with self.store.connect() as con:
                con.row_factory = __import__("sqlite3").Row
                if not resolved_candidate_id:
                    row = con.execute(
                        "SELECT candidate_id FROM setup_episodes WHERE setup_episode_id=?",
                        (episode_id,),
                    ).fetchone()
                    resolved_candidate_id = str(row["candidate_id"]) if row and row["candidate_id"] else None
                if resolved_candidate_id:
                    identity = con.execute("""
                        SELECT c.candidate_id,c.activation_evaluation_id,
                               c.decision_engine_profile_hash,c.trade_plan_profile_hash,
                               o.outcome_id
                        FROM decision_candidates c
                        JOIN candidate_outcomes o ON o.candidate_id=c.candidate_id
                        WHERE c.candidate_id=?
                        ORDER BY o.created_at ASC LIMIT 1
                    """, (resolved_candidate_id,)).fetchone()
        if resolved_candidate_id and identity is None and hasattr(self.store, "connect"):
            raise RuntimeError("CANDIDATE_OUTCOME_IDENTITY_MISSING")
        return UnifiedCaptureIdentity(
            episode_id=str(episode_id), candidate_id=resolved_candidate_id, created_candidate_id=candidate_id,
            outcome_id=str(identity["outcome_id"]) if identity is not None else None,
            decision_id=str(identity["activation_evaluation_id"]) if identity is not None else None,
            decision_engine_profile_hash=str(identity["decision_engine_profile_hash"]) if identity is not None else None,
            trade_plan_profile_hash=str(identity["trade_plan_profile_hash"]) if identity is not None else None,
        )

    def capture(self, a: CoinAnalysis) -> tuple[str, str | None]:
        identity = self.capture_with_identity(a)
        return identity.episode_id, identity.created_candidate_id
