from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from dvs_ai.services.paper_trade_service import PaperTradeService

FMT = "%Y-%m-%d %H:%M:%S"


class _Provider:
    exchange = None


class _Decision:
    pass


def _dt(value: str) -> datetime:
    return datetime.strptime(value, FMT)


def _close(a: float | None, b: float | None, tolerance: float = 1e-8) -> bool:
    if a is None or b is None:
        return a is b
    scale = max(abs(float(a)), abs(float(b)), 1.0)
    return abs(float(a) - float(b)) <= tolerance * scale


def audit_and_migrate(db_path: Path, *, apply: bool = False) -> dict:
    service = PaperTradeService(_Provider(), _Decision(), str(db_path), config=SimpleNamespace())
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        papers = con.execute("""
            SELECT * FROM paper_trades
            WHERE candidate_id IS NULL
            ORDER BY id
        """).fetchall()
        candidates = con.execute("""
            SELECT c.*,o.outcome_id FROM decision_candidates c
            JOIN candidate_outcomes o ON o.candidate_id=c.candidate_id
        """).fetchall()

    report = {"database": str(db_path), "apply": apply, "unbound": len(papers),
              "unique_matches": 0, "ambiguous": 0, "unmatched": 0, "rows": []}
    for paper in papers:
        created = _dt(paper["created_at"])
        matches = []
        for candidate in candidates:
            if paper["symbol"] != candidate["symbol"] or paper["direction"] != candidate["direction"]:
                continue
            if not all((
                _close(paper["entry_low"], candidate["entry_low"]),
                _close(paper["entry_high"], candidate["entry_high"]),
                _close(paper["invalidation"], candidate["invalidation"]),
                _close(paper["tp1"], candidate["tp1"]),
                _close(paper["tp2"], candidate["tp2"]),
            )):
                continue
            activated = _dt(candidate["activated_at"])
            deltas = [abs((activated - (created + timedelta(hours=offset))).total_seconds())
                      for offset in (0, 7, -7)]
            if min(deltas) <= 120:
                matches.append(candidate)
        row = {"paper_trade_id": paper["id"], "symbol": paper["symbol"],
               "status": paper["status"], "result": paper["result"],
               "match_count": len(matches)}
        if len(matches) == 1:
            candidate = matches[0]
            report["unique_matches"] += 1
            row.update(candidate_id=candidate["candidate_id"], outcome_id=candidate["outcome_id"])
            if apply:
                with service._connect() as con:
                    con.execute("""UPDATE paper_trades SET candidate_id=?,outcome_id=?,decision_id=?,
                        decision_engine_profile_hash=?,trade_plan_profile_hash=? WHERE id=? AND candidate_id IS NULL""",
                        (candidate["candidate_id"], candidate["outcome_id"], candidate["activation_evaluation_id"],
                         candidate["decision_engine_profile_hash"], candidate["trade_plan_profile_hash"], paper["id"]))
                    service._sync_unified_lifecycle(
                        con, trade_id=paper["id"], candidate_id=candidate["candidate_id"],
                        outcome_id=candidate["outcome_id"], current_status=paper["status"],
                        result=paper["result"], event_time=paper["closed_at"] or paper["tp1_hit_time"] or paper["fill_time"],
                        fill_time=paper["fill_time"], fill_price=paper["fill_price"],
                        close_price=paper["close_price"], realized_r=float(paper["r_multiple"] or 0.0),
                        mfe_r=float(paper["mfe_r"] or 0.0), mae_r=abs(float(paper["mae_r"] or 0.0)),
                        detail=paper["outcome_detail"] or paper["result"] or paper["status"],
                    )
        elif matches:
            report["ambiguous"] += 1
        else:
            report["unmatched"] += 1
        report["rows"].append(row)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit/migrate legacy Paper→Unified identity links")
    parser.add_argument("--db", default="data/dvs_paper_trades.db")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", default="artifacts/rc4_legacy_link_migration.json")
    args = parser.parse_args()
    report = audit_and_migrate(Path(args.db), apply=args.apply)
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False, indent=2))
    print(f"Report: {out}")
    return 0 if report["ambiguous"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
