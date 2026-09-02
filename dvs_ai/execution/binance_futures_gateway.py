from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

import requests

from .models import (
    ExecutionIntent,
    ExecutionMode,
    ExecutionResult,
    OrderStatus,
)


class BinanceFuturesGateway:
    """
    Minimal USDT-M Futures gateway.

    LIVE/TESTNET are disabled unless API credentials are supplied explicitly.
    This module is not connected to Decision Engine automatically.
    """

    LIVE_URL = "https://fapi.binance.com"
    TESTNET_URL = "https://testnet.binancefuture.com"

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        mode: ExecutionMode = ExecutionMode.TESTNET,
        timeout_seconds: int = 12,
    ) -> None:
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.mode = mode
        self.timeout = max(3, int(timeout_seconds))
        self.session = requests.Session()

    @property
    def base_url(self) -> str:
        return self.LIVE_URL if self.mode == ExecutionMode.LIVE else self.TESTNET_URL

    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def _signed_request(self, method: str, path: str, params: dict):
        if not self.configured():
            raise RuntimeError("BINANCE_CREDENTIALS_NOT_CONFIGURED")
        payload = dict(params)
        payload["timestamp"] = int(time.time()*1000)
        query = urlencode(payload)
        signature = hmac.new(
            self.api_secret.encode(),
            query.encode(),
            hashlib.sha256,
        ).hexdigest()
        payload["signature"] = signature
        response = self.session.request(
            method,
            f"{self.base_url}{path}",
            params=payload,
            headers={"X-MBX-APIKEY": self.api_key},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def balance(self):
        return self._signed_request("GET", "/fapi/v2/balance", {})

    def positions(self, symbol: str | None = None):
        params = {"symbol": symbol} if symbol else {}
        return self._signed_request("GET", "/fapi/v2/positionRisk", params)

    def open_orders(self, symbol: str | None = None):
        params = {"symbol": symbol} if symbol else {}
        return self._signed_request("GET", "/fapi/v1/openOrders", params)

    def submit(self, intent: ExecutionIntent) -> ExecutionResult:
        params = {
            "symbol": intent.symbol,
            "side": intent.side.value,
            "type": intent.order_type.value,
            "quantity": f"{intent.quantity:.12f}".rstrip("0").rstrip("."),
            "newClientOrderId": intent.client_order_id,
            "reduceOnly": "true" if intent.reduce_only else "false",
        }
        if intent.price is not None:
            params["price"] = str(intent.price)
            params["timeInForce"] = "GTC"
        if intent.stop_price is not None:
            params["stopPrice"] = str(intent.stop_price)

        try:
            raw = self._signed_request("POST", "/fapi/v1/order", params)
            return ExecutionResult(
                accepted=True,
                mode=self.mode,
                status=OrderStatus.SUBMITTED,
                symbol=intent.symbol,
                client_order_id=intent.client_order_id,
                exchange_order_id=str(raw.get("orderId", "")),
                filled_quantity=float(raw.get("executedQty", 0.0) or 0.0),
                average_price=float(raw.get("avgPrice", 0.0) or 0.0),
                message="ORDER_SUBMITTED",
                raw=raw,
            )
        except Exception as exc:
            return ExecutionResult(
                accepted=False,
                mode=self.mode,
                status=OrderStatus.REJECTED,
                symbol=intent.symbol,
                client_order_id=intent.client_order_id,
                message=str(exc),
            )

    def cancel_all(self, symbol: str):
        return self._signed_request(
            "DELETE",
            "/fapi/v1/allOpenOrders",
            {"symbol": symbol},
        )
