from __future__ import annotations

import time
from types import ModuleType, SimpleNamespace
import sys

import pandas as pd
import pytest

ccxt_stub = ModuleType("ccxt")
ccxt_stub.binance = lambda *args, **kwargs: None
sys.modules.setdefault("ccxt", ccxt_stub)
sys.modules.setdefault("pandas_ta", ModuleType("pandas_ta"))

from dvs_ai.data.binance_provider import (
    BinanceFuturesProvider,
    DataProviderError,
)


def test_classifies_network_timeout():
    import requests

    error = BinanceFuturesProvider.classify_exception(
        requests.Timeout("slow")
    )
    assert error.code == "NETWORK_TIMEOUT"
    assert error.retryable


def test_cache_is_bounded_and_expires():
    provider = BinanceFuturesProvider(
        cache_ttl_seconds=1.0,
        cache_max_items=100,
    )
    provider._cache_put(("a",), 1, 0.01)
    assert provider._cache_get(("a",)) == 1
    time.sleep(0.02)
    assert provider._cache_get(("a",)) is None


def test_insufficient_history_is_skip(monkeypatch):
    provider = BinanceFuturesProvider()
    rows = [
        [i, "1", "2", "0.5", "1.5", "10"]
        for i in range(70)
    ]
    monkeypatch.setattr(
        provider,
        "_get",
        lambda *args, **kwargs: rows,
    )
    with pytest.raises(DataProviderError) as caught:
        provider.fetch_ohlcv("TEST/USDT:USDT", "15m", 260)
    assert caught.value.code == "INSUFFICIENT_HISTORY"
    assert caught.value.skip_only


def test_rest_ohlcv_parses_frame(monkeypatch):
    provider = BinanceFuturesProvider()
    rows = [
        [i, "1", "2", "0.5", "1.5", "10"]
        for i in range(100)
    ]
    monkeypatch.setattr(
        provider,
        "_get",
        lambda *args, **kwargs: rows,
    )
    frame = provider.fetch_ohlcv(
        "TEST/USDT:USDT",
        "15m",
        100,
    )
    assert isinstance(frame, pd.DataFrame)
    assert len(frame) == 100
    assert list(frame.columns) == [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]


def test_worker_source_uses_bounded_executor():
    source = open(
        "dvs_ai/ui/main_window.py",
        encoding="utf-8",
    ).read()
    assert "ThreadPoolExecutor" in source
    assert "max_workers=self.config.scan_workers" in source
    assert "FIRST_COMPLETED" in source
