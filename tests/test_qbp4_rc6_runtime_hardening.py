from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[1]


def test_rc6_runtime_hardening_contract():
    version = (ROOT / 'dvs_ai/version.py').read_text(encoding='utf-8')
    source = (ROOT / 'dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
    profiler = (ROOT / 'dvs_ai/ui/ui_performance_profiler.py').read_text(encoding='utf-8')
    assert 'APP_VERSION = "4.3.0E-3-QBP-4-RC7"' in version
    assert 'PERFORMANCE_SUMMARY' in source
    assert 'PERFORMANCE_DRIFT_DETECTED' in source
    assert 'DISPLAY_INTEGRITY_OK' in source
    assert 'DISPLAY_INTEGRITY_FAILED' in source
    assert 'record_commit_metrics' in profiler
    assert 'p90_commit_ms' in profiler and 'p99_commit_ms' in profiler
    assert 'fingerprint_hit_ratio' in profiler


def test_profiler_burn_in_math_without_qt_runtime():
    source = (ROOT / 'dvs_ai/ui/ui_performance_profiler.py').read_text(encoding='utf-8')
    assert 'def _percentile' in source
    assert 'def _linear_slope' in source
    assert 'slope_ms_per_commit' in source
    assert 'rows_updated_ratio' in source


def test_frozen_decision_engine_hash_rc6():
    data = (ROOT / 'dvs_ai/engines/decision_engine.py').read_bytes()
    assert hashlib.md5(data).hexdigest() == '72cf7d54e1ed6369400683358da8c0ef'
    assert hashlib.sha256(data).hexdigest() == '00c1db1a1684896b3c06fbf4cfaeea094337f1841dc2e3cb9dfdf9013252dbce'
