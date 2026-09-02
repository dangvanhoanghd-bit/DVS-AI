from __future__ import annotations

from datetime import datetime, timedelta, timezone

from dvs_ai.services.integrity_alert_policy import IntegrityAlertPolicy


def incident(*, severity="WARNING", age=0, occurrences=1, recurrences=0, state="OPEN"):
    return {
        "incident_key": "k1", "state": state, "severity": severity,
        "code": "TEST", "entity": "episode", "entity_id": "e1",
        "age_seconds": age, "occurrence_count": occurrences,
        "recurrence_count": recurrences,
    }


def test_policy_is_deterministic_and_conservative():
    assert IntegrityAlertPolicy.classify(incident(severity="CRITICAL"))[0] == "URGENT"
    assert IntegrityAlertPolicy.classify(incident(severity="ERROR"))[0] == "ALERT"
    assert IntegrityAlertPolicy.classify(incident(severity="ERROR", age=3600))[0] == "URGENT"
    assert IntegrityAlertPolicy.classify(incident(severity="WARNING"))[0] == "NOTICE"
    assert IntegrityAlertPolicy.classify(incident(severity="WARNING", age=7200))[0] == "WATCH"
    assert IntegrityAlertPolicy.classify(incident(severity="INFO"))[0] == "NONE"
    assert IntegrityAlertPolicy.classify(incident(state="RESOLVED"))[0] == "NONE"


def test_alert_lifecycle_new_escalated_cleared(tmp_path):
    policy = IntegrityAlertPolicy(tmp_path / "ledger.db")
    now = datetime(2026, 7, 21, tzinfo=timezone.utc)
    payload = {"incidents": [incident(severity="WARNING")]}
    first = policy.evaluate(payload, now=now)
    assert first["status"] == "NOTICE"
    assert first["transitions"]["new"] == ["k1"]

    payload["incidents"][0]["age_seconds"] = 7200
    second = policy.evaluate(payload, now=now + timedelta(hours=2))
    assert second["status"] == "WATCH"
    assert second["transitions"]["escalated"] == ["k1"]

    third = policy.evaluate({"incidents": []}, now=now + timedelta(hours=3))
    assert third["status"] == "CLEAR"
    assert third["transitions"]["cleared"] == ["k1"]
