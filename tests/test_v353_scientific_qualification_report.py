from __future__ import annotations

import json

from dvs_ai.services.core_shadow_agreement_service import (
    AGREEMENT_FULL, CoreShadowAgreementStore, ShadowAgreementObservation,
)
from dvs_ai.services.qualification_report_service import QualificationReportService


def _obs() -> ShadowAgreementObservation:
    return ShadowAgreementObservation(
        request_id="r-353", symbol="BTC/USDT", analysis_revision=1,
        legacy_action="BUY", unified_action="BUY", agreement=AGREEMENT_FULL,
        ledger_verified=True, synthetic_lifecycle=True, confidence=72.0,
        regime="TREND", phase="MARKUP", timeframe="15m",
        reason_codes=("TREND_PASS",), ledger_hash="abc", authorized=True,
        risk_allowed=False, quantity=0.0, event_names=("scientific.decision.created",),
        observed_at="2026-07-20T00:00:00+00:00",
    )


def test_report_exports_json_html_pdf_without_authority_switch(tmp_path):
    store = CoreShadowAgreementStore(tmp_path / "q.sqlite3")
    store.append(_obs())
    service = QualificationReportService(store, build_version="3.5.3")
    snap = service.build_snapshot()
    assert snap.paper_authority == "LEGACY"
    assert snap.total_cycles == 1
    assert snap.governance_recommendation == "NOT_READY"
    jp = service.export_json(tmp_path / "report.json")
    hp = service.export_html(tmp_path / "report.html")
    pp = service.export_pdf(tmp_path / "report.pdf")
    assert json.loads(jp.read_text(encoding="utf-8"))["safety_boundary"]["automatic_promotion"] is False
    assert "Paper Authority remains LEGACY" in hp.read_text(encoding="utf-8")
    assert pp.read_bytes().startswith(b"%PDF-1.4")


def test_gui_wires_scientific_report_read_only():
    source = open("dvs_ai/ui/main_window.py", encoding="utf-8").read()
    assert "Scientific Report" in source
    assert "QualificationReportService" in source
    assert "switch_authority" not in source
