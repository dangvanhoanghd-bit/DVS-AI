import json
from pathlib import Path
from beta4a_burnin_collector import read_runtime_telemetry


def test_collector_contract(tmp_path: Path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "runtime_status.json").write_text(json.dumps({"pid": 123, "version": "RC6.1", "session_id": "s1"}), encoding="utf-8")
    (runtime / "heartbeat.json").write_text(json.dumps({
        "status": "RUNNING", "pid": 123, "version": "RC6.1", "session_id": "s1",
        "process": {"rss_bytes": 10, "cpu_percent": 1.0, "thread_count": 2, "open_files": 0},
        "ui": {"last_event_loop_lag_ms": 4.0}, "queues": {"pending_unified_identities": 0},
    }), encoding="utf-8")
    result = read_runtime_telemetry(runtime)
    assert result["found"] is True
    assert result["state"] == "RUNTIME_CONNECTED"
    assert result["rss_bytes"] == 10


def test_missing_runtime_is_explicit(tmp_path: Path):
    result = read_runtime_telemetry(tmp_path / "missing")
    assert result["found"] is False
    assert result["state"] == "RUNTIME_NOT_STARTED"
