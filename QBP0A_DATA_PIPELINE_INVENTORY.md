# QBP-0A Data Pipeline Inventory

Generated from the actual Python source tree. Classification is lexical and each reference remains listed for manual audit.

## `paper_trades`

### `dvs_ai/app.py`
- L54 **REFERENCE** — `paper_db_path = "data/dvs_paper_trades.db"`

### `dvs_ai/services/adaptive_confidence_service.py`
- L33 **REFERENCE** — `db_path: str = "data/dvs_paper_trades.db",`
- L67 **READ** — `FROM paper_trades`

### `dvs_ai/services/calibration_drift_monitor.py`
- L40 **REFERENCE** — `db_path: str = "data/dvs_paper_trades.db",`
- L77 **READ** — `FROM paper_trades`

### `dvs_ai/services/candidate_evidence_service.py`
- L79 **REFERENCE** — `self.lifecycle = CandidateLifecycleStore(str(self.data_dir / "dvs_paper_trades.db"))`
- L80 **REFERENCE** — `self.performance = HistoricalCandidateStore(str(self.data_dir / "dvs_paper_trades.db"))`
- L81 **REFERENCE** — `self.historical = HistoricalEvidenceRepository(str(self.data_dir / "dvs_paper_trades.db"), str(self.promotion_dir))`

### `dvs_ai/services/candidate_lifecycle_store.py`
- L45 **REFERENCE** — `def __init__(self, db_path: str = "data/dvs_paper_trades.db") -> None:`

### `dvs_ai/services/episode_audit_service.py`
- L12 **REFERENCE** — `def __init__(self, db_path: str | Path = "data/dvs_paper_trades.db") -> None:`

### `dvs_ai/services/episode_integrity_monitor.py`
- L15 **REFERENCE** — `def __init__(self, db_path: str | Path = "data/dvs_paper_trades.db") -> None:`

### `dvs_ai/services/evidence_analysis/observable_repository.py`
- L8 **REFERENCE** — `def __init__(self, db_path="data/dvs_paper_trades.db"): self.db_path=Path(db_path)`

### `dvs_ai/services/evidence_reliability_service.py`
- L37 **REFERENCE** — `db_path: str = "data/dvs_paper_trades.db",`
- L81 **READ** — `columns = {row[1] for row in con.execute("PRAGMA table_info(paper_trades)")}`
- L87 **READ** — `FROM paper_trades`

### `dvs_ai/services/historical_candidate_store.py`
- L33 **REFERENCE** — `def __init__(self, db_path: str = "data/dvs_paper_trades.db") -> None:`

### `dvs_ai/services/historical_evidence_repository.py`
- L34 **REFERENCE** — `def __init__(self, db_path: str = "data/dvs_paper_trades.db",`

### `dvs_ai/services/historical_readiness_trend.py`
- L87 **REFERENCE** — `def __init__(self, db_path: str="data/dvs_paper_trades.db") -> None:`

### `dvs_ai/services/integrity_incident_ledger.py`
- L25 **REFERENCE** — `source_db_path: str | Path = "data/dvs_paper_trades.db",`

### `dvs_ai/services/learning_service.py`
- L20 **REFERENCE** — `def __init__(self, db_path: str = "data/dvs_paper_trades.db") -> None:`
- L66 **READ** — `FROM paper_trades`
- L74 **READ** — `FROM paper_trades`
- L127 **READ** — `FROM paper_trades`
- L215 **READ** — `FROM paper_trades`
- L278 **READ** — `FROM paper_trades`
- L476 **READ** — `FROM paper_trades`
- L516 **READ** — `FROM paper_trades`

### `dvs_ai/services/operational_journey_service.py`
- L31 **REFERENCE** — `def __init__(self, db_path: str = "data/dvs_paper_trades.db", *, quantum_required: int = 80) -> None:`
- L64 **READ** — `exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_trades'").fetchone()`
- L67 **READ** — `return int(conn.execute("SELECT COUNT(*) FROM paper_trades WHERE status='CLOSED'").fetchone()[0] or 0)`

### `dvs_ai/services/operational_validation_service.py`
- L357 **REFERENCE** — `def __init__(self, db_path: str = "data/dvs_paper_trades.db", *, weights=None, regime_modifiers=None):`
- L449 **REFERENCE** — `def __init__(self, *, paper_db: str = "data/dvs_paper_trades.db", signals_db: str = "data/dvs_signals.db", health_weights=None, regime_modifiers=None):`

### `dvs_ai/services/outcome_infrastructure.py`
- L150 **REFERENCE** — `def __init__(self, db_path: str | Path = "data/dvs_paper_trades.db") -> None:`
- L300 **READ** — `if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_trades'").fetchone():`
- L301 **REFERENCE** — `cols = self._columns(con, "paper_trades")`
- L309 **WRITE/SCHEMA** — `con.execute(f"ALTER TABLE paper_trades ADD COLUMN {name} {ddl}")`

### `dvs_ai/services/paper_trade_service.py`
- L23 **REFERENCE** — `db_path: str = "data/dvs_paper_trades.db",`
- L49 **WRITE/SCHEMA** — `CREATE TABLE IF NOT EXISTS paper_trades (`
- L97 **REFERENCE** — `ON paper_trades(status, created_at)`
- L101 **REFERENCE** — `ON paper_trades(symbol, direction, status)`
- L107 **READ** — `"PRAGMA table_info(paper_trades)"`
- L112 **WRITE/SCHEMA** — `"ALTER TABLE paper_trades "`
- L117 **WRITE/SCHEMA** — `"ALTER TABLE paper_trades "`
- L122 **WRITE/SCHEMA** — `"ALTER TABLE paper_trades "`
- L127 **WRITE/SCHEMA** — `"ALTER TABLE paper_trades "`
- L131 **WRITE/SCHEMA** — `"UPDATE paper_trades SET lab='MAIN' "`
- L136 **WRITE/SCHEMA** — `"ALTER TABLE paper_trades "`
- L141 **WRITE/SCHEMA** — `"ALTER TABLE paper_trades "`
- L146 **WRITE/SCHEMA** — `"ALTER TABLE paper_trades "`
- L151 **WRITE/SCHEMA** — `"ALTER TABLE paper_trades "`
- L156 **WRITE/SCHEMA** — `"ALTER TABLE paper_trades "`
- L161 **WRITE/SCHEMA** — `"ALTER TABLE paper_trades "`
- L166 **WRITE/SCHEMA** — `"ALTER TABLE paper_trades "`
- L750 **READ** — `FROM paper_trades`
- L768 **READ** — `SELECT 1 FROM paper_trades`
- L834 **READ** — `SELECT COUNT(*) FROM paper_trades`
- L837 **READ** — `last_created = con.execute("SELECT MAX(created_at) FROM paper_trades").fetchone()[0]`
- L885 **WRITE/SCHEMA** — `INSERT INTO paper_trades (`
- L1000 **READ** — `FROM paper_trades`
- L1066 **WRITE/SCHEMA** — `UPDATE paper_trades`
- L1237 **WRITE/SCHEMA** — `UPDATE paper_trades`
- L1279 **READ** — `FROM paper_trades`
- L1346 **READ** — `FROM paper_trades`

### `dvs_ai/services/probability_calibration_service.py`
- L45 **REFERENCE** — `db_path: str = "data/dvs_paper_trades.db",`
- L71 **READ** — `FROM paper_trades`

### `dvs_ai/services/quantum_data_convergence/mapping.py`
- L22 **READ** — `"""Map paper_trades vocabulary without inferring outcome from PnL.`

### `dvs_ai/services/quantum_data_convergence/sources.py`
- L32 **REFERENCE** — `if "paper_trades" not in tables:`
- L38 **READ** — `FROM paper_trades`
- L49 **REFERENCE** — `source="paper_trades",`
- L67 **REFERENCE** — `"storage_table": "paper_trades",`

### `dvs_ai/services/quantum_optimizer.py`
- L78 **REFERENCE** — `db_path: str = "data/dvs_paper_trades.db",`
- L192 **READ** — `"PRAGMA table_info(paper_trades)"`
- L204 **READ** — `FROM paper_trades`

### `dvs_ai/services/quantum_readiness_service.py`
- L116 **REFERENCE** — `if "paper_trades" in tables:`
- L117 **READ** — `columns = {row[1] for row in con.execute("PRAGMA table_info(paper_trades)")}`
- L121 **READ** — `FROM paper_trades`

### `dvs_ai/services/shadow_observation_service.py`
- L34 **REFERENCE** — `def __init__(self, db_path: str = "data/dvs_paper_trades.db") -> None:`

### `dvs_ai/services/testnet_readiness_service.py`
- L55 **REFERENCE** — `def __init__(self, db_path: str = "data/dvs_paper_trades.db"):`

### `dvs_ai/services/truth_trend_store.py`
- L8 **REFERENCE** — `def __init__(self, db_path="data/dvs_paper_trades.db"):`

### `dvs_ai/ui/main_window.py`
- L960 **REFERENCE** — `getattr(self.paper_trade_service, "db_path", "data/dvs_paper_trades.db")`
- L1597 **REFERENCE** — `db_path = str(getattr(self.paper_trade_service, "db_path", "data/dvs_paper_trades.db"))`
- L1602 **REFERENCE** — `db_path = str(getattr(self.paper_trade_service, "db_path", "data/dvs_paper_trades.db"))`
- L1607 **REFERENCE** — `db_path = str(getattr(self.paper_trade_service, "db_path", "data/dvs_paper_trades.db"))`
- L1616 **REFERENCE** — `db_path = str(getattr(self.paper_trade_service, "db_path", "data/dvs_paper_trades.db"))`
- L1625 **REFERENCE** — `db_path = str(getattr(self.paper_trade_service, "db_path", "data/dvs_paper_trades.db"))`
- L1639 **REFERENCE** — `"data/dvs_paper_trades.db",`
- L1763 **REFERENCE** — `"data/dvs_paper_trades.db",`
- L3149 **REFERENCE** — `db_path = getattr(self.learning_service, "db_path", None) or getattr(self.quantum_optimizer, "db_path", "data/dvs_paper_trades.db")`
- L4302 **WRITE/SCHEMA** — `update_btn.clicked.connect(self.update_paper_trades)`
- L4386 **WRITE/SCHEMA** — `def update_paper_trades(self):`

### `dvs_ai/ui/truth_dashboard.py`
- L163 **REFERENCE** — `self._trend_store = TruthTrendStore("data/dvs_paper_trades.db")`
- L174 **REFERENCE** — `self._readiness_service = TestnetReadinessAuditService("data/dvs_paper_trades.db")`
- L177 **REFERENCE** — `self._journey_service = OperationalJourneyService("data/dvs_paper_trades.db")`

## `setup_episodes`

### `dvs_ai/services/episode_audit_service.py`
- L38 **READ** — `FROM setup_episodes e`
- L53 **READ** — `episode = con.execute("SELECT * FROM setup_episodes WHERE setup_episode_id=?", (episode_id,)).fetchone()`

### `dvs_ai/services/episode_integrity_monitor.py`
- L13 **REFERENCE** — `TABLES = {"setup_episodes", "episode_evaluations", "decision_candidates", "candidate_outcomes", "decision_diagnostic_traces"}`
- L53 **READ** — `LEFT JOIN setup_episodes e ON e.setup_episode_id=ev.setup_episode_id WHERE e.setup_episode_id IS NULL"""):`
- L56 **READ** — `LEFT JOIN setup_episodes e ON e.setup_episode_id=c.setup_episode_id WHERE e.setup_episode_id IS NULL"""):`
- L64 **READ** — `FROM setup_episodes e JOIN decision_candidates c ON c.setup_episode_id=e.setup_episode_id`
- L68 **READ** — `e.trade_plan_profile_hash et,c.trade_plan_profile_hash ct FROM setup_episodes e JOIN decision_candidates c ON c.setup_episode_id=e.setup_episode_id`
- L71 **READ** — `for r in con.execute("""SELECT dt.evaluation_id,dt.setup_episode_id FROM decision_diagnostic_traces dt JOIN setup_episodes e ON e.setup_episode_id=dt.setup_episode_id`
- L74 **READ** — `for r in con.execute("SELECT setup_episode_id,evaluation_count FROM setup_episodes"):`
- L79 **READ** — `for r in con.execute("SELECT setup_episode_id,last_seen_at FROM setup_episodes WHERE status='OPEN'"):`

### `dvs_ai/services/outcome_analytics.py`
- L72 **READ** — `FROM setup_episodes e`

### `dvs_ai/services/outcome_infrastructure.py`
- L163 **WRITE/SCHEMA** — `CREATE TABLE IF NOT EXISTS setup_episodes (`
- L188 **REFERENCE** — `ON setup_episodes(symbol,direction,status,last_seen_at);`
- L201 **REFERENCE** — `FOREIGN KEY(setup_episode_id) REFERENCES setup_episodes(setup_episode_id)`
- L228 **REFERENCE** — `FOREIGN KEY(setup_episode_id) REFERENCES setup_episodes(setup_episode_id)`
- L338 **READ** — `return con.execute("""SELECT * FROM setup_episodes WHERE symbol=? AND direction=?`
- L346 **WRITE/SCHEMA** — `con.execute("""INSERT INTO setup_episodes(`
- L365 **READ** — `sequence = con.execute("SELECT evaluation_count FROM setup_episodes WHERE setup_episode_id=?",`
- L370 **WRITE/SCHEMA** — `con.execute("UPDATE setup_episodes SET last_seen_at=?,evaluation_count=MAX(evaluation_count,?) WHERE setup_episode_id=?",`
- L411 **WRITE/SCHEMA** — `con.execute("""UPDATE setup_episodes SET activation_evaluation_id=?,activation_gate_set=?,episode_class=?,candidate_id=?`

### `dvs_ai/services/quantum_data_convergence/sources.py`
- L80 **REFERENCE** — `required = {"setup_episodes", "decision_candidates", "candidate_outcomes"}`
- L88 **READ** — `FROM setup_episodes e`

### `dvs_ai/services/quantum_dataset/factory.py`
- L152 **REFERENCE** — `"setup_episodes", "episode_evaluations", "decision_candidates", "candidate_outcomes"`
- L234 **READ** — `"SELECT COUNT(*) FROM decision_candidates c LEFT JOIN setup_episodes e ON e.setup_episode_id=c.setup_episode_id WHERE e.setup_episode_id IS NULL"`
- L259 **READ** — `FROM setup_episodes e`

### `dvs_ai/services/setup_episode_service.py`
- L91 **READ** — `activated = con.execute("SELECT candidate_id FROM setup_episodes WHERE setup_episode_id=?",`

## `candidate_outcomes`

### `dvs_ai/services/candidate_outcome_resolver.py`
- L57 **WRITE/SCHEMA** — `UPDATE candidate_outcomes`
- L73 **READ** — `FROM candidate_outcomes o`
- L81 **WRITE/SCHEMA** — `con.execute(f"UPDATE candidate_outcomes SET status='RESOLVING',resolution_claim_id=?,resolution_claimed_at=?,resolver_version=?,updated_at=? WHERE outcome_id IN ({marks}) AND status='PENDING'",`
- L84 **READ** — `SELECT o.*,c.* FROM candidate_outcomes o JOIN decision_candidates c USING(candidate_id)`
- L100 **WRITE/SCHEMA** — `con.execute("""UPDATE candidate_outcomes SET status=?,outcome_detail=?,outcome_time=?,outcome_price=?,`

### `dvs_ai/services/episode_audit_service.py`
- L40 **READ** — `LEFT JOIN candidate_outcomes o ON o.candidate_id=c.candidate_id`
- L66 **WRITE/SCHEMA** — `outcome = con.execute("SELECT * FROM candidate_outcomes WHERE candidate_id=? ORDER BY updated_at DESC LIMIT 1", (candidate["candidate_id"],)).fetchone()`

### `dvs_ai/services/episode_integrity_monitor.py`
- L13 **REFERENCE** — `TABLES = {"setup_episodes", "episode_evaluations", "decision_candidates", "candidate_outcomes", "decision_diagnostic_traces"}`
- L58 **READ** — `for r in con.execute("""SELECT o.outcome_id,o.candidate_id FROM candidate_outcomes o`
- L85 **READ** — `for r in con.execute("SELECT outcome_id,candidate_id,status,resolution_claimed_at FROM candidate_outcomes WHERE status='RESOLVING'"):`

### `dvs_ai/services/outcome_analytics.py`
- L74 **READ** — `JOIN candidate_outcomes o ON o.candidate_id=c.candidate_id`

### `dvs_ai/services/outcome_infrastructure.py`
- L241 **WRITE/SCHEMA** — `CREATE TABLE IF NOT EXISTS candidate_outcomes (`
- L416 **WRITE/SCHEMA** — `con.execute("""INSERT OR IGNORE INTO candidate_outcomes(`

### `dvs_ai/services/quantum_data_convergence/sources.py`
- L80 **REFERENCE** — `required = {"setup_episodes", "decision_candidates", "candidate_outcomes"}`
- L90 **READ** — `JOIN candidate_outcomes o ON o.candidate_id=c.candidate_id`
- L101 **REFERENCE** — `source="candidate_outcomes",`
- L120 **REFERENCE** — `"storage_table": "candidate_outcomes",`

### `dvs_ai/services/quantum_dataset/factory.py`
- L152 **REFERENCE** — `"setup_episodes", "episode_evaluations", "decision_candidates", "candidate_outcomes"`
- L228 **READ** — `"SELECT COUNT(*) FROM (SELECT candidate_id, COUNT(*) n FROM candidate_outcomes GROUP BY candidate_id HAVING n>1)"`
- L231 **READ** — `"SELECT COUNT(*) FROM candidate_outcomes o LEFT JOIN decision_candidates c ON c.candidate_id=o.candidate_id WHERE c.candidate_id IS NULL"`
- L237 **READ** — `SELECT COUNT(*) FROM candidate_outcomes o`
- L261 **READ** — `LEFT JOIN candidate_outcomes o ON o.candidate_id=c.candidate_id`
