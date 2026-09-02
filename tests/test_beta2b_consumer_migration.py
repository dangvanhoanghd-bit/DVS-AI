import sqlite3
from pathlib import Path

from dvs_ai.services.learning_service import LearningService
from dvs_ai.services.quantum_optimizer import QuantumOptimizer
from dvs_ai.services.quantum_readiness_service import QuantumReadinessService
from dvs_ai.services.unified_outcome_service import UnifiedOutcomeService


class FakeUnified:
    def __init__(self, rows): self._rows = rows
    def records(self): return list(self._rows)
    def learning_ready(self): return list(self._rows)
    def pipeline_schema_available(self): return True


def test_learning_default_consumer_is_unified(tmp_path):
    service = LearningService(tmp_path / "missing.db", unified_service=FakeUnified([]))
    assert service.overview()["closed"] == 0
    assert "FROM paper_trades" not in Path("dvs_ai/services/learning_service.py").read_text()


def test_quantum_default_has_unified_service_and_no_raw_adapter(tmp_path):
    optimizer = QuantumOptimizer(db_path=tmp_path / "missing.db", config_path=tmp_path / "c.json")
    assert optimizer.outcome_adapter is None
    assert isinstance(optimizer.unified_service, UnifiedOutcomeService)


def test_readiness_default_has_unified_service_and_no_raw_adapter(tmp_path):
    readiness = QuantumReadinessService(tmp_path / "missing.db")
    assert readiness.outcome_adapter is None
    assert isinstance(readiness.unified_service, UnifiedOutcomeService)


def test_pre_unified_compatibility_is_schema_gated(tmp_path):
    db = tmp_path / "legacy.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE paper_trades(id INTEGER, created_at TEXT, status TEXT, result TEXT, r_multiple REAL)")
    service = UnifiedOutcomeService(db)
    assert service.pipeline_schema_available() is False
    assert service.legacy_compat_learning_ready() == []
