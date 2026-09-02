from __future__ import annotations
import logging
import threading
import time
from collections import OrderedDict
from typing import Any
import ccxt
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

from dvs_ai.runtime.deadline_budget import DeadlineBudget, DeadlineExceeded
from dvs_ai.runtime.provider_circuit import (
    GLOBAL_PROVIDER_CIRCUIT, ProviderCircuitShortCircuited, CircuitPermit,
)
from dvs_ai.services.provider_evidence_telemetry import PROVIDER_EVIDENCE

from dvs_ai.domain.models import MarketSnapshot

log = logging.getLogger(__name__)


class DataProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        skip_only: bool = False,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.retryable = retryable
        self.skip_only = skip_only


class ProviderOperationDeadlineExceeded(DataProviderError):
    def __init__(self, message: str) -> None:
        super().__init__("PROVIDER_OPERATION_DEADLINE_EXCEEDED", message, retryable=True)


class BoundedRetry(Retry):
    """Retry helper that caps server-supplied Retry-After values."""
    def __init__(self, *args, retry_after_cap_seconds: float = 30.0, **kwargs) -> None:
        self.retry_after_cap_seconds = max(0.0, float(retry_after_cap_seconds))
        super().__init__(*args, **kwargs)

    def new(self, **kw):
        kw["retry_after_cap_seconds"] = self.retry_after_cap_seconds
        return super().new(**kw)

    def get_retry_after(self, response):
        value = super().get_retry_after(response)
        if value is None:
            return None
        return min(float(value), self.retry_after_cap_seconds)


class BinanceFuturesProvider:
    BASE_URL = "https://fapi.binance.com"

    def __init__(
        self,
        timeout_seconds: int = 12,
        cache_ttl_seconds: float = 25.0,
        cache_max_items: int = 1200,
        retry_after_cap_seconds: float = 30.0,
        operation_deadline_seconds: float = 45.0,
        snapshot_deadline_seconds: float = 90.0,
    ) -> None:
        self.timeout = timeout_seconds
        self.retry_after_cap_seconds = max(0.0, float(retry_after_cap_seconds))
        self.operation_deadline_seconds = max(1.0, float(operation_deadline_seconds))
        self.snapshot_deadline_seconds = max(self.operation_deadline_seconds, float(snapshot_deadline_seconds))
        # Kept for compatibility with older call sites. OHLCV now uses the
        # classified REST path below, avoiding opaque ccxt URL-only errors.
        self.exchange = ccxt.binance({
            "enableRateLimit": True,
            "timeout": timeout_seconds * 1000,
            "options": {"defaultType": "future"},
        })
        self._local = threading.local()
        self._cache_lock = threading.RLock()
        self._cache: OrderedDict[tuple, tuple[float, Any]] = OrderedDict()
        self._cache_ttl = max(1.0, float(cache_ttl_seconds))
        self._cache_max_items = max(100, int(cache_max_items))

    @staticmethod
    def raw_symbol(symbol: str) -> str:
        return symbol.split(":")[0].replace("/", "")

    @staticmethod
    def _f(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            # Retries are performed explicitly in _get so one monotonic
            # DeadlineBudget covers request, backoff and Retry-After sleeps.
            adapter = HTTPAdapter(
                max_retries=0,
                pool_connections=12,
                pool_maxsize=12,
            )
            session.mount("https://", adapter)
            self._local.session = session
        return session

    @staticmethod
    def _cache_key(
        path: str,
        params: dict[str, Any],
    ) -> tuple:
        return (
            path,
            tuple(sorted((str(k), str(v)) for k, v in params.items())),
        )

    def _cache_get(self, key: tuple) -> Any | None:
        now = time.monotonic()
        with self._cache_lock:
            item = self._cache.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at <= now:
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            return value

    def _cache_put(
        self,
        key: tuple,
        value: Any,
        ttl: float,
    ) -> None:
        with self._cache_lock:
            self._cache[key] = (
                time.monotonic()+max(0.001, float(ttl)),
                value,
            )
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_max_items:
                self._cache.popitem(last=False)

    def clear_expired_cache(self) -> int:
        now = time.monotonic()
        removed = 0
        with self._cache_lock:
            for key, (expires_at, _) in list(self._cache.items()):
                if expires_at <= now:
                    self._cache.pop(key, None)
                    removed += 1
        return removed

    @staticmethod
    def classify_exception(exc: Exception) -> DataProviderError:
        if isinstance(exc, DataProviderError):
            return exc
        if isinstance(exc, requests.Timeout):
            return DataProviderError(
                "NETWORK_TIMEOUT",
                str(exc),
                retryable=True,
            )
        if isinstance(exc, requests.ConnectionError):
            return DataProviderError(
                "NETWORK_CONNECTION",
                str(exc),
                retryable=True,
            )
        if isinstance(exc, requests.HTTPError):
            status = getattr(exc.response, "status_code", None)
            if status == 429:
                code = "RATE_LIMIT_429"
                retryable = True
            elif status == 418:
                code = "IP_BANNED_418"
                retryable = True
            elif status == 451:
                code = "REGION_RESTRICTED_451"
                retryable = False
            elif status in (400, 404):
                code = "SYMBOL_OR_REQUEST_INVALID"
                retryable = False
            elif status and status >= 500:
                code = f"BINANCE_HTTP_{status}"
                retryable = True
            else:
                code = f"HTTP_{status or 'UNKNOWN'}"
                retryable = False
            return DataProviderError(
                code,
                str(exc),
                retryable=retryable,
            )
        return DataProviderError(
            "DATA_PROVIDER_ERROR",
            str(exc),
            retryable=False,
        )

    @staticmethod
    def _retry_after_seconds(response: requests.Response) -> float | None:
        raw = response.headers.get("Retry-After")
        if raw is None:
            return None
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            try:
                when = parsedate_to_datetime(str(raw))
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
            except Exception:
                return None

    def _get(
        self,
        path: str,
        params: dict[str, Any],
        *,
        cache_ttl: float | None = None,
        deadline: DeadlineBudget | None = None,
        symbol: str = "",
        phase: str = "request",
    ) -> Any:
        ttl = self._cache_ttl if cache_ttl is None else float(cache_ttl)
        key = self._cache_key(path, params)
        if ttl > 0:
            cached = self._cache_get(key)
            if cached is not None:
                return cached

        permit = GLOBAL_PROVIDER_CIRCUIT.before_request(endpoint=path, phase=phase, symbol=symbol)
        operation = deadline.child(self.operation_deadline_seconds, label=f"{phase}:{symbol or path}") if deadline else DeadlineBudget.start(self.operation_deadline_seconds, label=f"{phase}:{symbol or path}")
        started = time.monotonic()
        last_exc: Exception | None = None
        retryable_status = {418, 429, 500, 502, 503, 504}
        max_attempts = 4
        outcome = "error"
        try:
            for attempt in range(1, max_attempts + 1):
                try:
                    operation.raise_if_expired()
                except DeadlineExceeded as exc:
                    raise ProviderOperationDeadlineExceeded(str(exc)) from exc
                remaining = operation.remaining()
                connect_timeout = max(0.05, min(4.0, remaining))
                read_timeout = max(0.05, min(float(self.timeout), remaining))
                try:
                    response = self._session().get(
                        f"{self.BASE_URL}{path}",
                        params=params,
                        timeout=(connect_timeout, read_timeout),
                    )
                    status = int(response.status_code)
                    if status not in retryable_status:
                        response.raise_for_status()
                        data = response.json()
                        if ttl > 0:
                            self._cache_put(key, data, ttl)
                        outcome = "success"
                        GLOBAL_PROVIDER_CIRCUIT.on_success(
                            permit=permit, endpoint=path, phase=phase, symbol=symbol
                        )
                        return data
                    last_exc = requests.HTTPError(f"HTTP {status}", response=response)
                    raw_retry_after = self._retry_after_seconds(response)
                    if status in (418, 429):
                        GLOBAL_PROVIDER_CIRCUIT.observe_rate_limit(
                            status_code=status, retry_after_raw_seconds=raw_retry_after,
                            endpoint=path, phase=phase, symbol=symbol, permit=permit,
                        )
                        raise self.classify_exception(last_exc)
                    if attempt >= max_attempts:
                        raise last_exc
                    exponential = 0.45 * (2 ** max(0, attempt - 1))
                    requested_sleep = raw_retry_after if raw_retry_after is not None else exponential
                    applied_sleep = min(requested_sleep, self.retry_after_cap_seconds, operation.remaining())
                    PROVIDER_EVIDENCE.emit(
                        "provider_retry", symbol=symbol, phase=phase, endpoint=path,
                        status_code=status, attempt=attempt, retry_after_raw=response.headers.get("Retry-After"),
                        retry_after_applied_seconds=round(applied_sleep, 3),
                        elapsed_ms=round((time.monotonic()-started)*1000.0, 3),
                    )
                    if applied_sleep <= 0:
                        raise ProviderOperationDeadlineExceeded(f"{phase} deadline exceeded before retry")
                    time.sleep(applied_sleep)
                except (requests.Timeout, requests.ConnectionError) as exc:
                    last_exc = exc
                    if attempt >= max_attempts:
                        raise
                    applied_sleep = min(0.45 * (2 ** max(0, attempt - 1)), operation.remaining())
                    PROVIDER_EVIDENCE.emit(
                        "provider_retry", symbol=symbol, phase=phase, endpoint=path,
                        status_code=None, attempt=attempt, retry_after_raw=None,
                        retry_after_applied_seconds=round(applied_sleep, 3),
                        error_type=type(exc).__name__, elapsed_ms=round((time.monotonic()-started)*1000.0, 3),
                    )
                    if applied_sleep <= 0:
                        raise ProviderOperationDeadlineExceeded(f"{phase} deadline exceeded before retry") from exc
                    time.sleep(applied_sleep)
            raise last_exc or RuntimeError("request failed")
        except ProviderCircuitShortCircuited:
            outcome = "short_circuited"
            raise
        except ProviderOperationDeadlineExceeded:
            outcome = "deadline_exceeded"
            raise
        except DeadlineExceeded as exc:
            outcome = "deadline_exceeded"
            raise ProviderOperationDeadlineExceeded(str(exc)) from exc
        except Exception as exc:
            if operation.expired():
                outcome = "deadline_exceeded"
                raise ProviderOperationDeadlineExceeded(f"{phase} deadline exceeded") from exc
            raise self.classify_exception(exc) from exc
        finally:
            PROVIDER_EVIDENCE.emit(
                "provider_operation_finished", symbol=symbol, phase=phase, endpoint=path,
                outcome=outcome, total_elapsed_ms=round((time.monotonic()-started)*1000.0, 3),
                remaining_ms=round(operation.remaining()*1000.0, 3),
            )

    def health_check(self) -> tuple[bool, str]:
        try:
            data = self._get("/fapi/v1/time", {})
            return (isinstance(data, dict) and "serverTime" in data, "Binance Futures API hoạt động")
        except Exception as exc:
            return False, f"Không kết nối được Binance: {exc}"


    def discover_usdt_perpetuals(
        self,
        limit: int = 120,
        min_quote_volume: float = 20_000_000,
    ) -> list[str]:
        """
        Lấy danh sách hợp đồng USDT perpetual đang giao dịch và xếp theo
        quote volume 24h. Chỉ dùng 2 API calls cho toàn universe.
        """
        exchange_info = self._get("/fapi/v1/exchangeInfo", {})
        tickers = self._get("/fapi/v1/ticker/24hr", {})

        valid = set()
        for item in exchange_info.get("symbols", []):
            if (
                item.get("status") == "TRADING"
                and item.get("contractType") == "PERPETUAL"
                and item.get("quoteAsset") == "USDT"
            ):
                valid.add(str(item.get("symbol", "")).upper())

        ranked = []
        for ticker in tickers if isinstance(tickers, list) else []:
            raw_symbol = str(ticker.get("symbol", "")).upper()
            quote_volume = self._f(ticker.get("quoteVolume"))
            last_price = self._f(ticker.get("lastPrice"))
            if (
                raw_symbol in valid
                and quote_volume >= float(min_quote_volume)
                and last_price > 0
            ):
                ranked.append((quote_volume, raw_symbol))

        ranked.sort(reverse=True)
        symbols = [
            f"{raw_symbol[:-4]}/USDT:USDT"
            for _, raw_symbol in ranked[: max(1, int(limit))]
            if raw_symbol.endswith("USDT")
        ]

        # BTC luôn có mặt để xây Market Brief.
        btc = "BTC/USDT:USDT"
        if btc in symbols:
            symbols.remove(btc)
        return [btc] + symbols[: max(0, int(limit) - 1)]

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
    ) -> pd.DataFrame:
        raw = self.raw_symbol(symbol)
        rows = self._get(
            "/fapi/v1/klines",
            {
                "symbol": raw,
                "interval": timeframe,
                "limit": min(1500, max(80, int(limit))),
            },
            cache_ttl=max(
                self._cache_ttl,
                20.0 if timeframe == "15m" else 45.0,
            ),
        )
        if not isinstance(rows, list) or not rows:
            raise DataProviderError(
                "NO_OHLCV_DATA",
                f"{symbol} {timeframe}",
                skip_only=True,
            )
        parsed = [
            (
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
            )
            for row in rows
            if isinstance(row, list) and len(row) >= 6
        ]
        df = pd.DataFrame(
            parsed,
            columns=(
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ),
        )
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna().reset_index(drop=True)
        if len(df) < 80:
            raise DataProviderError(
                "INSUFFICIENT_HISTORY",
                (
                    f"{symbol} {timeframe}: {len(df)} nến, "
                    "cần tối thiểu 80"
                ),
                skip_only=True,
            )
        return df

    def fetch_snapshot(self, symbol: str) -> MarketSnapshot:
        raw = self.raw_symbol(symbol)
        deadline = DeadlineBudget.start(self.snapshot_deadline_seconds, label=f"snapshot:{symbol}")

        def request(path: str, params: dict[str, Any], *, phase: str, cache_ttl: float | None = None):
            deadline.raise_if_expired()
            return self._get(path, params, cache_ttl=cache_ttl, deadline=deadline, symbol=symbol, phase=phase)

        try:
            ticker = request("/fapi/v1/ticker/24hr", {"symbol": raw}, phase="ticker", cache_ttl=15.0)
            premium = request("/fapi/v1/premiumIndex", {"symbol": raw}, phase="premium", cache_ttl=20.0)
            oi = request("/fapi/v1/openInterest", {"symbol": raw}, phase="oi", cache_ttl=15.0)

            def oi_change(period: str) -> float:
                phase = f"oi_change_{period}"
                try:
                    hist = request(
                        "/futures/data/openInterestHist",
                        {"symbol": raw, "period": period, "limit": 2},
                        phase=phase,
                    )
                    if isinstance(hist, list) and len(hist) >= 2:
                        old = self._f(hist[-2].get("sumOpenInterest"))
                        new = self._f(hist[-1].get("sumOpenInterest"))
                        return ((new - old) / old * 100.0) if old > 0 else 0.0
                except ProviderOperationDeadlineExceeded:
                    raise
                except Exception as exc:
                    log.warning("OI history unavailable %s %s: %s", symbol, period, exc)
                return 0.0

            return MarketSnapshot(
                symbol=symbol,
                last_price=self._f(ticker.get("lastPrice")),
                mark_price=self._f(premium.get("markPrice")),
                change_24h_pct=self._f(ticker.get("priceChangePercent")),
                quote_volume_24h=self._f(ticker.get("quoteVolume")),
                funding_pct=self._f(premium.get("lastFundingRate")) * 100.0,
                open_interest=self._f(oi.get("openInterest")),
                oi_change_15m_pct=oi_change("15m"),
                oi_change_1h_pct=oi_change("1h"),
            )
        except DeadlineExceeded as exc:
            raise ProviderOperationDeadlineExceeded(str(exc)) from exc


    def fetch_order_book(
        self,
        symbol: str,
        limit: int = 100,
    ) -> dict[str, Any]:
        raw = self.raw_symbol(symbol)
        limit = min(1000, max(20, int(limit)))
        data = self._get(
            "/fapi/v1/depth",
            {"symbol": raw, "limit": limit},
        )
        return data if isinstance(data, dict) else {}

    def fetch_agg_trades(
        self,
        symbol: str,
        limit: int = 500,
        *,
        from_id: int | None = None,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch public aggregate trades with optional controlled paging.

        ``from_id`` is used by the gap backfiller. Time bounds are optional and
        are never combined with an invented force-order reconstruction.
        """
        raw = self.raw_symbol(symbol)
        params: dict[str, Any] = {
            "symbol": raw,
            "limit": min(1000, max(1, int(limit))),
        }
        if from_id is not None:
            params["fromId"] = max(0, int(from_id))
        if start_time_ms is not None:
            params["startTime"] = max(0, int(start_time_ms))
        if end_time_ms is not None:
            params["endTime"] = max(0, int(end_time_ms))
        data = self._get("/fapi/v1/aggTrades", params)
        return data if isinstance(data, list) else []

    def fetch_microstructure_raw(
        self,
        symbol: str,
        depth_limit: int = 100,
        trade_limit: int = 500,
    ) -> dict[str, Any]:
        """
        Public REST bootstrap for the Microstructure Engine.

        This is L2 depth plus recent aggregate trades, not true Level 3.
        Liquidation fields remain unavailable until the WebSocket collector
        receives force-order events.
        """
        return {
            "symbol": symbol,
            "depth": self.fetch_order_book(symbol, depth_limit),
            "agg_trades": self.fetch_agg_trades(symbol, trade_limit),
            "liquidations": [],
            "source": "BINANCE_PUBLIC_REST_BOOTSTRAP",
        }

