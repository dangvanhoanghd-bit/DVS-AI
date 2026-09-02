import json
import time
from pathlib import Path

from dvs_ai.runtime.payload_footprint_telemetry import PayloadFootprintTelemetry


def _records(path: Path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def _wait_terminal(path: Path, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            rows = _records(path)
            if any(r.get('event') in {'snapshot_finished', 'snapshot_failed'} for r in rows):
                return rows
        time.sleep(0.02)
    raise AssertionError('terminal event not observed')


def test_single_flight_lifecycle_and_thread_identity(tmp_path):
    path = tmp_path / 'payload.jsonl'
    telemetry = PayloadFootprintTelemetry(path)
    assert telemetry.snapshot(cycle_index=1, results={'A': [1, 2]}, current_analysis=None, pending_analysis={})
    rows = _wait_terminal(path)
    submit = [r for r in rows if r.get('event') == 'snapshot_submit']
    started = [r for r in rows if r.get('event') == 'snapshot_started']
    terminal = [r for r in rows if r.get('event') in {'snapshot_finished', 'snapshot_failed'}]
    assert len(submit) == len(started) == len(terminal) == 1
    assert submit[0]['request_id'] == started[0]['request_id'] == terminal[0]['request_id']
    assert terminal[0]['reference_release_monotonic'] >= terminal[0]['measurement_finished_monotonic']
    snapshots = [r for r in rows if r.get('event') == 'owner_footprint_snapshot']
    assert snapshots
    assert all(r['is_gui_thread'] is False for r in snapshots)


def test_busy_drop_is_explicit_and_accounted(tmp_path, monkeypatch):
    path = tmp_path / 'payload.jsonl'
    telemetry = PayloadFootprintTelemetry(path)
    original = telemetry._measure

    def slow(*args, **kwargs):
        time.sleep(0.15)
        return original(*args, **kwargs)

    monkeypatch.setattr(telemetry, '_measure', slow)
    assert telemetry.snapshot(cycle_index=1, results={'A': [1]}, current_analysis=None, pending_analysis={})
    assert telemetry.snapshot(cycle_index=2, results={'B': [2]}, current_analysis=None, pending_analysis={}) is False
    rows = _wait_terminal(path)
    submits = [r for r in rows if r.get('event') == 'snapshot_submit']
    starts = [r for r in rows if r.get('event') == 'snapshot_started']
    drops = [r for r in rows if r.get('event') == 'snapshot_busy_drop']
    assert len(submits) == len(starts) + len(drops)
    assert len({r['generation'] for r in submits}) == len(submits)
    assert [r['generation'] for r in submits] == sorted(r['generation'] for r in submits)
