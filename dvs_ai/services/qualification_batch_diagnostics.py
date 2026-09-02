from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import traceback

LOGGER = logging.getLogger("dvs_ai.qualification_batch")


@dataclass(frozen=True, slots=True)
class QualificationBatchItemFailure:
    batch_id: str
    request_id: str
    symbol: str
    item_index: int
    exception_type: str
    exception_message: str
    traceback_text: str
    timestamp: str
    worker_state: str = "RUNNING"


def build_item_failure(*, batch_id: str, request_id: str, symbol: str, item_index: int, exc: Exception) -> QualificationBatchItemFailure:
    return QualificationBatchItemFailure(
        batch_id=batch_id,
        request_id=request_id,
        symbol=symbol,
        item_index=item_index,
        exception_type=type(exc).__name__,
        exception_message=str(exc),
        traceback_text=traceback.format_exc(),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


class QualificationBatchFailureJournal:
    """Bounded rotating JSONL diagnostics without cycle payloads or credentials."""

    def __init__(self, path: str | Path = "logs/qualification_batch_failures.jsonl", *, max_bytes: int = 1_000_000, backup_count: int = 3) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger(f"dvs_ai.qualification_batch.journal.{id(self)}")
        self._logger.setLevel(logging.ERROR)
        self._logger.propagate = False
        handler = RotatingFileHandler(self.path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger.handlers[:] = [handler]

    def append(self, failure: QualificationBatchItemFailure) -> None:
        self._logger.error(json.dumps(asdict(failure), ensure_ascii=False, sort_keys=True))
