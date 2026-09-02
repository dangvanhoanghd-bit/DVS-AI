from __future__ import annotations

import hashlib
import html
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE_MD5 = '72cf7d54e1ed6369400683358da8c0ef'
SCHEMA_VERSION = 'research-review-v1'
TARGET_TYPES = {'EXPERIMENT', 'COMPARISON', 'COHORT', 'LINEAGE_REPORT', 'COHORT_DIAGNOSTICS'}
REVIEW_STATES = {'DRAFT', 'IN_REVIEW', 'CHANGES_REQUESTED', 'APPROVED', 'REJECTED'}
ALLOWED_TRANSITIONS = {
    'DRAFT': {'IN_REVIEW'},
    'IN_REVIEW': {'CHANGES_REQUESTED', 'APPROVED', 'REJECTED'},
    'CHANGES_REQUESTED': {'IN_REVIEW'},
    'APPROVED': set(),
    'REJECTED': set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


class ResearchReviewWorkflowService:
    """Append-only research review ledger isolated from research results and the Decision Engine."""

    def __init__(
        self,
        workspace_path: str = 'data/research_workspace.db',
        review_db_path: str = 'data/research_reviews.db',
    ):
        self.workspace = Path(workspace_path)
        self.review_db = Path(review_db_path)
        self.review_db.parent.mkdir(parents=True, exist_ok=True)
        self._schema()

    def _connect(self):
        c = sqlite3.connect(self.review_db)
        c.row_factory = sqlite3.Row
        return c

    def _workspace_ro(self):
        if not self.workspace.exists():
            raise FileNotFoundError(self.workspace)
        c = sqlite3.connect(f'file:{self.workspace.resolve().as_posix()}?mode=ro', uri=True)
        c.row_factory = sqlite3.Row
        return c

    def _schema(self):
        with self._connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS research_reviews(
                review_id TEXT PRIMARY KEY,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                target_checksum TEXT,
                title TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                engine_md5 TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS ux_research_review_target
                ON research_reviews(target_type,target_id);
            CREATE TABLE IF NOT EXISTS research_review_annotations(
                annotation_id TEXT PRIMARY KEY,
                review_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                author TEXT NOT NULL,
                category TEXT NOT NULL,
                note TEXT NOT NULL,
                note_sha256 TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS research_review_events(
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_id TEXT NOT NULL,
                event_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                from_state TEXT,
                to_state TEXT,
                detail_json TEXT NOT NULL,
                event_sha256 TEXT NOT NULL
            );
            ''')

    @staticmethod
    def _table_exists(c: sqlite3.Connection, table: str) -> bool:
        return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None

    def resolve_target(self, target_type: str, target_id: str) -> dict[str, Any]:
        target_type = target_type.strip().upper()
        target_id = target_id.strip()
        if target_type not in TARGET_TYPES:
            raise ValueError('Unsupported review target type')
        if not target_id:
            raise ValueError('Target ID is required')
        table_map = {
            'EXPERIMENT': ('research_experiments', 'experiment_id', 'name', 'result_sha256'),
            'COMPARISON': ('research_comparisons', 'comparison_id', 'verdict', 'report_sha256'),
            'COHORT': ('research_cohorts', 'cohort_id', 'name', 'summary_sha256'),
        }
        if target_type in table_map:
            table, key, label, checksum = table_map[target_type]
            with self._workspace_ro() as c:
                if not self._table_exists(c, table):
                    raise KeyError(f'{table} not found')
                row = c.execute(
                    f'SELECT {key} AS target_id,{label} AS title,{checksum} AS target_checksum FROM {table} WHERE {key}=?',
                    (target_id,),
                ).fetchone()
            if not row:
                raise KeyError('Review target not found')
            return dict(row)
        # Report-like targets are identified by immutable externally supplied checksum/ID.
        return {'target_id': target_id, 'title': target_type.replace('_', ' ').title(), 'target_checksum': target_id}

    def create_review(self, target_type: str, target_id: str, reviewer: str, title: str = '') -> str:
        target = self.resolve_target(target_type, target_id)
        reviewer = reviewer.strip() or 'anonymous-reviewer'
        review_id = str(uuid.uuid4())
        now = _now()
        review_title = title.strip() or str(target.get('title') or f'{target_type}: {target_id}')
        with self._connect() as c:
            try:
                c.execute(
                    'INSERT INTO research_reviews VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (review_id, target_type.upper(), target_id, target.get('target_checksum'), review_title,
                     'DRAFT', now, now, reviewer, ENGINE_MD5),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError('A review already exists for this target') from exc
            self._append_event(c, review_id, 'CREATED', reviewer, None, 'DRAFT', {'target_checksum': target.get('target_checksum')})
        return review_id

    def _append_event(self, c, review_id, event_type, actor, from_state, to_state, detail):
        payload = {
            'review_id': review_id, 'event_type': event_type, 'actor': actor,
            'from_state': from_state, 'to_state': to_state, 'detail': detail,
        }
        c.execute(
            'INSERT INTO research_review_events(review_id,event_at,event_type,actor,from_state,to_state,detail_json,event_sha256) VALUES(?,?,?,?,?,?,?,?)',
            (review_id, _now(), event_type, actor, from_state, to_state, _canonical(detail), _sha(payload)),
        )

    def add_annotation(self, review_id: str, author: str, note: str, category: str = 'GENERAL') -> str:
        note = note.strip()
        if not note:
            raise ValueError('Annotation note is required')
        author = author.strip() or 'anonymous-reviewer'
        category = category.strip().upper() or 'GENERAL'
        annotation_id = str(uuid.uuid4())
        with self._connect() as c:
            review = c.execute('SELECT state FROM research_reviews WHERE review_id=?', (review_id,)).fetchone()
            if not review:
                raise KeyError('Review not found')
            if review['state'] in {'APPROVED', 'REJECTED'}:
                raise ValueError('Finalized reviews are immutable')
            c.execute(
                'INSERT INTO research_review_annotations VALUES(?,?,?,?,?,?,?)',
                (annotation_id, review_id, _now(), author, category, note, hashlib.sha256(note.encode('utf-8')).hexdigest()),
            )
            c.execute('UPDATE research_reviews SET updated_at=? WHERE review_id=?', (_now(), review_id))
            self._append_event(c, review_id, 'ANNOTATED', author, review['state'], review['state'], {'annotation_id': annotation_id, 'category': category})
        return annotation_id

    def transition(self, review_id: str, to_state: str, actor: str, reason: str = '') -> dict[str, Any]:
        to_state = to_state.strip().upper()
        actor = actor.strip() or 'anonymous-reviewer'
        if to_state not in REVIEW_STATES:
            raise ValueError('Invalid review state')
        with self._connect() as c:
            row = c.execute('SELECT * FROM research_reviews WHERE review_id=?', (review_id,)).fetchone()
            if not row:
                raise KeyError('Review not found')
            current = row['state']
            if to_state not in ALLOWED_TRANSITIONS[current]:
                raise ValueError(f'Invalid transition: {current} -> {to_state}')
            if to_state in {'CHANGES_REQUESTED', 'REJECTED'} and not reason.strip():
                raise ValueError('A reason is required for this transition')
            c.execute('UPDATE research_reviews SET state=?,updated_at=? WHERE review_id=?', (to_state, _now(), review_id))
            self._append_event(c, review_id, 'STATE_CHANGED', actor, current, to_state, {'reason': reason.strip()})
        return self.get_review(review_id)

    def verify_target_integrity(self, review_id: str) -> dict[str, Any]:
        review = self.get_review(review_id)
        result = self.verify_target_integrity_shallow(review)
        return {'review_id': review_id, **result}

    def get_review(self, review_id: str) -> dict[str, Any]:
        with self._connect() as c:
            row = c.execute('SELECT * FROM research_reviews WHERE review_id=?', (review_id,)).fetchone()
            if not row:
                raise KeyError('Review not found')
            out = dict(row)
            out['annotations'] = [dict(r) for r in c.execute(
                'SELECT annotation_id,created_at,author,category,note,note_sha256 FROM research_review_annotations WHERE review_id=? ORDER BY created_at,annotation_id',
                (review_id,),
            )]
            out['events'] = [dict(r) for r in c.execute(
                'SELECT event_at,event_type,actor,from_state,to_state,detail_json,event_sha256 FROM research_review_events WHERE review_id=? ORDER BY event_id',
                (review_id,),
            )]
        out['integrity'] = self.verify_target_integrity_shallow(out)
        return out

    def verify_target_integrity_shallow(self, review: dict[str, Any]) -> dict[str, Any]:
        expected = review.get('target_checksum')
        target_type = str(review.get('target_type') or '').upper()
        # Database-backed targets are independently resolved again from the read-only workspace.
        if target_type in {'EXPERIMENT', 'COMPARISON', 'COHORT'}:
            try:
                current = self.resolve_target(target_type, review['target_id']).get('target_checksum')
                return {
                    'expected_checksum': expected,
                    'current_checksum': current,
                    'matches': expected == current,
                    'integrity_level': 2,
                    'verification_basis': 'RECOMPUTED_FROM_READ_ONLY_WORKSPACE',
                    'independently_verifiable': True,
                }
            except Exception as exc:
                return {
                    'expected_checksum': expected, 'current_checksum': None, 'matches': False,
                    'integrity_level': 2, 'verification_basis': 'RECOMPUTE_FAILED',
                    'independently_verifiable': True, 'error': f'{type(exc).__name__}: {exc}',
                }
        # Report-like targets historically used their externally supplied checksum as both ID and checksum.
        # Do not present that tautological comparison as independent integrity verification.
        return {
            'expected_checksum': expected,
            'current_checksum': None,
            'matches': None,
            'integrity_level': 1,
            'verification_basis': 'SELF_ASSERTED_EXTERNAL_CHECKSUM',
            'independently_verifiable': False,
            'status': 'UNVERIFIABLE_WITHOUT_SOURCE_ARTIFACT',
            'limitation': 'Provide the original report artifact or a reproducible generation specification for Level 2 verification.',
        }

    def list_reviews(self) -> list[dict[str, Any]]:
        with self._connect() as c:
            return [dict(r) for r in c.execute(
                'SELECT review_id,target_type,target_id,title,state,created_at,updated_at,created_by,target_checksum FROM research_reviews ORDER BY updated_at DESC'
            )]

    def export_json(self, review_id: str, path: str) -> str:
        report = self.get_review(review_id)
        report['schema'] = SCHEMA_VERSION
        report['scientific_boundary'] = {
            'review_database_only': True,
            'research_result_mutation': False,
            'decision_engine_invocation': False,
            'automatic_tuning': False,
            'canonical_database_write': False,
        }
        report['report_sha256'] = _sha(report)
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
        return str(p)

    def export_html(self, review_id: str, path: str) -> str:
        r = self.get_review(review_id)
        notes = ''.join(
            f"<tr><td>{html.escape(x['created_at'])}</td><td>{html.escape(x['author'])}</td><td>{html.escape(x['category'])}</td><td>{html.escape(x['note'])}</td></tr>"
            for x in r['annotations']
        ) or '<tr><td colspan="4">No annotations</td></tr>'
        body = f'''<!doctype html><meta charset="utf-8"><title>Research Review</title>
<h1>Research Review & Approval Record</h1>
<p><strong>{html.escape(r['title'])}</strong></p>
<p>Target: {html.escape(r['target_type'])} / {html.escape(r['target_id'])}</p>
<p>State: <strong>{html.escape(r['state'])}</strong></p>
<p>Target checksum integrity: {('PASS' if r['integrity']['matches'] is True else 'FAIL' if r['integrity']['matches'] is False else 'UNVERIFIABLE')}</p>
<p>Integrity level: {r['integrity'].get('integrity_level')} · Basis: {html.escape(str(r['integrity'].get('verification_basis')))}</p>
<h2>Annotations</h2><table border="1" cellspacing="0" cellpadding="6"><tr><th>Time</th><th>Author</th><th>Category</th><th>Note</th></tr>{notes}</table>
<p><strong>Scientific boundary:</strong> review-ledger write only; no experiment result mutation; no Decision Engine invocation; no automatic tuning; no canonical database writes.</p>'''
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(body, encoding='utf-8')
        return str(p)
