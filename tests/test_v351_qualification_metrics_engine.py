from pathlib import Path

from dvs_ai.services.core_shadow_agreement_service import (
    CoreShadowAgreementStore, ShadowAgreementObservation,
    AGREEMENT_FULL, AGREEMENT_UNSAFE,
)


def test_analytics_breakdowns_and_unsafe_inventory(tmp_path: Path):
    store = CoreShadowAgreementStore(tmp_path / "q.sqlite3")
    store.append(ShadowAgreementObservation(
        request_id="a", symbol="BTC/USDT", analysis_revision=1,
        legacy_action="BUY", unified_action="BUY", agreement=AGREEMENT_FULL,
        ledger_verified=True, confidence=75, regime="TREND", phase="MARKUP", timeframe="15m",
    ))
    store.append(ShadowAgreementObservation(
        request_id="b", symbol="ETH/USDT", analysis_revision=2,
        legacy_action="NO_ACTION", unified_action="SELL", agreement=AGREEMENT_UNSAFE,
        ledger_verified=True, confidence=55, regime="RANGE", phase="DISTRIBUTION", timeframe="15m",
    ))
    analytics = store.analytics()
    assert analytics.total_cycles == 2
    assert any(x.key == "BTC/USDT" and x.full == 1 for x in analytics.by_symbol)
    assert any(x.key == "70-79" for x in analytics.by_confidence_bucket)
    assert len(analytics.unsafe_cases) == 1


def test_schema_migration_is_backward_compatible(tmp_path: Path):
    import sqlite3
    db = tmp_path / "old.sqlite3"
    with sqlite3.connect(db) as c:
        c.execute("""CREATE TABLE core_shadow_agreement_observations (
          request_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, analysis_revision INTEGER NOT NULL,
          legacy_action TEXT NOT NULL, unified_action TEXT NOT NULL, agreement TEXT NOT NULL,
          ledger_verified INTEGER NOT NULL, synthetic_lifecycle INTEGER NOT NULL,
          observed_at TEXT NOT NULL, profile_hash TEXT NOT NULL)""")
    CoreShadowAgreementStore(db)
    with sqlite3.connect(db) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(core_shadow_agreement_observations)")}
    assert {"confidence", "regime", "phase", "timeframe"}.issubset(cols)
