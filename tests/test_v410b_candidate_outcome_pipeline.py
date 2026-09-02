from __future__ import annotations
from datetime import datetime, timezone
import sqlite3

from dvs_ai.services.candidate_outcome_resolver import CandidateOutcomeResolver
from dvs_ai.services.outcome_infrastructure import OutcomeInfrastructureStore
from dvs_ai.services.setup_episode_service import EvaluationCapture, SetupEpisodeService


def ms(text):
    return int(datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()*1000)

class Exchange:
    def __init__(self, candles): self.candles=candles
    def fetch_ohlcv(self, symbol, timeframe, since, limit):
        assert timeframe == "1m"
        return [c for c in self.candles if c[0] >= since][:limit]
class Provider:
    def __init__(self,candles): self.exchange=Exchange(candles)

def candidate(store, ts="2026-07-20 10:00:00"):
    service=SetupEpisodeService(store)
    _, cid=service.capture(EvaluationCapture(symbol="BTCUSDT",direction="LONG",evaluated_at=ts,
        entry_score=60,confidence=55,opportunity_score=60,gate_set=("CONFIDENCE_LT_68",),
        decision_engine_profile_hash="d"*64,level=100,atr_15m=2,lifecycle="EARLY_FORMATION",
        entry_low=99,entry_high=100,invalidation=98,tp1=102,tp2=104,evaluation_id="e1"))
    return cid

def test_waiting_entry_then_target_resolves_win(tmp_path):
    store=OutcomeInfrastructureStore(tmp_path/'p.db'); cid=candidate(store)
    candles=[[ms("2026-07-20 10:01:00"),101,101,100.5,100.8,1],
             [ms("2026-07-20 10:02:00"),100.5,100.6,99.5,100,1],
             [ms("2026-07-20 10:03:00"),100,104.2,99.8,104,1]]
    result=CandidateOutcomeResolver(Provider(candles),store).resolve_pending()
    assert result["updated"] == 1
    with store.connect() as con:
        assert con.execute("select status from candidate_outcomes where candidate_id=?",(cid,)).fetchone()[0] == "WIN"
        assert con.execute("select status from decision_candidates where candidate_id=?",(cid,)).fetchone()[0] == "WIN"

def test_invalidation_before_entry_is_unfilled_not_loss(tmp_path):
    store=OutcomeInfrastructureStore(tmp_path/'p.db'); cid=candidate(store)
    candles=[[ms("2026-07-20 10:01:00"),98.5,98.5,97.5,98,1]]
    CandidateOutcomeResolver(Provider(candles),store).resolve_pending()
    with store.connect() as con:
        assert con.execute("select status from candidate_outcomes where candidate_id=?",(cid,)).fetchone()[0] == "EXPIRED_UNFILLED"

def test_stale_claim_is_recovered(tmp_path):
    store=OutcomeInfrastructureStore(tmp_path/'p.db'); cid=candidate(store)
    with store.connect() as con:
        con.execute("update candidate_outcomes set status='RESOLVING',resolution_claim_id='old',resolution_claimed_at='2026-07-20 00:00:00' where candidate_id=?",(cid,))
    resolver=CandidateOutcomeResolver(Provider([]),store)
    assert resolver.recover_stale_claims() == 1
    with store.connect() as con:
        assert con.execute("select status from candidate_outcomes where candidate_id=?",(cid,)).fetchone()[0] == "PENDING"

def test_claim_is_single_owner(tmp_path):
    store=OutcomeInfrastructureStore(tmp_path/'p.db'); candidate(store)
    resolver=CandidateOutcomeResolver(Provider([]),store)
    first=resolver._claim_batch(10); second=resolver._claim_batch(10)
    assert len(first)==1 and second==[]
