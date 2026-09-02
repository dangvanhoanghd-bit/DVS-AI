from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from uuid import uuid4

from dvs_ai.services.outcome_infrastructure import (
    OutcomeInfrastructureStore, candidate_capture_profile_hash, structural_event_id,
    setup_fingerprint, trade_plan_profile_hash, valid_trade_plan, zone_identity,
    lifecycle_family,
)

@dataclass(frozen=True)
class EvaluationCapture:
    symbol: str
    direction: str
    evaluated_at: str
    entry_score: float
    confidence: float
    opportunity_score: float | None
    gate_set: tuple[str, ...]
    decision_engine_profile_hash: str
    level: float
    atr_15m: float
    lifecycle: str
    event_type: str = "NONE"
    event_timestamp: str | None = None
    entry_low: float | None = None
    entry_high: float | None = None
    invalidation: float | None = None
    tp1: float | None = None
    tp2: float | None = None
    market_data_valid: bool = True
    evaluation_id: str = ""
    feature_snapshot: dict | None = None

class SetupEpisodeService:
    """Groups repeated evaluations into one statistical setup episode."""

    def __init__(self, store: OutcomeInfrastructureStore) -> None:
        self.store = store

    def capture(self, item: EvaluationCapture) -> tuple[str, str | None]:
        evaluation_id = item.evaluation_id or uuid4().hex
        plan_hash = trade_plan_profile_hash()
        zone_id, _ = zone_identity(item.level, item.atr_15m)
        event_id = structural_event_id(event_type=item.event_type,
                                       event_timestamp=item.event_timestamp)
        fingerprint = setup_fingerprint(
            symbol=item.symbol, direction=item.direction, primary_zone_id=zone_id,
            event_id=event_id, lifecycle=item.lifecycle,
            decision_profile_hash=item.decision_engine_profile_hash,
            plan_profile_hash=plan_hash,
        )
        episode = self.store.find_open_episode(
            symbol=item.symbol, direction=item.direction,
            decision_hash=item.decision_engine_profile_hash,
            plan_hash=plan_hash, evaluated_at=item.evaluated_at,
        )
        if episode is None or episode["setup_fingerprint"] != fingerprint:
            episode_id = self.store.create_episode(
                symbol=item.symbol, direction=item.direction,
                decision_engine_profile_hash=item.decision_engine_profile_hash,
                trade_plan_profile_hash=plan_hash,
                candidate_capture_profile_hash=candidate_capture_profile_hash(),
                setup_fingerprint=fingerprint, primary_zone_id=zone_id,
                structural_event_id=event_id, lifecycle_family=lifecycle_family(item.lifecycle),
                evaluated_at=item.evaluated_at, evaluation_id=evaluation_id,
                gate_set=item.gate_set,
            )
            self.store.append_evaluation(
                episode_id=episode_id, evaluation_id=evaluation_id,
                evaluated_at=item.evaluated_at, entry_score=item.entry_score,
                confidence=item.confidence, opportunity_score=item.opportunity_score,
                gate_set=item.gate_set,
            )
        else:
            episode_id = episode["setup_episode_id"]
            self.store.append_evaluation(
                episode_id=episode_id, evaluation_id=evaluation_id,
                evaluated_at=item.evaluated_at, entry_score=item.entry_score,
                confidence=item.confidence, opportunity_score=item.opportunity_score,
                gate_set=item.gate_set,
            )

        candidate_id = None
        if item.market_data_valid and valid_trade_plan(
            direction=item.direction, entry_low=item.entry_low, entry_high=item.entry_high,
            invalidation=item.invalidation, tp1=item.tp1, tp2=item.tp2,
        ):
            with self.store.connect() as con:
                activated = con.execute("SELECT candidate_id FROM setup_episodes WHERE setup_episode_id=?",
                                        (episode_id,)).fetchone()[0]
            if not activated:
                candidate_id = self.store.activate_candidate(
                    episode_id=episode_id, evaluation_id=evaluation_id,
                    activated_at=item.evaluated_at, symbol=item.symbol,
                    direction=item.direction, decision_hash=item.decision_engine_profile_hash,
                    plan_hash=plan_hash, gate_set=item.gate_set,
                    entry_low=float(item.entry_low), entry_high=float(item.entry_high),
                    invalidation=float(item.invalidation), tp1=item.tp1, tp2=item.tp2,
                )
                if item.feature_snapshot:
                    from dvs_ai.services.outcome_intelligence import OutcomeIntelligenceService
                    OutcomeIntelligenceService(self.store.db_path).capture_feature_snapshot(
                        candidate_id=candidate_id,
                        evaluation_id=evaluation_id,
                        features=item.feature_snapshot,
                        source="LIVE_EVALUATION",
                        captured_at=item.evaluated_at,
                    )
        return episode_id, candidate_id
