from pathlib import Path
import ast

ROOT=Path(__file__).resolve().parent

def test_contract():
    src=(ROOT/'dvs_ai/runtime/payload_footprint_telemetry.py').read_text(encoding='utf-8')
    assert 'gc.get_objects' not in src
    assert 'repr(' not in src
    assert 'MainWindow._truth_dashboard_pending_analysis' in src
    assert 'MainWindow.current_analysis' in src
    assert 'MainWindow.results' in src
    assert 'memory_usage(index=True, deep=True)' in src
    assert 'obj.nbytes' in src

def test_runtime_identity_uses_canonical_build_id():
    src=(ROOT/'dvs_ai/app.py').read_text(encoding='utf-8')
    assert 'from dvs_ai.version import APP_VERSION, BUILD_ID' in src
    assert '"build_id": BUILD_ID' in src
    assert 'RC6.4.7F-r2-OLD-OBJECT' not in src

def test_main_window_hook():
    src=(ROOT/'dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
    assert 'PAYLOAD_FOOTPRINT_TELEMETRY.snapshot(' in src
    ast.parse(src)
