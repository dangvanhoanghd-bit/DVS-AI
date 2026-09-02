from __future__ import annotations
import json
from pathlib import Path
from dvs_ai.services.quantum_governance.checksum import canonical_sha256, file_sha256
from dvs_ai.services.quantum_runtime_guard import QuantumRuntimeAction, QuantumRuntimeGuard

def make_bundle(root: Path, optimizer=True, shadow=True):
    root.mkdir()
    g={"schema_version":"dvs-quantum-governance-v1","state":"READY_FOR_AUDIT","study_id":"qi2","runtime_authority":{"optimizer_allowed":optimizer,"shadow_apply_allowed":shadow},"safety_boundary":{"optimizer_authority":optimizer,"shadow_write_authority":shadow}}
    g["self_sha256"]=canonical_sha256(g)
    gp=root/'governance.manifest.json'; gp.write_text(json.dumps(g,sort_keys=True))
    idx={"schema_version":"dvs-quantum-audit-bundle-v1","study_id":"qi2","governance_state":"READY_FOR_AUDIT","files":{gp.name:file_sha256(gp)},"immutable_intent":True}
    idx["self_sha256"]=canonical_sha256(idx)
    ip=root/'audit_bundle.index.json'; ip.write_text(json.dumps(idx,sort_keys=True))
    return file_sha256(ip)

def configure(monkeypatch, bundle, fingerprint, log):
    monkeypatch.setenv('DVS_QUANTUM_ALLOWED_BUNDLE_ROOTS', str(bundle.parent))
    monkeypatch.setenv('DVS_QUANTUM_TRUSTED_BUNDLE_SHA256', fingerprint)
    monkeypatch.setenv('DVS_QUANTUM_RUNTIME_AUDIT_LOG', str(log))

def test_untrusted_bundle_blocks(tmp_path, monkeypatch):
    b=tmp_path/'bundle'; fp=make_bundle(b)
    monkeypatch.setenv('DVS_QUANTUM_ALLOWED_BUNDLE_ROOTS', str(tmp_path))
    monkeypatch.setenv('DVS_QUANTUM_TRUSTED_BUNDLE_SHA256', '0'*64)
    d=QuantumRuntimeGuard(b,audit_log=tmp_path/'log.jsonl').evaluate(QuantumRuntimeAction.OPTIMIZE)
    assert not d.allowed and 'BUNDLE_FINGERPRINT_NOT_TRUSTED' in d.violations

def test_allowed_trusted_bundle_opens_and_logs_hash_chain(tmp_path, monkeypatch):
    b=tmp_path/'bundle'; fp=make_bundle(b); log=tmp_path/'runtime.jsonl'; configure(monkeypatch,b,fp,log)
    guard=QuantumRuntimeGuard(b)
    assert guard.startup_self_test().allowed
    assert guard.evaluate(QuantumRuntimeAction.OPTIMIZE).allowed
    rows=[json.loads(x) for x in log.read_text().splitlines()]
    assert len(rows)==2 and rows[0]['previous_hash']=='GENESIS'
    assert rows[1]['previous_hash']==rows[0]['entry_hash']
    for row in rows:
        h=row.pop('entry_hash'); assert canonical_sha256(row)==h

def test_path_outside_allowlist_blocks(tmp_path, monkeypatch):
    allowed=tmp_path/'allowed'; allowed.mkdir(); b=tmp_path/'other'/'bundle'; b.parent.mkdir(); fp=make_bundle(b)
    monkeypatch.setenv('DVS_QUANTUM_ALLOWED_BUNDLE_ROOTS', str(allowed))
    monkeypatch.setenv('DVS_QUANTUM_TRUSTED_BUNDLE_SHA256', fp)
    d=QuantumRuntimeGuard(b,audit_log=tmp_path/'log').evaluate(QuantumRuntimeAction.OPTIMIZE)
    assert not d.allowed and 'BUNDLE_PATH_NOT_ALLOWED' in d.violations

def test_startup_self_test_does_not_require_action_authority(tmp_path, monkeypatch):
    b=tmp_path/'bundle'; fp=make_bundle(b,False,False); configure(monkeypatch,b,fp,tmp_path/'log')
    assert QuantumRuntimeGuard(b).startup_self_test().allowed
    assert not QuantumRuntimeGuard(b).evaluate(QuantumRuntimeAction.OPTIMIZE).allowed
