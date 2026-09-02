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
SCHEMA_VERSION = 'research-governance-v1'
REVIEWABLE_TABLES = {
    'EXPERIMENT': ('research_experiments', 'experiment_id', 'name', 'result_sha256'),
    'COMPARISON': ('research_comparisons', 'comparison_id', 'verdict', 'report_sha256'),
    'COHORT': ('research_cohorts', 'cohort_id', 'name', 'summary_sha256'),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


class ResearchGovernanceDashboardService:
    """Read-only governance coverage across research workspace and isolated review ledger."""

    def __init__(self, workspace_path='data/research_workspace.db', review_db_path='data/research_reviews.db'):
        self.workspace = Path(workspace_path)
        self.review_db = Path(review_db_path)

    @staticmethod
    def _connect_ro(path: Path) -> sqlite3.Connection:
        if not path.exists():
            raise FileNotFoundError(path)
        c = sqlite3.connect(f'file:{path.resolve().as_posix()}?mode=ro', uri=True)
        c.row_factory = sqlite3.Row
        return c

    @staticmethod
    def _table_exists(c: sqlite3.Connection, table: str) -> bool:
        return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None

    def _targets(self) -> list[dict[str, Any]]:
        targets: list[dict[str, Any]] = []
        with self._connect_ro(self.workspace) as c:
            for target_type, (table, key, label, checksum) in REVIEWABLE_TABLES.items():
                if not self._table_exists(c, table):
                    continue
                rows = c.execute(
                    f'SELECT {key} AS target_id,{label} AS title,{checksum} AS target_checksum FROM {table}'
                ).fetchall()
                for row in rows:
                    item = dict(row)
                    item['target_type'] = target_type
                    targets.append(item)
        return targets

    def _reviews(self) -> list[dict[str, Any]]:
        if not self.review_db.exists():
            return []
        with self._connect_ro(self.review_db) as c:
            if not self._table_exists(c, 'research_reviews'):
                return []
            reviews = [dict(r) for r in c.execute(
                'SELECT review_id,target_type,target_id,target_checksum,title,state,created_at,updated_at,created_by,engine_md5 '
                'FROM research_reviews ORDER BY updated_at DESC'
            )]
            annotation_counts = Counter()
            if self._table_exists(c, 'research_review_annotations'):
                annotation_counts.update(dict(c.execute(
                    'SELECT review_id,COUNT(*) FROM research_review_annotations GROUP BY review_id'
                ).fetchall()))
            event_counts = Counter()
            if self._table_exists(c, 'research_review_events'):
                event_counts.update(dict(c.execute(
                    'SELECT review_id,COUNT(*) FROM research_review_events GROUP BY review_id'
                ).fetchall()))
        for review in reviews:
            review['annotation_count'] = int(annotation_counts.get(review['review_id'], 0))
            review['event_count'] = int(event_counts.get(review['review_id'], 0))
        return reviews

    def analyze(self) -> dict[str, Any]:
        targets = self._targets()
        reviews = self._reviews()
        target_map = {(t['target_type'], t['target_id']): t for t in targets}
        review_map = {(r['target_type'], r['target_id']): r for r in reviews}

        state_counts = Counter(r['state'] for r in reviews)
        type_counts = Counter(t['target_type'] for t in targets)
        reviewed_type_counts = Counter(r['target_type'] for r in reviews if (r['target_type'], r['target_id']) in target_map)
        reviewer_workload: dict[str, dict[str, Any]] = defaultdict(lambda: {
            'review_count': 0, 'annotation_count': 0, 'states': Counter(), 'finalized_count': 0,
        })
        checksum_ok = 0
        checksum_failed = 0
        stale_reviews = []
        orphan_reviews = []
        engine_mismatch_reviews = []

        for review in reviews:
            actor = review.get('created_by') or 'unknown'
            workload = reviewer_workload[actor]
            workload['review_count'] += 1
            workload['annotation_count'] += int(review.get('annotation_count', 0))
            workload['states'][review['state']] += 1
            if review['state'] in {'APPROVED', 'REJECTED'}:
                workload['finalized_count'] += 1

            key = (review['target_type'], review['target_id'])
            target = target_map.get(key)
            if not target:
                orphan_reviews.append(review)
            elif review.get('target_checksum') == target.get('target_checksum'):
                checksum_ok += 1
            else:
                checksum_failed += 1
                stale_reviews.append({
                    'review_id': review['review_id'], 'target_type': review['target_type'],
                    'target_id': review['target_id'], 'expected_checksum': review.get('target_checksum'),
                    'current_checksum': target.get('target_checksum'), 'state': review['state'],
                })
            if review.get('engine_md5') != ENGINE_MD5:
                engine_mismatch_reviews.append({
                    'review_id': review['review_id'], 'engine_md5': review.get('engine_md5')
                })

        unreviewed = [t for t in targets if (t['target_type'], t['target_id']) not in review_map]
        total_targets = len(targets)
        reviewed_targets = total_targets - len(unreviewed)
        coverage_rate = reviewed_targets / total_targets if total_targets else 0.0
        approved = int(state_counts.get('APPROVED', 0))
        approval_rate = approved / reviewed_targets if reviewed_targets else 0.0
        integrity_total = checksum_ok + checksum_failed
        integrity_rate = checksum_ok / integrity_total if integrity_total else 1.0

        workload_rows = []
        for reviewer, value in sorted(reviewer_workload.items(), key=lambda kv: (-kv[1]['review_count'], kv[0])):
            workload_rows.append({
                'reviewer': reviewer,
                'review_count': value['review_count'],
                'annotation_count': value['annotation_count'],
                'finalized_count': value['finalized_count'],
                'state_counts': dict(value['states']),
            })

        type_coverage = {}
        for target_type in sorted(set(type_counts) | set(reviewed_type_counts)):
            total = int(type_counts.get(target_type, 0))
            reviewed = int(reviewed_type_counts.get(target_type, 0))
            type_coverage[target_type] = {
                'total': total,
                'reviewed': reviewed,
                'unreviewed': max(total - reviewed, 0),
                'coverage_rate': reviewed / total if total else 0.0,
            }

        report = {
            'schema': SCHEMA_VERSION,
            'generated_at': _now(),
            'engine_md5': ENGINE_MD5,
            'summary': {
                'total_targets': total_targets,
                'reviewed_targets': reviewed_targets,
                'unreviewed_targets': len(unreviewed),
                'coverage_rate': coverage_rate,
                'approved_reviews': approved,
                'approval_rate': approval_rate,
                'checksum_integrity_rate': integrity_rate,
                'checksum_failures': checksum_failed,
                'orphan_reviews': len(orphan_reviews),
                'engine_mismatch_reviews': len(engine_mismatch_reviews),
            },
            'state_counts': dict(state_counts),
            'type_coverage': type_coverage,
            'unreviewed_targets': unreviewed,
            'stale_reviews': stale_reviews,
            'orphan_reviews': orphan_reviews,
            'engine_mismatch_reviews': engine_mismatch_reviews,
            'reviewer_workload': workload_rows,
            'scientific_boundary': {
                'workspace_read_only': True,
                'review_ledger_read_only': True,
                'approval_is_governance_metadata_only': True,
                'research_result_mutation': False,
                'decision_engine_invocation': False,
                'automatic_tuning': False,
                'canonical_database_write': False,
            },
            'limitations': [
                'Coverage measures workflow completion, not scientific validity.',
                'Approval does not establish profitability, causality, or out-of-sample robustness.',
                'Reviewer workload is descriptive and must not be used as a performance score.',
                'Checksum integrity confirms artifact identity only; it does not validate methodology.',
            ],
        }
        report['report_sha256'] = _sha(report)
        return report

    def export_json(self, path: str) -> str:
        report = self.analyze()
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
        return str(p)

    def export_html(self, path: str) -> str:
        r = self.analyze(); s = r['summary']
        state_rows = ''.join(f'<tr><td>{html.escape(k)}</td><td>{v}</td></tr>' for k, v in sorted(r['state_counts'].items())) or '<tr><td colspan="2">No reviews</td></tr>'
        unreviewed_rows = ''.join(
            f"<tr><td>{html.escape(x['target_type'])}</td><td>{html.escape(str(x['target_id']))}</td><td>{html.escape(str(x.get('title') or ''))}</td></tr>"
            for x in r['unreviewed_targets']
        ) or '<tr><td colspan="3">None</td></tr>'
        workload_rows = ''.join(
            f"<tr><td>{html.escape(x['reviewer'])}</td><td>{x['review_count']}</td><td>{x['annotation_count']}</td><td>{x['finalized_count']}</td></tr>"
            for x in r['reviewer_workload']
        ) or '<tr><td colspan="4">No reviewer workload</td></tr>'
        body = f'''<!doctype html><meta charset="utf-8"><title>Research Governance Dashboard</title>
<h1>Research Governance Dashboard & Review Coverage</h1>
<p>Generated: {html.escape(r['generated_at'])}</p>
<ul><li>Total targets: {s['total_targets']}</li><li>Reviewed: {s['reviewed_targets']}</li><li>Coverage: {s['coverage_rate']:.1%}</li><li>Approved: {s['approved_reviews']}</li><li>Checksum integrity: {s['checksum_integrity_rate']:.1%}</li></ul>
<h2>Review states</h2><table border="1" cellpadding="6"><tr><th>State</th><th>Count</th></tr>{state_rows}</table>
<h2>Unreviewed targets</h2><table border="1" cellpadding="6"><tr><th>Type</th><th>ID</th><th>Title</th></tr>{unreviewed_rows}</table>
<h2>Reviewer workload</h2><table border="1" cellpadding="6"><tr><th>Reviewer</th><th>Reviews</th><th>Annotations</th><th>Finalized</th></tr>{workload_rows}</table>
<p><strong>Scientific boundary:</strong> read-only governance metadata; no research result mutation; no Decision Engine invocation; no automatic tuning; no canonical database writes.</p>'''
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(body, encoding='utf-8')
        return str(p)
