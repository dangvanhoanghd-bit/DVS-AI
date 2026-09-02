from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta

from dvs_ai.services.integrity_incident_ledger import IntegrityIncidentLedger


def _schema(path):
    con=sqlite3.connect(path)
    con.executescript('''
    CREATE TABLE setup_episodes(setup_episode_id TEXT PRIMARY KEY,status TEXT,last_seen_at TEXT,evaluation_count INTEGER,activation_evaluation_id TEXT,decision_engine_profile_hash TEXT,trade_plan_profile_hash TEXT);
    CREATE TABLE episode_evaluations(evaluation_id TEXT PRIMARY KEY,setup_episode_id TEXT,sequence_number INTEGER);
    CREATE TABLE decision_candidates(candidate_id TEXT PRIMARY KEY,setup_episode_id TEXT,activation_evaluation_id TEXT,decision_engine_profile_hash TEXT,trade_plan_profile_hash TEXT,status TEXT,entry_expiry_at TEXT);
    CREATE TABLE candidate_outcomes(outcome_id TEXT PRIMARY KEY,candidate_id TEXT,status TEXT,resolution_claimed_at TEXT);
    CREATE TABLE decision_diagnostic_traces(evaluation_id TEXT PRIMARY KEY,setup_episode_id TEXT,decision_engine_profile_hash TEXT);
    ''')
    con.commit(); return con


def test_ledger_new_resolved_and_reopened(tmp_path):
    source=tmp_path/'source.db'; ledger=tmp_path/'ledger.db'; now=datetime(2026,7,21,tzinfo=timezone.utc)
    con=_schema(source)
    con.execute("INSERT INTO setup_episodes VALUES(?,?,?,?,?,?,?)",('ep1','OPEN',(now-timedelta(hours=3)).isoformat(),0,None,'de','tp'))
    con.commit(); con.close()
    svc=IntegrityIncidentLedger(source,ledger)
    first=svc.capture(now=now)
    assert first['open_incident_count']==1
    assert len(first['transitions']['new'])==1

    con=sqlite3.connect(source); con.execute("UPDATE setup_episodes SET last_seen_at=? WHERE setup_episode_id='ep1'",(now.isoformat(),)); con.commit(); con.close()
    second=svc.capture(now=now+timedelta(minutes=1))
    assert second['open_incident_count']==0
    assert second['resolved_incident_count']==1
    assert len(second['transitions']['resolved'])==1

    con=sqlite3.connect(source); con.execute("UPDATE setup_episodes SET last_seen_at=? WHERE setup_episode_id='ep1'",((now-timedelta(hours=4)).isoformat(),)); con.commit(); con.close()
    third=svc.capture(now=now+timedelta(minutes=2))
    assert third['open_incident_count']==1
    assert len(third['transitions']['reopened'])==1
    incident=third['incidents'][0]
    assert incident['recurrence_count']==1
    assert incident['occurrence_count']==2


def test_ledger_identity_ignores_detail_changes(tmp_path):
    source=tmp_path/'source.db'; ledger=tmp_path/'ledger.db'; now=datetime(2026,7,21,tzinfo=timezone.utc)
    con=_schema(source)
    con.execute("INSERT INTO setup_episodes VALUES(?,?,?,?,?,?,?)",('ep1','OPEN',(now-timedelta(hours=3)).isoformat(),0,None,'de','tp'))
    con.commit(); con.close()
    svc=IntegrityIncidentLedger(source,ledger)
    svc.capture(now=now)
    later=svc.capture(now=now+timedelta(minutes=10))
    assert later['open_incident_count']==1
    assert len(later['transitions']['ongoing'])==1
    assert later['incidents'][0]['occurrence_count']==2
