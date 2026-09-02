from pathlib import Path

from dvs_ai.services.core_shadow_agreement_service import (
    AGREEMENT_CONSERVATIVE,
    AGREEMENT_FULL,
    AGREEMENT_UNSAFE,
    AgreementResult,
    classify_agreement,
    classify_agreement_result,
)
from dvs_ai.version import APP_VERSION, APP_EDITION


def test_canonical_agreement_value_object_drives_code_and_display():
    full = classify_agreement_result("BUY", "BUY")
    conservative = classify_agreement_result("BUY", "NO_ACTION")
    unsafe = classify_agreement_result("NO_ACTION", "SELL")

    assert isinstance(full, AgreementResult)
    assert full.code == AGREEMENT_FULL
    assert full.display == "FULL"
    assert full.severity == "SAFE"
    assert conservative.code == AGREEMENT_CONSERVATIVE
    assert "MORE CONSERVATIVE" in conservative.display
    assert unsafe.code == AGREEMENT_UNSAFE
    assert unsafe.is_unsafe is True
    assert unsafe.severity == "BLOCKED"


def test_legacy_code_only_facade_uses_canonical_classifier():
    assert classify_agreement("BUY", "NO_ACTION") == classify_agreement_result(
        "BUY", "NO_ACTION"
    ).code


def test_gui_has_no_inline_duplicate_agreement_classification():
    source = Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")
    render = source[source.index("def _render_core_shadow_comparison"):source.index("def _render_shadow_qualification_dashboard")]
    assert "classify_agreement_result(legacy, unified)" in render
    assert 'legacy == "NO_ACTION" and unified in actionable' not in render
    assert "agreement_result.display" in render
    assert "agreement_result.severity" in render


def test_qualification_dashboard_is_observe_only_and_profile_visible():
    source = Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")
    assert "SHADOW QUALIFICATION · FROZEN GOVERNANCE PROFILE" in source
    assert "PAPER AUTHORITY: LEGACY" in source
    assert "core_qualification_progress" in source
    assert "profile_hash[:12]" in source
    for forbidden in ("switch_authority(", "promote_authority(", "activate_handover("):
        assert forbidden not in source


def test_build_identity_updated():
    assert APP_VERSION == __import__("dvs_ai").__version__
    assert APP_EDITION
