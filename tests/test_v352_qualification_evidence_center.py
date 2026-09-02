from __future__ import annotations

import json
from dataclasses import replace

from dvs_ai.services.core_shadow_agreement_service import (
    AGREEMENT_FULL,
    CoreShadowAgreementStore,
    ShadowAgreementObservation,
)


def _observation(request_id: str = "req-1") -> ShadowAgreementObservation:
    return ShadowAgreementObservation(
        request_id=request_id,
        symbol="BTC/USDT",
        analysis_revision=7,
        legacy_action="BUY",
        unified_action="BUY",
        agreement=AGREEMENT_FULL,
        ledger_verified=True,
        synthetic_lifecycle=True,
        confidence=72.5,
        regime="TREND",
        phase="MARKUP",
        timeframe="15m",
        reason_codes=("GUI_SHADOW_LONG_SCORE_DOMINANT", "GUI_SHADOW_OBSERVE_ONLY"),
        ledger_hash="abc123",
        authorized=True,
        risk_allowed=False,
        quantity=0.0,
        event_names=("market.snapshot.accepted", "scientific.decision.created"),
        observed_at="2026-07-20T05:00:00+00:00",
    )


def test_new_evidence_is_sealed_and_verifiable(tmp_path):
    store = CoreShadowAgreementStore(tmp_path / "evidence.sqlite3")
    assert store.append(_observation()) is True
    record = store.get_evidence("req-1")
    assert record is not None
    assert record.integrity_status == "PASS"
    assert len(record.evidence_hash) == 64
    assert record.reason_codes[0] == "GUI_SHADOW_LONG_SCORE_DOMINANT"
    assert record.quantity == 0.0


def test_tampering_is_detected(tmp_path):
    store = CoreShadowAgreementStore(tmp_path / "evidence.sqlite3")
    store.append(_observation())
    with store._connect() as connection:
        connection.execute(
            "UPDATE core_shadow_agreement_observations SET confidence = 99 WHERE request_id = 'req-1'"
        )
    assert store.get_evidence("req-1").integrity_status == "FAILED"


def test_filters_and_exports_are_read_only(tmp_path):
    store = CoreShadowAgreementStore(tmp_path / "evidence.sqlite3")
    store.append(_observation("req-btc"))
    store.append(replace(_observation("req-eth"), symbol="ETH/USDT"))
    assert [r.request_id for r in store.list_evidence(symbol="BTC")] == ["req-btc"]

    json_path = tmp_path / "evidence.json"
    csv_path = tmp_path / "evidence.csv"
    assert store.export_evidence_json(json_path, limit=100) == 2
    assert store.export_evidence_csv(csv_path, limit=100) == 2
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(payload) == 2
    assert "evidence_hash" in payload[0]
    assert "request_id" in csv_path.read_text(encoding="utf-8-sig")


def test_gui_contains_read_only_evidence_center():
    source = open("dvs_ai/ui/main_window.py", encoding="utf-8").read()
    assert "QUALIFICATION EVIDENCE CENTER · READ ONLY" in source
    assert "export_evidence_json" in source
    assert "export_evidence_csv" in source
    assert "switch_authority" not in source
