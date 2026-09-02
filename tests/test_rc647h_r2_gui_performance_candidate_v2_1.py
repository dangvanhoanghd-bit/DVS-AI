from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'dvs_ai/ui/main_window.py').read_text(encoding='utf-8')


def test_paper_chunk_is_directly_attributed():
    assert '@_audit_gui_callback("paper_trade_chunk_commit"' in SOURCE
    assert 'def _commit_paper_chunk(self):' in SOURCE


def test_forensic_timing_is_in_memory_and_async():
    assert 'time.perf_counter_ns()' in SOURCE
    assert '_paper_commit_forensic_ring.append(record)' in SOURCE
    body = SOURCE.split('def _commit_paper_chunk(self):', 1)[1].split('def auto_paper_consider', 1)[0]
    loop = body.split('for row in range(begin,end):', 1)[1].split('qt_commit_ms=', 1)[0]
    assert '_append_rc63_jsonl' not in loop


def test_queue_wait_and_qt_commit_are_separate():
    for token in ('queue_wait_ms', 'qt_commit_ms', 'callback_execution_ms', 'telemetry_publish_ms'):
        assert token in SOURCE


def test_operation_breakdown_is_available_only_on_budget_exceedance():
    assert 'if budget_exceeded:' in SOURCE
    assert 'record["span_breakdown_ms"]' in SOURCE
    assert 'record["slow_spans"]' in SOURCE


def test_decision_engine_frozen():
    data = (ROOT / 'dvs_ai/engines/decision_engine.py').read_bytes()
    assert hashlib.sha256(data).hexdigest() == '00c1db1a1684896b3c06fbf4cfaeea094337f1841dc2e3cb9dfdf9013252dbce'
