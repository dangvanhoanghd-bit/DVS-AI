from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import pytest
from dvs_ai.configuration import VersionedConfigManager
from dvs_ai.monitoring import Alert, AlertCenter, AlertSeverity
from dvs_ai.plugins import PluginKind, PluginRegistry
from dvs_ai.readiness import DeploymentMode, ProductionReadinessGate, REQUIRED_CHECKS
from dvs_ai.runtime import ComponentHealth, HealthStatus, RuntimeHealthMonitor


def test_health_monitor_fail_closed_on_exception():
    monitor=RuntimeHealthMonitor()
    monitor.register_check("boom", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    report=monitor.run()
    assert report.status is HealthStatus.UNHEALTHY
    assert report.components[0].message.startswith("check exception")


def test_heartbeat_staleness():
    monitor=RuntimeHealthMonitor(); now=datetime.now(timezone.utc)
    monitor.heartbeat("feed", at=now-timedelta(seconds=20))
    assert monitor.check_heartbeat("feed", max_age_seconds=5, now=now).status is HealthStatus.UNHEALTHY


def test_alert_center_history_and_sink_isolation():
    center=AlertCenter(max_history=2); seen=[]
    center.add_sink(lambda a: seen.append(a.code)); center.add_sink(lambda a: (_ for _ in ()).throw(RuntimeError()))
    for code in ("A","B","C"):
        center.publish(Alert(code, AlertSeverity.WARNING, code, "test"))
    assert seen == ["A","B","C"]
    assert [a.code for a in center.history()] == ["B","C"]


def test_versioned_config_validation_and_rollback():
    def validate(data):
        if data.get("live_enabled"):
            raise ValueError("live prohibited")
    manager=VersionedConfigManager({"live_enabled":False,"risk":1}, validate)
    manager.apply({"live_enabled":False,"risk":2})
    assert manager.current.version == 2
    rolled=manager.rollback(1)
    assert rolled.version == 3 and rolled.data["risk"] == 1
    with pytest.raises(ValueError): manager.apply({"live_enabled":True})


def test_plugin_registry_rejects_duplicates():
    @dataclass
    class P:
        name:str="rsi"; version:str="1"; kind:PluginKind=PluginKind.INDICATOR
    registry=PluginRegistry(); registry.register(P())
    with pytest.raises(ValueError): registry.register(P())


def test_readiness_gate_is_fail_closed():
    gate=ProductionReadinessGate()
    partial={name:True for name in REQUIRED_CHECKS if name != "paper_kpi"}
    report=gate.evaluate(partial)
    assert report.mode is DeploymentMode.SIMULATION_ONLY
    assert "READINESS_PAPER_KPI_FAILED" in report.reason_codes


def test_readiness_gate_allows_eligibility_only_when_all_pass():
    report=ProductionReadinessGate().evaluate({name:True for name in REQUIRED_CHECKS})
    assert report.ready and report.mode is DeploymentMode.LIVE_ELIGIBLE
