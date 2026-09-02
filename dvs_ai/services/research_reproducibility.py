from __future__ import annotations
import hashlib, html, json, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE_MD5 = '72cf7d54e1ed6369400683358da8c0ef'
SCHEMA_VERSION = 'research-comparison-v1'

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()

class ExperimentComparisonService:
    """Read-only comparison of completed research runs stored in the isolated workspace."""
    def __init__(self, workspace_path: str = 'data/research_workspace.db'):
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
            CREATE TABLE IF NOT EXISTS research_comparisons(
              comparison_id TEXT PRIMARY KEY,
              created_at TEXT NOT NULL,
              experiment_ids_json TEXT NOT NULL,
              status TEXT NOT NULL,
              verdict TEXT NOT NULL,
              report_json TEXT NOT NULL,
              report_sha256 TEXT NOT NULL,
              engine_md5 TEXT NOT NULL
            );
            ''')

    def _load(self, c, experiment_id: str) -> dict[str, Any]:
        row = c.execute('SELECT * FROM research_experiments WHERE experiment_id=?', (experiment_id,)).fetchone()
        if not row:
            raise KeyError(f'Experiment not found: {experiment_id}')
        d = dict(row)
        d['parameters'] = json.loads(d['parameters_json'])
        d['result'] = json.loads(d['result_json']) if d.get('result_json') else None
        return d

    def compare(self, experiment_ids: list[str]) -> dict[str, Any]:
        ids = list(dict.fromkeys(x.strip() for x in experiment_ids if x and x.strip()))
        if len(ids) < 2:
            raise ValueError('At least two experiment IDs are required')
        with self._connect() as c:
            runs = [self._load(c, x) for x in ids]
            snapshots = {r['snapshot_id'] for r in runs}
            analyses = {r['analysis_type'] for r in runs}
            parameters = {r['parameters_json'] for r in runs}
            engines = {r['engine_md5'] for r in runs}
            statuses = {r['status'] for r in runs}
            results = {r.get('result_sha256') for r in runs}
            checks = {
                'all_finished': statuses == {'FINISHED'},
                'same_snapshot': len(snapshots) == 1,
                'same_analysis_type': len(analyses) == 1,
                'same_parameters': len(parameters) == 1,
                'same_engine_md5': engines == {ENGINE_MD5},
                'same_result_sha256': len(results) == 1 and None not in results,
            }
            reproducible = all(checks.values())
            if reproducible:
                verdict = 'REPRODUCIBLE'
            elif not checks['all_finished']:
                verdict = 'INCOMPLETE_RUN_SET'
            elif not checks['same_snapshot']:
                verdict = 'DATASET_DRIFT'
            elif not checks['same_parameters']:
                verdict = 'PARAMETER_DRIFT'
            elif not checks['same_analysis_type']:
                verdict = 'ANALYSIS_DRIFT'
            elif not checks['same_engine_md5']:
                verdict = 'ENVIRONMENT_DRIFT'
            else:
                verdict = 'RESULT_DIVERGENCE'
            report = {
                'schema': SCHEMA_VERSION,
                'created_at': _now(),
                'verdict': verdict,
                'reproducible': reproducible,
                'checks': checks,
                'experiment_ids': ids,
                'runs': [{
                    'experiment_id': r['experiment_id'], 'name': r['name'], 'status': r['status'],
                    'analysis_type': r['analysis_type'], 'parameters': r['parameters'],
                    'snapshot_id': r['snapshot_id'], 'result_sha256': r.get('result_sha256'),
                    'engine_md5': r['engine_md5'], 'created_at': r['created_at'],
                    'started_at': r.get('started_at'), 'finished_at': r.get('finished_at')
                } for r in runs],
                'scientific_boundary': {
                    'descriptive_only': True,
                    'canonical_database_write': False,
                    'decision_engine_invocation': False,
                    'automatic_tuning': False,
                },
            }
            cid = str(uuid.uuid4())
            digest = _sha(report)
            c.execute('INSERT INTO research_comparisons VALUES(?,?,?,?,?,?,?,?)',
                      (cid, report['created_at'], _canonical(ids), 'FINISHED', verdict,
                       _canonical(report), digest, ENGINE_MD5))
            report['comparison_id'] = cid
            report['report_sha256'] = digest
            return report

    def list_comparisons(self) -> list[dict[str, Any]]:
        with self._connect() as c:
            return [dict(r) for r in c.execute('SELECT comparison_id,created_at,status,verdict,report_sha256 FROM research_comparisons ORDER BY created_at DESC')]

    def export_json(self, report: dict[str, Any], path: str) -> str:
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
        return str(p)

    def export_html(self, report: dict[str, Any], path: str) -> str:
        rows = ''.join(f"<tr><td>{html.escape(r['experiment_id'])}</td><td>{html.escape(r['analysis_type'])}</td><td>{html.escape(r['snapshot_id'])}</td><td>{html.escape(str(r['result_sha256']))}</td></tr>" for r in report['runs'])
        checks = ''.join(f"<li>{html.escape(k)}: <strong>{v}</strong></li>" for k,v in report['checks'].items())
        body = f'''<!doctype html><meta charset="utf-8"><title>Experiment Reproducibility Report</title>
<h1>Experiment Result Comparison</h1><p><strong>Verdict:</strong> {html.escape(report['verdict'])}</p>
<p><strong>Report SHA-256:</strong> {html.escape(report['report_sha256'])}</p><ul>{checks}</ul>
<table border="1" cellspacing="0" cellpadding="6"><tr><th>Experiment</th><th>Analysis</th><th>Snapshot</th><th>Result SHA-256</th></tr>{rows}</table>
<p><strong>Scientific boundary:</strong> read-only comparison; no Decision Engine invocation; no automatic tuning.</p>'''
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(body, encoding='utf-8'); return str(p)
