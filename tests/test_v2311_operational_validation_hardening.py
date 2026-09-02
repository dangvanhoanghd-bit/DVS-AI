import math
from dvs_ai.services.operational_validation_service import *

def cov(state="FULL"):
 return CoverageSnapshot(state,100,100,{"BULL":40,"BEAR":30,"RANGE":30},{"LONG":50,"SHORT":50},{"FULL":100},1,1,())
def conf(state="BALANCED"):
 return ConfidenceSnapshot(state,100,50,50,70,80,.3,.05,{"0-30":1,"30-50":1,"50-70":1,"70+":1},())
def regimes(state="SUPPORTED"):
 return RegimeValidationSnapshot(state,(),2,())

def test_weights_normalize_and_fallback(tmp_path):
 s=AIHealthService(str(tmp_path/"x.db"),weights={"data_quality":-9,"calibration":200})
 assert abs(sum(s.weights.values())-100)<1e-6
 assert s.weight_warnings

def test_regime_modifier_explained(tmp_path):
 s=AIHealthService(str(tmp_path/"x.db"),weights=AIHealthService.DEFAULT_WEIGHTS,regime_modifiers={"RANGE":{"coverage":1.2}})
 snap=s.evaluate(coverage=cov(),confidence=conf(),regimes=regimes(),alerts=(),calibration_state="VALIDATED",drift_state="STABLE",reliability_state="VALIDATED",runtime_state="CONNECTED",active_regime="RANGE")
 assert snap.modifiers["coverage"]==1.2 and 0<=snap.score<=100

def test_composite_critical_incident():
 alerts=OperationalAlertCenter().build(coverage=cov("BLOCKED"),confidence=conf(),regimes=regimes(),calibration_state="VALIDATED",drift_state="DRIFT",reliability_state="VALIDATED",runtime_state="CONNECTED")
 assert alerts[0].composite and alerts[0].severity=="CRITICAL"

def test_composite_watch_actionable():
 alerts=OperationalAlertCenter().build(coverage=cov("DEGRADED"),confidence=conf("VERY_STRICT"),regimes=regimes(),calibration_state="VALIDATED",drift_state="STABLE",reliability_state="VALIDATED",runtime_state="CONNECTED")
 assert any(a.code=="COMPOSITE_DATA_WATCH" and a.action for a in alerts)

def test_health_history_dedup(tmp_path):
 s=AIHealthService(str(tmp_path/"x.db"))
 snap=s.evaluate(coverage=cov(),confidence=conf(),regimes=regimes(),alerts=(),calibration_state="VALIDATED",drift_state="STABLE",reliability_state="VALIDATED",runtime_state="CONNECTED")
 assert s.append(snap,snapshot_key="same") is True
 assert s.append(snap,snapshot_key="same") is False
