from __future__ import annotations

import sqlite3

import pytest

from dvs_ai.services.quantum_data_convergence import (
    EpisodeOutcomeSource,
    OutcomeMappingError,
    PaperTradeSource,
    QuantumDataAdapter,
    map_legacy_outcome,
)
from dvs_ai.services.outcome_infrastructure import OutcomeInfrastructureStore


def _legacy_db(path):
    with sqlite3.connect(path) as con:
        con.execute("""CREATE TABLE paper_trades(
          id INTEGER PRIMARY KEY,pilot_id TEXT,lab TEXT,created_at TEXT,closed_at TEXT,
          symbol TEXT,direction TEXT,status TEXT,result TEXT,r_multiple REAL,
          confidence REAL,entry_score REAL,risk_score REAL,rr_planned REAL)""")
        con.executemany("INSERT INTO paper_trades VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
          (1,'p1','MAIN','2026-01-01','2026-01-02','BTCUSDT','LONG','CLOSED','WIN',1.5,70,65,20,2.0),
          (2,'p2','SHADOW','2026-01-03','2026-01-04','ETHUSDT','SHORT','CLOSED','PARTIAL_AMBIGUOUS',0,60,55,30,1.5),
          (3,'p3','MAIN','2026-01-05',None,'SOLUSDT','LONG','OPEN','OPEN',0,50,50,50,1.2),
        ])


def _episode_db(path):
    store = OutcomeInfrastructureStore(path)
    with store.connect() as con:
        con.execute("""INSERT INTO setup_episodes(
          setup_episode_id,symbol,direction,decision_engine_profile_hash,trade_plan_profile_hash,
          candidate_capture_profile_hash,setup_fingerprint,primary_zone_id,structural_event_id,
          lifecycle_family,status,started_at,last_seen_at,first_evaluation_id,
          activation_evaluation_id,evaluation_count,initial_gate_set,eventually_accepted,candidate_id)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          ('ep1','XRPUSDT','LONG','d','t','c','f',1,'NONE','L','CLOSED','2026-01-01','2026-01-02','ev1','ev1',1,'[]',1,'c1'))
        con.execute("INSERT INTO episode_evaluations VALUES(?,?,?,?,?,?,?,?,?)",
                    ('ep1','ev1',1,'2026-01-01',66,72,70,'[]',1.0))
        con.execute("""INSERT INTO decision_candidates(
          candidate_id,setup_episode_id,activation_evaluation_id,activated_at,cohort,symbol,direction,
          decision_engine_profile_hash,trade_plan_profile_hash,entry_low,entry_high,planned_entry,
          invalidation,tp1,tp2,rr_planned,entry_wait_started_at,entry_expiry_at,status,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          ('c1','ep1','ev1','2026-01-01','CENSUS','XRPUSDT','LONG','d','t',1,2,1.5,1,2,3,2.0,'2026-01-01','2026-01-01','FILLED','2026-01-01'))
        con.execute("""INSERT INTO candidate_outcomes(
          outcome_id,candidate_id,resolver_profile_hash,status,outcome_time,realized_r,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?)""", ('o1','c1','r','LOSS','2026-01-02',-1.0,'2026-01-02','2026-01-02'))


def test_mapping_is_explicit_and_fail_closed():
    assert map_legacy_outcome(status='CLOSED', result='PARTIAL_AMBIGUOUS').unified == 'AMBIGUOUS'
    with pytest.raises(OutcomeMappingError):
        map_legacy_outcome(status='CLOSED', result='PROFIT')
    with pytest.raises(OutcomeMappingError):
        map_legacy_outcome(status='OPEN', result='WIN')


def test_sources_preserve_provenance_and_are_read_only(tmp_path):
    legacy = tmp_path/'legacy.db'; episode = tmp_path/'episode.db'
    _legacy_db(legacy); _episode_db(episode)
    rows = QuantumDataAdapter(PaperTradeSource(legacy), EpisodeOutcomeSource(episode)).read_terminal()
    assert sorted(r.outcome for r in rows) == ['AMBIGUOUS', 'LOSS', 'WIN']
    assert {r.source for r in rows} == {'paper_trades','candidate_outcomes'}
    assert all(r.provenance['mapping_rule_id'] for r in rows)
    with sqlite3.connect(legacy) as con:
        assert con.execute('select count(*) from paper_trades').fetchone()[0] == 3


def test_data_equivalence_for_legacy_reader(tmp_path):
    path = tmp_path/'legacy.db'; _legacy_db(path)
    direct = []
    with sqlite3.connect(path) as con:
        direct = con.execute("SELECT id,result,r_multiple,created_at,closed_at FROM paper_trades WHERE status='CLOSED' ORDER BY created_at,id").fetchall()
    adapted = PaperTradeSource(path).read_terminal()
    assert len(adapted) == len(direct)
    assert [r.source_id for r in adapted] == [str(r[0]) for r in direct]
    assert [r.realized_r for r in adapted] == [float(r[2]) for r in direct]
    assert [r.setup_time for r in adapted] == [r[3] for r in direct]
    assert [r.close_time for r in adapted] == [r[4] for r in direct]


def test_convergence_report_has_no_cross_source_identity_collision(tmp_path):
    legacy = tmp_path/'legacy.db'; episode = tmp_path/'episode.db'
    _legacy_db(legacy); _episode_db(episode)
    adapter = QuantumDataAdapter(PaperTradeSource(legacy), EpisodeOutcomeSource(episode))
    report = adapter.report()
    assert report.total == 3
    assert report.by_source == {'candidate_outcomes': 1, 'paper_trades': 2}
    assert report.by_outcome == {'AMBIGUOUS': 1, 'LOSS': 1, 'WIN': 1}
    assert report.duplicate_identities == ()
