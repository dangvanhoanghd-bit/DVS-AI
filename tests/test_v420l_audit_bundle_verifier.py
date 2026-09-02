from __future__ import annotations

import json
import zipfile
from pathlib import Path

from dvs_ai.services.audit_bundle_verifier import IndependentAuditBundleVerifier
from dvs_ai.services.research_governance_audit_bundle import ResearchGovernanceAuditBundleService
from tests.test_v420k_research_governance_audit_bundle import _fixtures


def _bundle(tmp_path: Path) -> Path:
    workspace, reviews, ledger = _fixtures(tmp_path)
    output = tmp_path / "audit.zip"
    ResearchGovernanceAuditBundleService(str(workspace), str(reviews), str(ledger)).export_bundle(str(output))
    return output


def _rewrite(source: Path, destination: Path, transform):
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as dst:
        for name in src.namelist():
            dst.writestr(name, transform(name, src.read(name)))


def test_valid_bundle_verifies_without_importing_data(tmp_path):
    bundle = _bundle(tmp_path)
    before = set(tmp_path.iterdir())
    report = IndependentAuditBundleVerifier().verify(str(bundle))
    assert report["valid"] is True
    assert report["status"] == "VERIFIED"
    assert report["manifest_status"] == report["engine_status"] == report["payload_status"] == "PASS"
    assert report["boundary"]["data_import"] is False
    assert set(tmp_path.iterdir()) == before


def test_missing_payload_is_detected(tmp_path):
    bundle = _bundle(tmp_path)
    missing = tmp_path / "missing.zip"
    with zipfile.ZipFile(bundle) as src, zipfile.ZipFile(missing, "w") as dst:
        for name in src.namelist():
            if name != "reports/governance_coverage.json":
                dst.writestr(name, src.read(name))
    report = IndependentAuditBundleVerifier().verify(str(missing))
    assert report["valid"] is False
    assert report["payload_status"] == "FAIL"
    assert any("Missing payload" in error for error in report["errors"])


def test_tampered_payload_is_detected(tmp_path):
    bundle = _bundle(tmp_path)
    tampered = tmp_path / "tampered.zip"
    _rewrite(bundle, tampered, lambda name, data: data + b"tamper" if name == "index.html" else data)
    report = IndependentAuditBundleVerifier().verify(str(tampered))
    assert report["valid"] is False
    assert any("Checksum mismatch" in error for error in report["errors"])


def test_invalid_manifest_hash_is_detected(tmp_path):
    bundle = _bundle(tmp_path)
    invalid = tmp_path / "invalid_manifest.zip"
    def mutate(name, data):
        if name != "manifest.json":
            return data
        manifest = json.loads(data)
        manifest["bundle_version"] = "tampered"
        return json.dumps(manifest).encode()
    _rewrite(bundle, invalid, mutate)
    report = IndependentAuditBundleVerifier().verify(str(invalid))
    assert report["valid"] is False
    assert report["manifest_status"] == "FAIL"
    assert any("Manifest SHA-256 mismatch" in error for error in report["errors"])


def test_engine_md5_mismatch_is_detected_even_with_resealed_manifest(tmp_path):
    bundle = _bundle(tmp_path)
    mismatch = tmp_path / "engine_mismatch.zip"
    def mutate(name, data):
        if name != "manifest.json":
            return data
        manifest = json.loads(data)
        manifest["engine_md5"] = "0" * 32
        from dvs_ai.services.audit_bundle_verifier import _canonical, _sha256_bytes
        manifest["manifest_sha256"] = _sha256_bytes(_canonical({k: v for k, v in manifest.items() if k != "manifest_sha256"}))
        return json.dumps(manifest, sort_keys=True).encode()
    _rewrite(bundle, mismatch, mutate)
    report = IndependentAuditBundleVerifier().verify(str(mismatch))
    assert report["manifest_status"] == "PASS"
    assert report["engine_status"] == "FAIL"
    assert report["valid"] is False


def test_verification_report_exports_json_and_html(tmp_path):
    report = IndependentAuditBundleVerifier().verify(str(_bundle(tmp_path)))
    service = IndependentAuditBundleVerifier()
    json_path = Path(service.export_json(report, str(tmp_path / "verification")))
    html_path = Path(service.export_html(report, str(tmp_path / "verification")))
    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "VERIFIED"
    html_text = html_path.read_text(encoding="utf-8")
    assert "Read-only verification only" in html_text
    assert "VERIFIED" in html_text
