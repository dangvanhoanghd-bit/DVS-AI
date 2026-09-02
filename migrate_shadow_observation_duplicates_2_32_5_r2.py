from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dvs_ai.services.shadow_observation_service import ShadowObservationStore


def counts(db: Path) -> tuple[int, int]:
    with sqlite3.connect(db) as conn:
        total = int(conn.execute("SELECT COUNT(*) FROM shadow_observations").fetchone()[0])
        try:
            archived = int(conn.execute("SELECT COUNT(*) FROM shadow_observation_duplicate_archive").fetchone()[0])
        except sqlite3.OperationalError:
            archived = 0
    return total, archived


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit-safe shadow observation duplicate migration")
    parser.add_argument("db", nargs="?", default="data/dvs_paper_trades.db")
    args = parser.parse_args()
    db = Path(args.db).resolve()
    if not db.exists():
        raise SystemExit(f"Database not found: {db}")
    before, archived_before = counts(db)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = db.with_name(f"{db.stem}.before_shadow_dedup_{stamp}{db.suffix}")
    shutil.copy2(db, backup)
    ShadowObservationStore(str(db))  # schema migration is transactional and append-only archived
    after, archived_after = counts(db)
    print(f"database={db}")
    print(f"backup={backup}")
    print(f"rows_before={before}")
    print(f"rows_after={after}")
    print(f"duplicates_archived={archived_after - archived_before}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
