from __future__ import annotations

import sqlite3
from pathlib import Path

from beta4a_burnin_collector import capture, sha256_file, sqlite_integrity


def test_collector_reads_sqlite_without_mutation(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY)")
        conn.executemany("INSERT INTO sample(id) VALUES (?)", [(1,), (2,)])
    before = sha256_file(db)
    snapshot = capture(db, tmp_path / "missing.log")
    after = sha256_file(db)
    assert snapshot.table_counts == {"sample": 2}
    assert before == after
    assert sqlite_integrity(db) == "ok"


def test_missing_database_is_fail_closed(tmp_path: Path) -> None:
    missing = tmp_path / "missing.db"
    snapshot = capture(missing, tmp_path / "missing.log")
    assert snapshot.table_counts == {}
    assert sqlite_integrity(missing) == "MISSING"
