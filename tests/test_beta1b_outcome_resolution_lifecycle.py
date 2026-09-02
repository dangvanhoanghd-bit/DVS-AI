from __future__ import annotations

from datetime import datetime, timezone

from dvs_ai.services.candidate_outcome_resolver import CandidateOutcomeResolver
from dvs_ai.services.outcome_infrastructure import OutcomeInfrastructureStore
from dvs_ai.services.outcome_intelligence import OutcomeIntelligenceService
from dvs_ai.services.setup_episode_service import EvaluationCapture, SetupEpisodeService


def ms(text: str) -> int:
    return int(datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000)


class Exchange:
    def __init__(self, candles): self.candles = candles
    def fetch_ohlcv(self, symbol, timeframe, since, limit):
        return [c for c in self.candles if c[0] >= since][:limit]


class Provider:
    def __init__(self, candles): self.exchange = Exchange(candles)


def create_candidate(store, *, ts="2026-07-20 10:00:00"):
    service = SetupEpisodeService(store)
    _, cid = service.capture(EvaluationCapture(
        symbol="BTCUSDT", direction="LONG", evaluated_at=ts, entry_score=60,
        confidence=55, opportunity_score=60, gate_set=("CONFIDENCE_LT_68",),
        decision_engine_profile_hash="d" * 64, level=100, atr_15m=2,
        lifecycle="EARLY_FORMATION", entry_low=99, entry_high=100,
        invalidation=98, tp1=102, tp2=104, evaluation_id="e1",
        feature_snapshot={"confidence": 55, "direction": "LONG"},
    ))
    return cid


def test_tp1_is_intermediate_then_tp2_resolves_win_with_timeline(tmp_path):
    store = OutcomeInfrastructureStore(tmp_path / "p.db")
    cid = create_candidate(store)
    first = [[ms("2026-07-20 10:01:00"), 100, 102.2, 99.5, 102, 1]]
    CandidateOutcomeResolver(Provider(first), store).resolve_pending()
    with store.connect() as con:
        assert con.execute("select status from decision_candidates where candidate_id=?", (cid,)).fetchone()[0] == "TP1_HIT"
        assert con.execute("select status from candidate_outcomes where candidate_id=?", (cid,)).fetchone()[0] == "PENDING"
        assert con.execute("select count(*) from candidate_outcome_events where candidate_id=? and event_type='TP1_HIT'", (cid,)).fetchone()[0] == 1

    second = [[ms("2026-07-20 10:02:00"), 102, 104.2, 101.5, 104, 1]]
    CandidateOutcomeResolver(Provider(second), store).resolve_pending()
    with store.connect() as con:
        assert con.execute("select status from candidate_outcomes where candidate_id=?", (cid,)).fetchone()[0] == "WIN"
        events = [r[0] for r in con.execute("select event_type from candidate_outcome_events where candidate_id=? order by event_time", (cid,))]
        assert "TP1_HIT" in events and "TP2_HIT" in events
    assert OutcomeIntelligenceService(store.db_path).maturity_summary().learning_ready == 1


def test_terminal_outcome_is_not_overwritten(tmp_path):
    store = OutcomeInfrastructureStore(tmp_path / "p.db")
    cid = create_candidate(store)
    win = [[ms("2026-07-20 10:01:00"), 100, 104.2, 99.5, 104, 1]]
    CandidateOutcomeResolver(Provider(win), store).resolve_pending()
    loss = [[ms("2026-07-20 10:02:00"), 100, 100.1, 97.5, 98, 1]]
    result = CandidateOutcomeResolver(Provider(loss), store).resolve_pending()
    assert result["checked"] == 0
    with store.connect() as con:
        assert con.execute("select status from candidate_outcomes where candidate_id=?", (cid,)).fetchone()[0] == "WIN"
        assert con.execute("select count(*) from candidate_outcome_events where candidate_id=? and event_type='TP2_HIT'", (cid,)).fetchone()[0] == 1


def test_event_ledger_has_no_duplicate_on_same_resolution_cycle(tmp_path):
    store = OutcomeInfrastructureStore(tmp_path / "p.db")
    cid = create_candidate(store)
    candles = [[ms("2026-07-20 10:01:00"), 100, 104.2, 99.5, 104, 1]]
    resolver = CandidateOutcomeResolver(Provider(candles), store)
    resolver.resolve_pending(); resolver.resolve_pending()
    with store.connect() as con:
        count = con.execute("select count(*) from candidate_outcome_events where candidate_id=? and event_type='TP2_HIT'", (cid,)).fetchone()[0]
    assert count == 1
