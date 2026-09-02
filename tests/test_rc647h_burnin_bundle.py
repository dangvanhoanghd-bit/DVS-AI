from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys

from dvs_ai.governance.burnin_bundle import build_burnin_validation_bundle

ROOT = Path(__file__).resolve().parents[1]


def test_burnin_bundle_is_evidence_not_audit_result(tmp_path):
    runtime = ROOT / "artifacts" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    sample = runtime / "_rc647h_test_sample.jsonl"
    sample.write_text('{"event":"ok"}\n', encoding="utf-8")
    try:
        result = build_burnin_validation_bundle(ROOT, tmp_path / "bundle")
        summary = json.loads((tmp_path / "bundle" / "burnin_summary.json").read_text(encoding="utf-8"))
        assert summary["document_role"] == "EVIDENCE_PACKAGE_NOT_AUDIT_RESULT"
        assert summary["audit_status"] == "NOT_AUDITED"
        assert result.writer_errors == 0
        assert (tmp_path / "bundle.zip").is_file()
    finally:
        sample.unlink(missing_ok=True)


def test_bundle_manifest_verifies(tmp_path):
    out = tmp_path / "bundle"
    build_burnin_validation_bundle(ROOT, out)
    proc = subprocess.run([sys.executable, str(out / "verify_bundle.py")], capture_output=True, text=True)
    payload = json.loads(proc.stdout)
    assert proc.returncode == 0, proc.stderr
    assert payload["valid"] is True


def test_bundle_manifest_fails_closed_after_tamper(tmp_path):
    out = tmp_path / "bundle"
    build_burnin_validation_bundle(ROOT, out)
    target = out / "burnin_summary.json"
    target.write_text(target.read_text(encoding="utf-8") + " ", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(out / "verify_bundle.py")], capture_output=True, text=True)
    payload = json.loads(proc.stdout)
    assert proc.returncode == 2
    assert payload["valid"] is False
