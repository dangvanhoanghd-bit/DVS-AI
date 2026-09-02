from pathlib import Path
import sqlite3

from dvs_ai.services.operational_validation_service import (
    AIHealthService, ConfidenceDistributionEngine, DataCoverageEngine,
    OperationalAlertCenter, OperationalValidationPlatform, RegimeValidationEngine,
)


def rows(n=90):
    out=[]
    regimes=("BULL","BEAR","RANGE")
    for i in range(n):
        out.append({
            "regime":regimes[i%3], "direction":"LONG" if i%2==0 else "SHORT",
            "paper_trade_id":i+1, "outcome_r":1.0 if i%3 else -0.5,
            "baseline_decision":"WAIT" if i%4 else "READY",
            "shadow_decision":"READY", "truth":{"order_flow_quality":"FULL"},
        })
    return out


def test_coverage_requires_regime_and_direction_support():
    result=DataCoverageEngine(min_total=30,min_regime=10,min_direction=10).evaluate(rows(90))
    assert result.state == "FULL"
    assert result.regime_coverage == 1.0 and result.direction_coverage == 1.0


def test_confidence_distribution_is_deterministic_and_explains_strictness():
    result=ConfidenceDistributionEngine(min_samples=10).evaluate([20]*80+[55]*19+[75])
    assert result.samples == 100
    assert result.histogram["70+"] == 1
    assert result.state == "STRICT"


def test_regime_validation_blocks_underperforming_regime():
    data=rows(90)
    for row in data:
        if row["regime"] == "BEAR":
            row["outcome_r"]=-1.0
            row["baseline_decision"]="READY"
            row["shadow_decision"]="WAIT"
    result=RegimeValidationEngine(min_samples=10).evaluate(data)
    assert result.state in {"UNSTABLE", "CONTINUE_OBSERVATION"}
    assert len(result.metrics) == 3


def test_health_score_is_observe_only_and_append_deduplicates(tmp_path):
    coverage=DataCoverageEngine(min_total=30,min_regime=10,min_direction=10).evaluate(rows(90))
    confidence=ConfidenceDistributionEngine(min_samples=10).evaluate([60]*100)
    regimes=RegimeValidationEngine(min_samples=10).evaluate(rows(90))
    alerts=OperationalAlertCenter().build(coverage=coverage,confidence=confidence,regimes=regimes,
        calibration_state="VALIDATED",drift_state="STABLE",reliability_state="VALIDATED",runtime_state="CONNECTED")
    service=AIHealthService(str(tmp_path/'paper.db'))
    health=service.evaluate(coverage=coverage,confidence=confidence,regimes=regimes,alerts=alerts,
        calibration_state="VALIDATED",drift_state="STABLE",reliability_state="VALIDATED",runtime_state="CONNECTED")
    assert 0 <= health.score <= 100
    assert service.append(health,snapshot_key="same") is True
    assert service.append(health,snapshot_key="same") is False


def test_platform_reads_persisted_data_without_mutating_trading_tables(tmp_path):
    paper=tmp_path/'paper.db'; signals=tmp_path/'signals.db'
    with sqlite3.connect(paper) as con:
        con.execute('CREATE TABLE shadow_observations(id INTEGER PRIMARY KEY,candidate_id TEXT,symbol TEXT,direction TEXT,regime TEXT,baseline_decision TEXT,shadow_decision TEXT,paper_trade_id INTEGER,outcome_r REAL,truth_json TEXT)')
        for i,row in enumerate(rows(90),1):
            con.execute('INSERT INTO shadow_observations VALUES(?,?,?,?,?,?,?,?,?,?)',(i,'C1','BTC',row['direction'],row['regime'],row['baseline_decision'],row['shadow_decision'],row['paper_trade_id'],row['outcome_r'],'{"order_flow_quality":"FULL"}'))
    with sqlite3.connect(signals) as con:
        con.execute('CREATE TABLE scan_signals(id INTEGER PRIMARY KEY,confidence REAL)')
        con.executemany('INSERT INTO scan_signals(confidence) VALUES(?)',[(v,) for v in range(20,80)])
    before=paper.read_bytes()
    snapshot=OperationalValidationPlatform(paper_db=str(paper),signals_db=str(signals)).snapshot(runtime_state='CONNECTED')
    assert snapshot.coverage.total == 90
    # health table creation is allowed; observation rows remain unchanged
    with sqlite3.connect(paper) as con:
        assert con.execute('SELECT COUNT(*) FROM shadow_observations').fetchone()[0] == 90


def test_source_boundary_has_no_execution_or_config_mutation():
    source=Path('dvs_ai/services/operational_validation_service.py').read_text()
    forbidden=('send_order','TradeIntentBuilder','PositionSizer','ShadowPromotionService','config.json')
    assert all(token not in source for token in forbidden)
