from __future__ import annotations

import hashlib
import html
import json
import sqlite3
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dvs_ai.services.research_experiment_engine import ResearchExperimentEngine

ENGINE_MD5 = '72cf7d54e1ed6369400683358da8c0ef'
SCHEMA_VERSION = 'research-cohort-v1'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


class ResearchCohortService:
    """Controlled batch studies over registered research experiments only."""

    def __init__(self, source_db_path: str, workspace_path: str = 'data/research_workspace.db'):
        self.source = Path(source_db_path)
        self.workspace = Path(workspace_path)
        self.workspace.parent.mkdir(parents=True, exist_ok=True)
        self._schema()

    def _connect(self):
        c = sqlite3.connect(self.workspace)
        c.row_factory = sqlite3.Row
        return c

    def _schema(self) -> None:
        with self._connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS research_cohorts(
              cohort_id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              objective TEXT NOT NULL,
              created_at TEXT NOT NULL,
              status TEXT NOT NULL,
              experiment_ids_json TEXT NOT NULL,
              configuration_sha256 TEXT NOT NULL,
              started_at TEXT,
              finished_at TEXT,
              summary_json TEXT,
              summary_sha256 TEXT,
              engine_md5 TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS research_cohort_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              cohort_id TEXT NOT NULL,
              event_at TEXT NOT NULL,
              event_type TEXT NOT NULL,
              detail_json TEXT NOT NULL
            );
            ''')

    def _experiments(self, c, ids: list[str]) -> list[dict[str, Any]]:
        rows = []
        for eid in ids:
            row = c.execute('SELECT * FROM research_experiments WHERE experiment_id=?', (eid,)).fetchone()
            if not row:
                raise KeyError(f'Experiment not found: {eid}')
            rows.append(dict(row))
        return rows

    def create_cohort(self, name: str, objective: str, experiment_ids: list[str]) -> str:
        ids = list(dict.fromkeys(x.strip() for x in experiment_ids if x and x.strip()))
        if len(ids) < 2:
            raise ValueError('A cohort requires at least two experiments')
        with self._connect() as c:
            runs = self._experiments(c, ids)
            if any(r['engine_md5'] != ENGINE_MD5 for r in runs):
                raise ValueError('Experiment engine MD5 differs from frozen baseline')
            config = {
                'schema': SCHEMA_VERSION,
                'experiment_ids': ids,
                'analysis_types': [r['analysis_type'] for r in runs],
                'snapshot_ids': [r['snapshot_id'] for r in runs],
                'engine_md5': ENGINE_MD5,
            }
            cid = str(uuid.uuid4())
            created = _now()
            c.execute(
                'INSERT INTO research_cohorts(cohort_id,name,objective,created_at,status,experiment_ids_json,configuration_sha256,engine_md5) VALUES(?,?,?,?,?,?,?,?)',
                (cid, name.strip() or 'Research Cohort', objective.strip(), created, 'CREATED', _canonical(ids), _sha(config), ENGINE_MD5),
            )
            c.execute(
                'INSERT INTO research_cohort_events(cohort_id,event_at,event_type,detail_json) VALUES(?,?,?,?)',
                (cid, created, 'CREATED', _canonical(config)),
            )
            return cid

    def run_cohort(self, cohort_id: str) -> dict[str, Any]:
        with self._connect() as c:
            row = c.execute('SELECT * FROM research_cohorts WHERE cohort_id=?', (cohort_id,)).fetchone()
            if not row:
                raise KeyError('Cohort not found')
            cohort = dict(row)
            ids = json.loads(cohort['experiment_ids_json'])
            started = _now()
            c.execute('UPDATE research_cohorts SET status=?,started_at=? WHERE cohort_id=?', ('RUNNING', started, cohort_id))
            c.execute('INSERT INTO research_cohort_events(cohort_id,event_at,event_type,detail_json) VALUES(?,?,?,?)', (cohort_id, started, 'RUNNING', '{}'))

        engine = ResearchExperimentEngine(str(self.source), str(self.workspace))
        for eid in ids:
            run = engine.get(eid)
            if run and run['status'] == 'CREATED':
                engine.run(eid)

        with self._connect() as c:
            runs = self._experiments(c, ids)
            status_counts = Counter(r['status'] for r in runs)
            analysis_counts = Counter(r['analysis_type'] for r in runs)
            snapshot_counts = Counter(r['snapshot_id'] for r in runs)
            result_groups: dict[str, list[str]] = defaultdict(list)
            for r in runs:
                if r.get('result_sha256'):
                    result_groups[r['result_sha256']].append(r['experiment_id'])
            completed = status_counts.get('FINISHED', 0)
            total = len(runs)
            summary = {
                'schema': SCHEMA_VERSION,
                'cohort_id': cohort_id,
                'generated_at': _now(),
                'total_experiments': total,
                'completed_experiments': completed,
                'completion_rate': completed / total if total else 0.0,
                'status_counts': dict(sorted(status_counts.items())),
                'analysis_counts': dict(sorted(analysis_counts.items())),
                'snapshot_count': len(snapshot_counts),
                'snapshot_coverage': dict(sorted(snapshot_counts.items())),
                'distinct_result_count': len(result_groups),
                'result_groups': dict(sorted(result_groups.items())),
                'experiments': [
                    {
                        'experiment_id': r['experiment_id'], 'name': r['name'],
                        'analysis_type': r['analysis_type'], 'snapshot_id': r['snapshot_id'],
                        'status': r['status'], 'result_sha256': r.get('result_sha256'),
                    } for r in runs
                ],
                'scientific_boundary': {
                    'descriptive_only': True,
                    'automatic_tuning': False,
                    'decision_engine_invocation': False,
                    'canonical_database_write': False,
                },
            }
            final_status = 'FINISHED' if completed == total else 'COMPLETED_WITH_EXCEPTIONS'
            digest = _sha(summary)
            finished = _now()
            c.execute('UPDATE research_cohorts SET status=?,finished_at=?,summary_json=?,summary_sha256=? WHERE cohort_id=?', (final_status, finished, _canonical(summary), digest, cohort_id))
            c.execute('INSERT INTO research_cohort_events(cohort_id,event_at,event_type,detail_json) VALUES(?,?,?,?)', (cohort_id, finished, final_status, _canonical({'summary_sha256': digest})))
            summary['status'] = final_status
            summary['summary_sha256'] = digest
            return summary

    def get_cohort(self, cohort_id: str) -> dict[str, Any] | None:
        with self._connect() as c:
            row = c.execute('SELECT * FROM research_cohorts WHERE cohort_id=?', (cohort_id,)).fetchone()
            if not row:
                return None
            data = dict(row)
            data['experiment_ids'] = json.loads(data['experiment_ids_json'])
            data['summary'] = json.loads(data['summary_json']) if data.get('summary_json') else None
            data['events'] = [dict(r) for r in c.execute('SELECT event_at,event_type,detail_json FROM research_cohort_events WHERE cohort_id=? ORDER BY id', (cohort_id,))]
            return data

    def list_cohorts(self) -> list[dict[str, Any]]:
        with self._connect() as c:
            return [dict(r) for r in c.execute('SELECT cohort_id,name,created_at,status,configuration_sha256,summary_sha256 FROM research_cohorts ORDER BY created_at DESC')]

    def export_json(self, summary: dict[str, Any], path: str) -> str:
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
        return str(p)

    def export_html(self, summary: dict[str, Any], path: str) -> str:
        rows = ''.join(
            f"<tr><td>{html.escape(r['experiment_id'])}</td><td>{html.escape(r['analysis_type'])}</td><td>{html.escape(r['status'])}</td><td>{html.escape(str(r['result_sha256']))}</td></tr>"
            for r in summary['experiments']
        )
        body = f'''<!doctype html><meta charset="utf-8"><title>Research Cohort Report</title>
<h1>Experiment Cohort & Batch Study</h1>
<p><strong>Status:</strong> {html.escape(summary['status'])}</p>
<p><strong>Completion:</strong> {summary['completed_experiments']}/{summary['total_experiments']}</p>
<p><strong>Summary SHA-256:</strong> {html.escape(summary['summary_sha256'])}</p>
<table border="1" cellspacing="0" cellpadding="6"><tr><th>Experiment</th><th>Analysis</th><th>Status</th><th>Result SHA-256</th></tr>{rows}</table>
<p><strong>Scientific boundary:</strong> descriptive-only batch study; no Decision Engine invocation; no automatic tuning; no canonical database write.</p>'''
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(body, encoding='utf-8')
        return str(p)
