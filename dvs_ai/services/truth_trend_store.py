from __future__ import annotations
import json, math, sqlite3
from datetime import datetime, timezone
from pathlib import Path

class TruthTrendStore:
    """Append-only observe-only history for drift/reliability visualization."""
    def __init__(self, db_path="data/dvs_paper_trades.db"):
        self.db_path=Path(db_path)
        self._ensure()
    def _ensure(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as con:
            con.execute("""CREATE TABLE IF NOT EXISTS truth_trend_history(
                id INTEGER PRIMARY KEY AUTOINCREMENT, recorded_at TEXT NOT NULL,
                kind TEXT NOT NULL, state TEXT NOT NULL, payload_json TEXT NOT NULL)""")
            con.execute("CREATE INDEX IF NOT EXISTS idx_truth_trend_kind_time ON truth_trend_history(kind, recorded_at)")
    @staticmethod
    def _clean(payload):
        out={}
        for k,v in dict(payload).items():
            if isinstance(v,(int,float)):
                v=float(v)
                out[k]=v if math.isfinite(v) else 0.0
            elif isinstance(v,(str,bool)) or v is None: out[k]=v
        return out
    def append(self, kind, state, payload, recorded_at=None):
        at=recorded_at or datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as con:
            con.execute("INSERT INTO truth_trend_history(recorded_at,kind,state,payload_json) VALUES(?,?,?,?)",
                        (at,str(kind).upper(),str(state).upper(),json.dumps(self._clean(payload))))
    def recent(self, kind, limit=120):
        with sqlite3.connect(self.db_path) as con:
            rows=con.execute("SELECT recorded_at,state,payload_json FROM truth_trend_history WHERE kind=? ORDER BY id DESC LIMIT ?",
                             (str(kind).upper(),max(1,int(limit)))).fetchall()
        result=[]
        for at,state,payload in reversed(rows):
            try: data=json.loads(payload)
            except Exception: data={}
            result.append({"recorded_at":at,"state":state,**data})
        return result
