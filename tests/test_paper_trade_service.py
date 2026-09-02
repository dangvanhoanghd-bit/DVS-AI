from pathlib import Path
from types import SimpleNamespace

from dvs_ai.services.paper_trade_service import PaperTradeService


class DummyProvider:
    exchange = None


class DummyDecision:
    pass


def test_paper_db_initializes(tmp_path):
    service = PaperTradeService(
        DummyProvider(),
        DummyDecision(),
        str(tmp_path / "paper.db"),
    )
    assert service.counts() == {"LONG": 0, "SHORT": 0}
    assert service.statistics()["total"] == 0
