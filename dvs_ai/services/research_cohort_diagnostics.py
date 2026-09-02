from __future__ import annotations

import hashlib
import html
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

ENGINE_MD5 = '72cf7d54e1ed6369400683358da8c0ef'
SCHEMA_VERSION = 'cohort-diagnostics-v1'


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


class ResearchCohortDiagnosticsService:
    """Read-only, descriptive cross-study diagnostics over completed cohorts."""

    def __init__(self, workspace_path: str = 'data/research_workspace.db'):
        self.workspace = Path(workspace_path)

    def _connect_ro(self):
        if not self.workspace.exists():
            raise FileNotFoundError(f'Research workspace not found: {self.workspace}')
        c = sqlite3.connect(f'file:{self.workspace.resolve()}?mode=ro', uri=True)
        c.row_factory = sqlite3.Row
        return c

    def analyze(self, cohort_ids: list[str] | None = None) -> dict[str, Any]:
        with self._connect_ro() as c:
            if cohort_ids:
                ids = list(dict.fromkeys(x.strip() for x in cohort_ids if x and x.strip()))
                q = ','.join('?' for _ in ids)
                rows = c.execute(f'SELECT * FROM research_cohorts WHERE cohort_id IN ({q}) ORDER BY created_at', ids).fetchall()
                missing = sorted(set(ids) - {r['cohort_id'] for r in rows})
                if missing:
                    raise KeyError(f'Cohort not found: {", ".join(missing)}')
            else:
                rows = c.execute('SELECT * FROM research_cohorts ORDER BY created_at').fetchall()

        cohorts = []
        completion_rates = []
        status_totals = Counter()
        analysis_totals = Counter()
        snapshot_totals = Counter()
        result_occurrences: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            r = dict(row)
            summary = json.loads(r['summary_json']) if r.get('summary_json') else {}
            completion = float(summary.get('completion_rate', 0.0) or 0.0)
            completion_rates.append(completion)
            status_totals.update(summary.get('status_counts', {}))
            analysis_totals.update(summary.get('analysis_counts', {}))
            snapshot_totals.update(summary.get('snapshot_coverage', {}))
            for digest, experiment_ids in summary.get('result_groups', {}).items():
                result_occurrences[digest].extend(experiment_ids)
            cohorts.append({
                'cohort_id': r['cohort_id'],
                'name': r['name'],
                'status': r['status'],
                'created_at': r['created_at'],
                'configuration_sha256': r['configuration_sha256'],
                'summary_sha256': r.get('summary_sha256'),
                'total_experiments': int(summary.get('total_experiments', 0) or 0),
                'completed_experiments': int(summary.get('completed_experiments', 0) or 0),
                'completion_rate': completion,
                'snapshot_count': int(summary.get('snapshot_count', 0) or 0),
                'distinct_result_count': int(summary.get('distinct_result_count', 0) or 0),
            })

        cross_cohort_repeats = {
            digest: sorted(set(exp_ids))
            for digest, exp_ids in result_occurrences.items()
            if len(set(exp_ids)) > 1
        }
        report = {
            'schema': SCHEMA_VERSION,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'engine_md5': ENGINE_MD5,
            'cohort_count': len(cohorts),
            'total_experiments': sum(x['total_experiments'] for x in cohorts),
            'completed_experiments': sum(x['completed_experiments'] for x in cohorts),
            'completion_rate_mean': mean(completion_rates) if completion_rates else 0.0,
            'completion_rate_median': median(completion_rates) if completion_rates else 0.0,
            'status_coverage': dict(sorted(status_totals.items())),
            'analysis_coverage': dict(sorted(analysis_totals.items())),
            'snapshot_coverage': dict(sorted(snapshot_totals.items())),
            'unique_snapshot_count': len(snapshot_totals),
            'cross_cohort_repeated_results': cross_cohort_repeats,
            'cohorts': cohorts,
            'limitations': [
                'Descriptive diagnostics only; no causal inference.',
                'Result checksum equality does not prove market robustness.',
                'Small or overlapping cohorts may overstate consistency.',
                'No automatic tuning, ranking, or Decision Engine invocation.',
            ],
            'scientific_boundary': {
                'descriptive_only': True,
                'automatic_tuning': False,
                'strategy_ranking': False,
                'decision_engine_invocation': False,
                'canonical_database_write': False,
                'workspace_write': False,
            },
        }
        report['report_sha256'] = _sha(report)
        return report

    def export_json(self, report: dict[str, Any], path: str) -> str:
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
        return str(p)

    def export_html(self, report: dict[str, Any], path: str) -> str:
        rows = ''.join(
            '<tr>' + ''.join(f'<td>{html.escape(str(c))}</td>' for c in (
                r['name'], r['status'], r['total_experiments'], r['completed_experiments'],
                f"{r['completion_rate']:.1%}", r['snapshot_count'], r['distinct_result_count'])) + '</tr>'
            for r in report['cohorts']
        )
        body = f'''<!doctype html><meta charset="utf-8"><title>Cohort Statistical Diagnostics</title>
<h1>Cohort Statistical Diagnostics & Cross-Study Analysis</h1>
<p><b>Cohorts:</b> {report['cohort_count']} · <b>Experiments:</b> {report['total_experiments']} · <b>Mean completion:</b> {report['completion_rate_mean']:.1%}</p>
<p><b>Report SHA-256:</b> {html.escape(report['report_sha256'])}</p>
<table border="1" cellspacing="0" cellpadding="6"><tr><th>Cohort</th><th>Status</th><th>Total</th><th>Completed</th><th>Completion</th><th>Snapshots</th><th>Distinct results</th></tr>{rows}</table>
<h2>Limitations</h2><ul>{''.join(f'<li>{html.escape(x)}</li>' for x in report['limitations'])}</ul>
<p><b>Scientific boundary:</b> descriptive only; no tuning; no strategy ranking; no Decision Engine invocation; no database write.</p>'''
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(body, encoding='utf-8')
        return str(p)
