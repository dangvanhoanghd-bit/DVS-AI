from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from dvs_ai.services.audit_bundle_verifier import IndependentAuditBundleVerifier
from dvs_ai.services.outcome_analytics import OutcomeAnalyticsService
from dvs_ai.services.outcome_infrastructure import OutcomeInfrastructureStore
from dvs_ai.services.research_governance_audit_bundle import ResearchGovernanceAuditBundleService
from dvs_ai.services.research_review_workflow import ResearchReviewWorkflowService
from tests.test_v420g_research_review_workflow import seed_workspace
from tests.test_v420k_research_governance_audit_bundle import _fixtures


def test_outcome_analytics_connection_is_sqlite_enforced_read_only(tmp_path, monkeypatch):
    store = OutcomeInfrastructureStore(tmp_path / "paper.db")
    service = OutcomeAnalyticsService(store)
    original_connect = sqlite3.connect
    observed = {}

    def checking_connect(database, *args, **kwargs):
        observed["database"] = str(database)
        observed["uri"] = kwargs.get("uri")
        connection = original_connect(database, *args, **kwargs)
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("CREATE TABLE forbidden_write(x INTEGER)")
        return connection

    monkeypatch.setattr(sqlite3, "connect", checking_connect)
    service._rows()
    assert "mode=ro" in observed["database"]
    assert observed["uri"] is True


def test_strict_verification_fails_on_unlisted_archive_member(tmp_path):
    workspace, reviews, ledger = _fixtures(tmp_path)
    original = tmp_path / "audit.zip"
    ResearchGovernanceAuditBundleService(str(workspace), str(reviews), str(ledger)).export_bundle(str(original))
    modified = tmp_path / "audit_extra.zip"
    with zipfile.ZipFile(original) as src, zipfile.ZipFile(modified, "w", compression=zipfile.ZIP_DEFLATED) as dst:
        for name in src.namelist():
            dst.writestr(name, src.read(name))
        dst.writestr("external_notes.txt", b"auditor note")
    normal = IndependentAuditBundleVerifier(strict=False).verify(str(modified))
    strict = IndependentAuditBundleVerifier(strict=True).verify(str(modified))
    assert normal["valid"] is True
    assert normal["warnings"]
    assert normal["verification_mode"] == "NORMAL"
    assert strict["valid"] is False
    assert strict["verification_mode"] == "STRICT"
    assert any("strict mode" in item for item in strict["errors"])


def test_database_target_uses_level_2_independent_verification(tmp_path):
    workspace = tmp_path / "workspace.db"
    reviews = tmp_path / "reviews.db"
    seed_workspace(workspace)
    service = ResearchReviewWorkflowService(str(workspace), str(reviews))
    review_id = service.create_review("EXPERIMENT", "e1", "auditor")
    integrity = service.verify_target_integrity(review_id)
    assert integrity["matches"] is True
    assert integrity["integrity_level"] == 2
    assert integrity["independently_verifiable"] is True


def test_report_target_is_not_given_tautological_pass(tmp_path):
    workspace = tmp_path / "workspace.db"
    reviews = tmp_path / "reviews.db"
    seed_workspace(workspace)
    service = ResearchReviewWorkflowService(str(workspace), str(reviews))
    review_id = service.create_review("LINEAGE_REPORT", "a" * 64, "auditor")
    integrity = service.verify_target_integrity(review_id)
    assert integrity["matches"] is None
    assert integrity["integrity_level"] == 1
    assert integrity["independently_verifiable"] is False
    assert integrity["status"] == "UNVERIFIABLE_WITHOUT_SOURCE_ARTIFACT"


def test_audit_bundle_manifest_contains_assurance_metadata(tmp_path):
    workspace, reviews, ledger = _fixtures(tmp_path)
    output = tmp_path / "audit.zip"
    result = ResearchGovernanceAuditBundleService(str(workspace), str(reviews), str(ledger)).export_bundle(str(output))
    assurance = result["manifest"]["audit_assurance"]
    assert assurance["baseline_release"] == "4.2.0-L"
    assert assurance["hardening_release"] == "4.2.1"
    assert assurance["known_design_limitations_documented"] is True


def test_audit_register_and_limitations_are_machine_readable():
    root = Path(__file__).resolve().parents[1]
    register = json.loads((root / "audit_register.json").read_text(encoding="utf-8"))
    assert register["release"] == "4.2.1"
    assert register["decision_engine_md5"] == "72cf7d54e1ed6369400683358da8c0ef"
    assert "manifest self-sealing" in (root / "KNOWN_DESIGN_LIMITATIONS.md").read_text(encoding="utf-8")
