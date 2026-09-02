from __future__ import annotations
import hashlib
import json
from pathlib import Path

from dvs_ai.services.quantum_governance.checksum import canonical_sha256
from dvs_ai.services.quantum_release_qualification import QuantumReleaseQualifier


class GuardStub:
    def __init__(self, allowed: bool, audit_log: Path):
        self.allowed = allowed
        self.audit_log = audit_log
    def startup_self_test(self):
        class D:
            allowed = self.allowed
            def message(inner):
                return "approved" if inner.allowed else "blocked"
        return D()


def write_audit(path: Path, count=2):
    prev = "GENESIS"
    rows=[]
    for i in range(count):
        row={"schema_version":"dvs-quantum-runtime-audit-v1","timestamp_utc":f"2026-01-01T00:00:0{i}+00:00","action":"STARTUP_SELF_TEST","allowed":True,"violations":[],"bundle_dir":"/x","study_id":"s","bundle_fingerprint":"f","previous_hash":prev}
        row["entry_hash"]=canonical_sha256(row); prev=row["entry_hash"]; rows.append(row)
    path.write_text("\n".join(json.dumps(x,sort_keys=True,separators=(",",":")) for x in rows)+"\n")


def make_project(tmp_path: Path):
    (tmp_path/'dvs_ai/engines').mkdir(parents=True)
    engine=tmp_path/'dvs_ai/engines/decision_engine.py'; engine.write_text('frozen')
    (tmp_path/'config.json').write_text(json.dumps({"execution_mode":"PAPER","quantum_auto_apply_shadow":False}))
    log=tmp_path/'audit.jsonl'; write_audit(log)
    return engine, log


def test_audit_chain_accepts_valid_and_rejects_tamper(tmp_path):
    log=tmp_path/'audit.jsonl'; write_audit(log)
    assert QuantumReleaseQualifier.verify_runtime_audit_log(log)[0]
    rows=log.read_text().splitlines(); payload=json.loads(rows[0]); payload['allowed']=False; rows[0]=json.dumps(payload)
    log.write_text('\n'.join(rows)+'\n')
    valid, detail=QuantumReleaseQualifier.verify_runtime_audit_log(log)
    assert not valid and 'HASH_INVALID' in detail


def test_qualification_passes_only_when_all_checks_pass(tmp_path, monkeypatch):
    engine, log=make_project(tmp_path)
    expected=hashlib.md5(b'frozen').hexdigest()
    monkeypatch.setattr('dvs_ai.services.quantum_release_qualification.FROZEN_DECISION_ENGINE_MD5', expected)
    q=QuantumReleaseQualifier(tmp_path, guard=GuardStub(True,log))
    report=q.run()
    assert report.qualified and report.state=='QUALIFIED_RESEARCH_RUNTIME'
    assert all(c.passed for c in report.checks)


def test_unsafe_config_blocks(tmp_path, monkeypatch):
    engine, log=make_project(tmp_path)
    (tmp_path/'config.json').write_text(json.dumps({"execution_mode":"LIVE","quantum_auto_apply_shadow":True}))
    monkeypatch.setattr('dvs_ai.services.quantum_release_qualification.FROZEN_DECISION_ENGINE_MD5', hashlib.md5(b'frozen').hexdigest())
    report=QuantumReleaseQualifier(tmp_path, guard=GuardStub(True,log)).run()
    assert not report.qualified
    check=next(x for x in report.checks if x.name=='runtime_configuration')
    assert not check.passed and 'QUANTUM_AUTO_APPLY_SHADOW_NOT_FALSE' in check.detail


def test_governance_or_ledger_failure_blocks(tmp_path, monkeypatch):
    engine, log=make_project(tmp_path)
    monkeypatch.setattr('dvs_ai.services.quantum_release_qualification.FROZEN_DECISION_ENGINE_MD5', hashlib.md5(b'frozen').hexdigest())
    assert not QuantumReleaseQualifier(tmp_path, guard=GuardStub(False,log)).run().qualified
    log.unlink()
    assert not QuantumReleaseQualifier(tmp_path, guard=GuardStub(True,log)).run().qualified


def test_report_has_verifiable_self_hash(tmp_path, monkeypatch):
    engine, log=make_project(tmp_path)
    monkeypatch.setattr('dvs_ai.services.quantum_release_qualification.FROZEN_DECISION_ENGINE_MD5', hashlib.md5(b'frozen').hexdigest())
    payload=QuantumReleaseQualifier(tmp_path, guard=GuardStub(True,log)).run().to_dict()
    claimed=payload.pop('report_sha256')
    assert canonical_sha256(payload)==claimed
