from __future__ import annotations

import hashlib
import html
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE_MD5 = '72cf7d54e1ed6369400683358da8c0ef'
SCHEMA_VERSION = 'research-lineage-v1'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


class ResearchLineageProvenanceService:
    """Read-only provenance explorer for snapshots, experiments, comparisons and cohorts."""

    def __init__(self, workspace_path: str = 'data/research_workspace.db'):
        self.workspace = Path(workspace_path)

    def _connect_ro(self):
        if not self.workspace.exists():
            raise FileNotFoundError(self.workspace)
        c = sqlite3.connect(f'file:{self.workspace.resolve().as_posix()}?mode=ro', uri=True)
        c.row_factory = sqlite3.Row
        return c

    @staticmethod
    def _table_exists(c: sqlite3.Connection, name: str) -> bool:
        return c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone() is not None

    def analyze(self) -> dict[str, Any]:
        with self._connect_ro() as c:
            snapshots = [dict(r) for r in c.execute(
                'SELECT snapshot_id,created_at,source_path,source_sha256,manifest_sha256 FROM research_snapshots ORDER BY created_at'
            )] if self._table_exists(c, 'research_snapshots') else []
            experiments = [dict(r) for r in c.execute(
                'SELECT experiment_id,name,analysis_type,snapshot_id,status,created_at,result_sha256,engine_md5 FROM research_experiments ORDER BY created_at'
            )] if self._table_exists(c, 'research_experiments') else []
            comparisons = [dict(r) for r in c.execute(
                'SELECT comparison_id,created_at,experiment_ids_json,status,verdict,report_sha256,engine_md5 FROM research_comparisons ORDER BY created_at'
            )] if self._table_exists(c, 'research_comparisons') else []
            cohorts = [dict(r) for r in c.execute(
                'SELECT cohort_id,name,created_at,status,experiment_ids_json,configuration_sha256,summary_sha256,engine_md5 FROM research_cohorts ORDER BY created_at'
            )] if self._table_exists(c, 'research_cohorts') else []

        exp_by_id = {x['experiment_id']: x for x in experiments}
        snapshot_by_id = {x['snapshot_id']: x for x in snapshots}
        snapshot_usage: dict[str, list[str]] = defaultdict(list)
        result_usage: dict[str, list[str]] = defaultdict(list)
        engine_counts = Counter()
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []

        for s in snapshots:
            nodes.append({'id': s['snapshot_id'], 'type': 'SNAPSHOT', 'label': s['snapshot_id'], 'created_at': s['created_at']})

        for e in experiments:
            nodes.append({'id': e['experiment_id'], 'type': 'EXPERIMENT', 'label': e['name'], 'created_at': e['created_at']})
            snapshot_usage[e['snapshot_id']].append(e['experiment_id'])
            edges.append({'from': e['snapshot_id'], 'to': e['experiment_id'], 'relation': 'SNAPSHOT_TO_EXPERIMENT'})
            if e.get('result_sha256'):
                result_usage[e['result_sha256']].append(e['experiment_id'])
            engine_counts[e.get('engine_md5') or 'MISSING'] += 1
            if e['snapshot_id'] not in snapshot_by_id:
                issues.append({'severity': 'ERROR', 'code': 'ORPHAN_EXPERIMENT_SNAPSHOT', 'entity_id': e['experiment_id'], 'detail': e['snapshot_id']})
            if e.get('engine_md5') != ENGINE_MD5:
                issues.append({'severity': 'ERROR', 'code': 'ENGINE_MD5_MISMATCH', 'entity_id': e['experiment_id'], 'detail': str(e.get('engine_md5'))})

        def parse_ids(raw: str, owner_type: str, owner_id: str) -> list[str]:
            try:
                value = json.loads(raw)
                if not isinstance(value, list):
                    raise ValueError('not a list')
                return [str(x) for x in value]
            except Exception as exc:
                issues.append({'severity': 'ERROR', 'code': 'INVALID_EXPERIMENT_ID_LIST', 'entity_id': owner_id, 'detail': f'{owner_type}: {exc}'})
                return []

        for x in comparisons:
            nodes.append({'id': x['comparison_id'], 'type': 'COMPARISON', 'label': x['verdict'], 'created_at': x['created_at']})
            ids = parse_ids(x['experiment_ids_json'], 'COMPARISON', x['comparison_id'])
            for eid in ids:
                edges.append({'from': eid, 'to': x['comparison_id'], 'relation': 'EXPERIMENT_TO_COMPARISON'})
                if eid not in exp_by_id:
                    issues.append({'severity': 'ERROR', 'code': 'ORPHAN_COMPARISON_EXPERIMENT', 'entity_id': x['comparison_id'], 'detail': eid})
            if x.get('engine_md5') != ENGINE_MD5:
                issues.append({'severity': 'ERROR', 'code': 'COMPARISON_ENGINE_MD5_MISMATCH', 'entity_id': x['comparison_id'], 'detail': str(x.get('engine_md5'))})

        for x in cohorts:
            nodes.append({'id': x['cohort_id'], 'type': 'COHORT', 'label': x['name'], 'created_at': x['created_at']})
            ids = parse_ids(x['experiment_ids_json'], 'COHORT', x['cohort_id'])
            for eid in ids:
                edges.append({'from': eid, 'to': x['cohort_id'], 'relation': 'EXPERIMENT_TO_COHORT'})
                if eid not in exp_by_id:
                    issues.append({'severity': 'ERROR', 'code': 'ORPHAN_COHORT_EXPERIMENT', 'entity_id': x['cohort_id'], 'detail': eid})
            if x.get('engine_md5') != ENGINE_MD5:
                issues.append({'severity': 'ERROR', 'code': 'COHORT_ENGINE_MD5_MISMATCH', 'entity_id': x['cohort_id'], 'detail': str(x.get('engine_md5'))})

        duplicate_source_groups: dict[str, list[str]] = defaultdict(list)
        for s in snapshots:
            duplicate_source_groups[s['source_sha256']].append(s['snapshot_id'])
        duplicate_source_groups = {k: v for k, v in duplicate_source_groups.items() if len(v) > 1}

        branch_points = [
            {'snapshot_id': sid, 'experiment_ids': ids, 'experiment_count': len(ids)}
            for sid, ids in sorted(snapshot_usage.items()) if len(ids) > 1
        ]
        shared_results = [
            {'result_sha256': digest, 'experiment_ids': ids, 'experiment_count': len(ids)}
            for digest, ids in sorted(result_usage.items()) if len(ids) > 1
        ]
        unused_snapshots = [s['snapshot_id'] for s in snapshots if not snapshot_usage.get(s['snapshot_id'])]

        report = {
            'schema': SCHEMA_VERSION,
            'generated_at': _now(),
            'workspace_path': str(self.workspace),
            'counts': {
                'snapshots': len(snapshots),
                'experiments': len(experiments),
                'comparisons': len(comparisons),
                'cohorts': len(cohorts),
                'nodes': len(nodes),
                'edges': len(edges),
                'issues': len(issues),
            },
            'snapshots': snapshots,
            'experiments': experiments,
            'comparisons': comparisons,
            'cohorts': cohorts,
            'nodes': nodes,
            'edges': edges,
            'snapshot_usage': dict(sorted(snapshot_usage.items())),
            'branch_points': branch_points,
            'duplicate_source_snapshots': dict(sorted(duplicate_source_groups.items())),
            'shared_result_groups': shared_results,
            'unused_snapshots': unused_snapshots,
            'engine_md5_distribution': dict(sorted(engine_counts.items())),
            'issues': issues,
            'scientific_boundary': {
                'read_only': True,
                'descriptive_only': True,
                'decision_engine_invocation': False,
                'automatic_tuning': False,
                'canonical_database_write': False,
                'workspace_write': False,
            },
            'limitations': [
                'Lineage is derived from stored identifiers and checksums only.',
                'Shared source checksum indicates identical source bytes, not identical research intent.',
                'Shared result checksum indicates identical serialized result, not external validity.',
                'Missing legacy tables are treated as absent, not reconstructed.',
            ],
        }
        report['report_sha256'] = _sha(report)
        return report

    def export_json(self, report: dict[str, Any], path: str) -> str:
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
        return str(p)

    def export_html(self, report: dict[str, Any], path: str) -> str:
        issue_rows = ''.join(
            f"<tr><td>{html.escape(x['severity'])}</td><td>{html.escape(x['code'])}</td><td>{html.escape(x['entity_id'])}</td><td>{html.escape(x['detail'])}</td></tr>"
            for x in report['issues']
        ) or '<tr><td colspan="4">No provenance issues detected</td></tr>'
        branch_rows = ''.join(
            f"<tr><td>{html.escape(x['snapshot_id'])}</td><td>{x['experiment_count']}</td><td>{html.escape(', '.join(x['experiment_ids']))}</td></tr>"
            for x in report['branch_points']
        ) or '<tr><td colspan="3">No branch points</td></tr>'
        c = report['counts']
        body = f'''<!doctype html><meta charset="utf-8"><title>Research Dataset Lineage</title>
<h1>Research Dataset Lineage & Provenance</h1>
<p>Snapshots {c['snapshots']} · Experiments {c['experiments']} · Comparisons {c['comparisons']} · Cohorts {c['cohorts']}</p>
<p><strong>Report SHA-256:</strong> {html.escape(report['report_sha256'])}</p>
<h2>Snapshot branch points</h2><table border="1" cellspacing="0" cellpadding="6"><tr><th>Snapshot</th><th>Experiments</th><th>Experiment IDs</th></tr>{branch_rows}</table>
<h2>Provenance issues</h2><table border="1" cellspacing="0" cellpadding="6"><tr><th>Severity</th><th>Code</th><th>Entity</th><th>Detail</th></tr>{issue_rows}</table>
<p><strong>Scientific boundary:</strong> read-only lineage exploration; no Decision Engine invocation; no automatic tuning; no database writes.</p>'''
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(body, encoding='utf-8')
        return str(p)
