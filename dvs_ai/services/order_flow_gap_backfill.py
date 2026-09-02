from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Protocol

from dvs_ai.services.order_flow_store import PersistentOrderFlowStore


class AggregateTradeFetcher(Protocol):
    def __call__(self, symbol: str, from_id: int, limit: int) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class GapBackfillResult:
    symbol: str
    expected_from_id: int
    expected_to_id: int
    requested: int
    received: int
    inserted: int
    status: str
    reason: str = ""


class ControlledAggTradeBackfiller:
    """Bounded, ID-contiguous aggTrade recovery.

    It never reconstructs forceOrder events. Missing liquidation information is
    unknowable through this REST path and must remain explicitly unresolved.
    """

    def __init__(
        self,
        store: PersistentOrderFlowStore,
        fetcher: AggregateTradeFetcher,
        *,
        max_gap_trades: int = 3000,
        page_size: int = 1000,
        max_pages: int = 3,
    ) -> None:
        self.store = store
        self.fetcher = fetcher
        self.max_gap_trades = max(1, int(max_gap_trades))
        self.page_size = min(1000, max(1, int(page_size)))
        self.max_pages = max(1, int(max_pages))

    @staticmethod
    def _trade_id(item: dict[str, Any]) -> int | None:
        value = item.get("a", item.get("id"))
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def backfill(self, symbol: str, from_id: int, to_id: int) -> GapBackfillResult:
        start, end = int(from_id), int(to_id)
        requested = max(0, end - start + 1)
        if requested <= 0:
            return GapBackfillResult(symbol, start, end, requested, 0, 0, "NO_GAP")
        if requested > self.max_gap_trades:
            return GapBackfillResult(
                symbol, start, end, requested, 0, 0, "UNRESOLVED",
                f"gap exceeds max_gap_trades={self.max_gap_trades}",
            )

        expected = start
        collected: list[dict[str, Any]] = []
        pages = 0
        while expected <= end and pages < self.max_pages:
            limit = min(self.page_size, end - expected + 1)
            try:
                batch = self.fetcher(symbol, expected, limit) or []
            except Exception as exc:
                return GapBackfillResult(
                    symbol, start, end, requested, len(collected), 0,
                    "UNRESOLVED", f"fetch failed: {type(exc).__name__}: {exc}",
                )
            pages += 1
            if not batch:
                break
            for item in batch:
                trade_id = self._trade_id(item)
                if trade_id is None or trade_id < expected:
                    continue
                if trade_id != expected:
                    return GapBackfillResult(
                        symbol, start, end, requested, len(collected), 0,
                        "UNRESOLVED", f"non-contiguous REST response at {expected}, got {trade_id}",
                    )
                if trade_id > end:
                    break
                collected.append(item)
                expected += 1
            if expected <= end and len(batch) < limit:
                break

        if expected <= end:
            return GapBackfillResult(
                symbol, start, end, requested, len(collected), 0,
                "UNRESOLVED", f"REST ended before trade id {expected}",
            )
        inserted = self.store.ingest_agg_trades(symbol, collected, realtime=False)
        return GapBackfillResult(
            symbol, start, end, requested, len(collected), inserted, "FILLED"
        )

    @staticmethod
    def diagnostics(result: GapBackfillResult) -> dict[str, Any]:
        return asdict(result)
