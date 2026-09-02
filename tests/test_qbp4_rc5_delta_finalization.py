from pathlib import Path
import hashlib
ROOT = Path(__file__).resolve().parents[1]

def test_rc5_delta_contract():
    version=(ROOT/'dvs_ai/version.py').read_text(encoding='utf-8')
    source=(ROOT/'dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
    block=source[source.index('def _commit_finalization_payload'):source.index('def _submit_qualification_batch')]
    assert 'APP_VERSION = "4.3.0E-3-QBP-4-RC7"' in version
    assert '"commit_strategy": "delta_only"' in block
    assert 'self.table.setRowCount(0)' not in block
    assert 'rows_unchanged' in block and '_analysis_table_fingerprint' in source

def test_frozen_decision_engine_hash():
    data=(ROOT/'dvs_ai/engines/decision_engine.py').read_bytes()
    assert hashlib.md5(data).hexdigest()=='72cf7d54e1ed6369400683358da8c0ef'
    assert hashlib.sha256(data).hexdigest()=='00c1db1a1684896b3c06fbf4cfaeea094337f1841dc2e3cb9dfdf9013252dbce'
