from pathlib import Path

from dvs_ai.governance.paper_authority_handover import (
    FROZEN_PAPER_AUTHORITY_HANDOVER_PROFILE,
)
from dvs_ai.services.core_shadow_agreement_service import (
    AGREEMENT_CONSERVATIVE,
    AGREEMENT_FULL,
    AGREEMENT_UNSAFE,
    CoreShadowAgreementStore,
    ShadowAgreementObservation,
    classify_agreement,
)


def test_agreement_classification_preserves_safety_direction():
    assert classify_agreement("BUY", "BUY") == AGREEMENT_FULL
    assert classify_agreement("BUY", "NO_ACTION") == AGREEMENT_CONSERVATIVE
    assert classify_agreement("NO_ACTION", "BUY") == AGREEMENT_UNSAFE


def test_store_is_idempotent_and_counts_profile_metrics(tmp_path: Path):
    store = CoreShadowAgreementStore(tmp_path / "agreement.sqlite3")
    observation = ShadowAgreementObservation(
        request_id="request-1",
        symbol="BTC/USDT:USDT",
        analysis_revision=1,
        legacy_action="NO_ACTION",
        unified_action="NO_ACTION",
        agreement=AGREEMENT_FULL,
        ledger_verified=True,
    )
    assert store.append(observation) is True
    assert store.append(observation) is False
    metrics = store.metrics()
    assert metrics.total_cycles == 1
    assert metrics.full_agreements == 1
    assert metrics.full_agreement_ratio == 1.0
    assert metrics.qualification_status == "COLLECTING"
    assert metrics.profile_hash == FROZEN_PAPER_AUTHORITY_HANDOVER_PROFILE.profile_hash


def test_unsafe_divergence_blocks_qualification(tmp_path: Path):
    store = CoreShadowAgreementStore(tmp_path / "agreement.sqlite3")
    store.append(
        ShadowAgreementObservation(
            request_id="unsafe-1",
            symbol="ETH/USDT:USDT",
            analysis_revision=2,
            legacy_action="NO_ACTION",
            unified_action="BUY",
            agreement=AGREEMENT_UNSAFE,
            ledger_verified=True,
        )
    )
    metrics = store.metrics()
    assert metrics.unsafe_divergences == 1
    assert metrics.qualification_status == "BLOCKED_UNSAFE_DIVERGENCE"


def test_main_window_labels_synthetic_ledger_and_records_metrics():
    source = Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")
    assert "VERIFIED (synthetic)" in source
    assert "ShadowAgreementObservation" in source
    assert "Qualification:" in source
    assert "Paper authority: LEGACY" in source
