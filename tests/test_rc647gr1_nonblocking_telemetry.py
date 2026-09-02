from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]

def test_retention_telemetry_is_fail_open_nonblocking():
    src=(ROOT/'dvs_ai/ui/retention_owner_telemetry.py').read_text(encoding='utf-8')
    assert 'acquire(blocking=False)' in src
    assert 'lock_busy_drop_total' in src
    tree=ast.parse(src)
    record=next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name=='record_mutation')
    assert not any(isinstance(n, ast.With) for n in ast.walk(record))

def test_hang_dump_and_stage_probes_present():
    src=(ROOT/'dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
    assert 'faulthandler.dump_traceback' in src
    assert 'elapsed_ms >= 5000.0' in src
    for stage in ('before_owner_release','after_owner_release_before_record_mutation','after_record_mutation','before_worker_emit','after_worker_emit'):
        assert stage in src
