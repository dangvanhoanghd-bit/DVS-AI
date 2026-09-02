from pathlib import Path

from dvs_ai.governance.paper_authority_handover import (
    FROZEN_PAPER_AUTHORITY_HANDOVER_PROFILE,
    PaperAuthorityHandoverProfile,
)
from dvs_ai.ui.shadow_core_runtime import build_gui_shadow_core_runtime


def test_handover_profile_is_frozen_before_shadow_metrics():
    profile = FROZEN_PAPER_AUTHORITY_HANDOVER_PROFILE
    assert isinstance(profile, PaperAuthorityHandoverProfile)
    assert profile.minimum_parallel_cycles == 500
    assert profile.minimum_full_agreement_ratio == 0.85
    assert profile.maximum_unsafe_divergences == 0
    assert profile.require_unified_not_more_aggressive is True
    assert profile.required_approvals == 2
    assert len(profile.profile_hash) == 64


def test_main_window_wires_adapter_but_not_core_capabilities():
    source = Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")
    assert "CoreRuntimeAdapter" in source
    assert "run_cycle_async" in source
    assert "submit_order" not in source
    assert "place_order" not in source
    assert "open_position" not in source
    assert "Paper authority: LEGACY" in source


def test_app_injects_isolated_shadow_runtime():
    source = Path("dvs_ai/app.py").read_text(encoding="utf-8")
    assert "build_gui_shadow_core_runtime" in source
    assert "core_runtime_adapter=core_runtime_adapter" in source


def test_shadow_runtime_has_no_exchange_or_application_paper_service():
    runtime = build_gui_shadow_core_runtime()
    public = {name for name in dir(runtime) if not name.startswith("_")}
    assert "run_cycle" in public
    assert "exchange" not in public
    assert "paper_trade_service" not in public
