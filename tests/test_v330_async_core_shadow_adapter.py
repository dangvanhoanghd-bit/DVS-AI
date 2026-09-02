from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from dvs_ai.application import UnifiedCycleRequest
from dvs_ai.strategy_intelligence import MarketSnapshot
from dvs_ai.ui.core_runtime_adapter import CoreCycleRequest, CoreRuntimeAdapter


def make_request(*, request_id: str = "req-1", revision: int = 1) -> CoreCycleRequest:
    cycle = UnifiedCycleRequest(
        pipeline_run_id="run-1",
        snapshot=MarketSnapshot(
            symbol="BTC/USDT",
            timeframe="15m",
            close=100.0,
            observed_at=datetime.now(timezone.utc),
        ),
        quantity=1.0,
    )
    return CoreCycleRequest(cycle, revision, request_id=request_id)


def test_request_is_immutable_and_shadow_only():
    request = make_request()
    assert request.shadow_only is True
    assert request.symbol == "BTC/USDT"
    with pytest.raises(ValueError):
        CoreCycleRequest(request.cycle, 1, request_id="x", shadow_only=False)


def test_adapter_api_does_not_expose_execution_capabilities():
    public = {name for name in dir(CoreRuntimeAdapter) if not name.startswith("_")}
    assert "run_cycle_async" in public
    forbidden = {
        "authorize", "resize_position", "open_position", "submit_order",
        "place_order", "execute_decision", "ledger", "core",
    }
    assert public.isdisjoint(forbidden)


def test_adapter_uses_qthread_and_latest_request_wins_contract():
    source = Path("dvs_ai/ui/core_runtime_adapter.py").read_text(encoding="utf-8")
    assert "QThread" in source
    assert "moveToThread" in source
    assert "self._pending = request" in source
    assert "request.request_id != self._latest_request_id" in source
    assert "quantity=0.0" in source


def test_view_models_are_frozen():
    source = Path("dvs_ai/ui/core_runtime_adapter.py").read_text(encoding="utf-8")
    assert source.count("@dataclass(frozen=True, slots=True)") >= 3


def test_shadow_adapter_is_wired_without_exposing_core_capabilities():
    source = Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")
    assert "CoreRuntimeAdapter" in source
    assert "run_cycle_async" in source
    assert "DVSAICore" not in source
    assert "Paper authority: LEGACY" in source
