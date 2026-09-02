from pathlib import Path
import hashlib, json, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def test_release_identity_five_sources_agree():
    from dvs_ai.version import APP_VERSION, BUILD_ID
    assert (ROOT/'BUILD_ID.txt').read_text().strip()==BUILD_ID
    top=json.loads((ROOT/'code_identity.json').read_text())
    art=json.loads((ROOT/'artifacts/code_identity.json').read_text())
    assert top==art
    assert top['build_id']==BUILD_ID
    assert top['app_version']==APP_VERSION
    manifest={}
    for line in (ROOT/'SOURCE_SHA256.txt').read_text().splitlines():
        h, rel=line.split('  ',1); manifest[rel]=h
    for rel in ('dvs_ai/ui/main_window.py','dvs_ai/ui/retention_owner_telemetry.py','dvs_ai/engines/decision_engine.py','dvs_ai/app.py','dvs_ai/version.py'):
        assert manifest[rel]==sha(ROOT/rel)
        assert top['files'][rel]==sha(ROOT/rel)
