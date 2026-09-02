from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import sys
import types

# The audit container does not ship ccxt; the provider only instantiates it for
# compatibility and the adversarial tests exercise the classified REST path.
if "ccxt" not in sys.modules:
    ccxt_stub = types.ModuleType("ccxt")
    ccxt_stub.binance = lambda *args, **kwargs: object()
    sys.modules["ccxt"] = ccxt_stub

from dvs_ai.data.binance_provider import (
    BinanceFuturesProvider,
    BoundedRetry,
    ProviderOperationDeadlineExceeded,
)
from dvs_ai.services.stage_boundary_telemetry import StageBoundaryTelemetry


class FakeResponse:
    def __init__(self, status_code=200, headers=None, payload=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload if payload is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        if not self.responses:
            raise AssertionError("unexpected request")
        return self.responses.pop(0)


def test_a_bounded_retry_caps_300_seconds():
    retry = BoundedRetry(total=3, retry_after_cap_seconds=30.0)
    response = SimpleNamespace(headers={"Retry-After": "300"})
    assert retry.get_retry_after(response) == 30.0


def test_b_get_deadline_is_total_budget(monkeypatch, tmp_path):
    provider = BinanceFuturesProvider(
        operation_deadline_seconds=1.0,
        snapshot_deadline_seconds=1.0,
        retry_after_cap_seconds=30.0,
        cache_ttl_seconds=0.001,
    )
    fake = FakeSession([FakeResponse(429, {"Retry-After": "300"})] * 10)
    monkeypatch.setattr(provider, "_session", lambda: fake)

    # Avoid a real one-second sleep while still consuming the actual deadline.
    original_sleep = time.sleep
    monkeypatch.setattr("dvs_ai.data.binance_provider.time.sleep", lambda seconds: original_sleep(min(seconds, 1.05)))

    started = time.monotonic()
    with pytest.raises(ProviderOperationDeadlineExceeded):
        provider._get(
            "/test",
            {},
            cache_ttl=0,
            symbol="TEST/USDT:USDT",
            phase="ticker",
        )
    elapsed = time.monotonic() - started
    assert elapsed < 1.5
    assert fake.calls <= 2


def test_c_fetch_snapshot_fails_fast_and_skips_later_phases(monkeypatch):
    provider = BinanceFuturesProvider(
        operation_deadline_seconds=0.15,
        snapshot_deadline_seconds=0.15,
        retry_after_cap_seconds=0.15,
        cache_ttl_seconds=0.001,
    )
    calls = []

    def fake_get(path, params, **kwargs):
        calls.append(kwargs.get("phase"))
        if kwargs.get("phase") == "premium":
            raise ProviderOperationDeadlineExceeded("premium deadline")
        return {
            "lastPrice": "1",
            "priceChangePercent": "0",
            "quoteVolume": "100",
            "markPrice": "1",
            "lastFundingRate": "0",
            "openInterest": "1",
        }

    monkeypatch.setattr(provider, "_get", fake_get)
    with pytest.raises(ProviderOperationDeadlineExceeded):
        provider.fetch_snapshot("TEST/USDT:USDT")
    assert calls == ["ticker", "premium"]


def test_d_stage_boundary_write_failure_is_counted(monkeypatch, tmp_path):
    telemetry = StageBoundaryTelemetry(tmp_path / "stage.jsonl")

    def fail_open(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "open", fail_open)
    telemetry.emit("test_event", symbol="TEST")
    counters = telemetry.snapshot_counters()
    assert counters["producer_emit_count"] == 1
    assert counters["successful_write_count"] == 0
    assert counters["write_error_count"] == 1
    assert counters["last_error_type"] == "PermissionError"


def test_future_runtime_uses_execution_start_not_submit_time():
    # Importing this module also validates the actual implementation contract.
    from dvs_ai.runtime.future_lifecycle import FutureIdentity, FutureRuntime, orphan_threshold

    identity = FutureIdentity("cycle", 0, "TEST")
    runtime = FutureRuntime(identity=identity, submitted_at=time.monotonic() - 10.0)
    assert runtime.state == "QUEUED"
    assert runtime.started_at is None
    dispatch_ms = runtime.mark_started()
    assert runtime.state == "RUNNING"
    assert dispatch_ms >= 9000
    assert orphan_threshold(1) == 1
    assert orphan_threshold(2) == 2
    assert orphan_threshold(3) == 2
    assert orphan_threshold(6) == 3


def test_d_stale_and_quarantined_results_are_distinct():
    from dvs_ai.runtime.future_lifecycle import FutureIdentity, classify_result_identity

    stale = FutureIdentity("old-cycle", 2, "A")
    quarantined = FutureIdentity("current", 1, "B")
    current = FutureIdentity("current", 2, "C")
    assert classify_result_identity(
        stale, current_scan_cycle_id="current", current_executor_generation=2
    ) == "STALE_FUTURE_RESULT_DISCARDED"
    assert classify_result_identity(
        quarantined, current_scan_cycle_id="current", current_executor_generation=2
    ) == "QUARANTINED_EXECUTOR_RESULT_DISCARDED"
    assert classify_result_identity(
        current, current_scan_cycle_id="current", current_executor_generation=2
    ) is None
