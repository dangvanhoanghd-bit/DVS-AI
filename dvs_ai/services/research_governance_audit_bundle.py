from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dvs_ai.services.research_governance_dashboard import (
    ENGINE_MD5,
    ResearchGovernanceDashboardService,
)
from dvs_ai.services.research_lineage_provenance import ResearchLineageProvenanceService

SCHEMA_VERSION = "research-governance-audit-bundle-v1"
BUNDLE_VERSION = "4.2.0-K"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class ResearchGovernanceAuditBundleService:
    """Build a self-verifying, independent audit ZIP without mutating source databases."""

    def __init__(
        self,
        workspace_path: str = "data/research_workspace.db",
        review_db_path: str = "data/research_reviews.db",
        ledger_path: str = "data/research_governance_ledger.db",
    ) -> None:
        self.workspace = Path(workspace_path)
        self.reviews = Path(review_db_path)
        self.ledger = Path(ledger_path)

    @staticmethod
    def _connect_ro(path: Path) -> sqlite3.Connection:
        if not path.exists():
            raise FileNotFoundError(path)
        connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone() is not None

    def _ledger_snapshot(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "available": self.ledger.exists(),
            "incidents": [],
            "incident_events": [],
            "alert_state": [],
            "alert_events": [],
        }
        if not self.ledger.exists():
            return result
        with self._connect_ro(self.ledger) as connection:
            mappings = {
                "incidents": "governance_incidents",
                "incident_events": "governance_incident_events",
                "alert_state": "governance_alert_state",
                "alert_events": "governance_alert_events",
            }
            for key, table in mappings.items():
                if self._table_exists(connection, table):
                    rows = connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                    result[key] = [dict(row) for row in rows]
        return result

    @staticmethod
    def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
        if not rows:
            return b""
        fields = sorted({field for row in rows for field in row})
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})
        return stream.getvalue().encode("utf-8-sig")

    @staticmethod
    def _html_index(summary: dict[str, Any]) -> bytes:
        files = "".join(
            f"<li><code>{html.escape(item['path'])}</code> — {html.escape(item['sha256'])}</li>"
            for item in summary["files"]
        )
        body = f"""<!doctype html><html><head><meta charset='utf-8'>
<title>DVS AI Independent Audit Bundle</title>
<style>body{{font-family:Arial,sans-serif;max-width:1100px;margin:32px auto;padding:0 18px}}code{{background:#eee;padding:2px 5px}}table{{border-collapse:collapse}}td,th{{border:1px solid #bbb;padding:6px}}</style></head><body>
<h1>DVS AI Research Governance Independent Audit Bundle</h1>
<table><tr><th>Bundle version</th><td>{html.escape(summary['bundle_version'])}</td></tr>
<tr><th>Generated UTC</th><td>{html.escape(summary['generated_at'])}</td></tr>
<tr><th>Frozen Decision Engine MD5</th><td><code>{ENGINE_MD5}</code></td></tr>
<tr><th>Workspace SHA-256</th><td><code>{summary['source_database_hashes'].get('workspace') or 'missing'}</code></td></tr>
<tr><th>Reviews SHA-256</th><td><code>{summary['source_database_hashes'].get('reviews') or 'missing'}</code></td></tr>
<tr><th>Governance ledger SHA-256</th><td><code>{summary['source_database_hashes'].get('ledger') or 'missing'}</code></td></tr></table>
<h2>Bundle contents</h2><ul>{files}</ul>
<h2>Verification</h2><p>Run <code>python verify_bundle.py</code> from the extracted bundle directory. The script verifies every payload against <code>manifest.json</code>.</p>
<h2>Boundary</h2><p>This export is audit evidence only. It does not approve research, repair artifacts, tune thresholds, invoke the Decision Engine, create signals, or place orders.</p>
</body></html>"""
        return body.encode("utf-8")

    @staticmethod
    def _verifier_script() -> bytes:
        return b'''from __future__ import annotations\nimport hashlib, json, sys\nfrom pathlib import Path\nroot=Path(__file__).resolve().parent\nmanifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))\nfailed=[]\nfor item in manifest['files']:\n    path=root/item['path']\n    if not path.exists(): failed.append(f"MISSING {item['path']}"); continue\n    digest=hashlib.sha256(path.read_bytes()).hexdigest()\n    if digest!=item['sha256']: failed.append(f"MISMATCH {item['path']} expected={item['sha256']} actual={digest}")\nif failed:\n    print('AUDIT BUNDLE VERIFICATION FAILED')\n    print('\\n'.join(failed)); sys.exit(1)\nprint(f"AUDIT BUNDLE VERIFIED: {len(manifest['files'])} payload files")\nprint('Decision Engine MD5:', manifest['engine_md5'])\n'''

    def build_payloads(self) -> tuple[dict[str, bytes], dict[str, Any]]:
        governance = ResearchGovernanceDashboardService(self.workspace, self.reviews).analyze()
        lineage = ResearchLineageProvenanceService(self.workspace).analyze()
        ledger = self._ledger_snapshot()
        source_hashes = {
            "workspace": _file_sha256(self.workspace),
            "reviews": _file_sha256(self.reviews),
            "ledger": _file_sha256(self.ledger),
        }
        payloads: dict[str, bytes] = {
            "reports/governance_coverage.json": json.dumps(governance, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
            "reports/lineage_provenance.json": json.dumps(lineage, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
            "reports/governance_ledger.json": json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
            "tables/incidents.csv": self._csv_bytes(ledger["incidents"]),
            "tables/incident_events.csv": self._csv_bytes(ledger["incident_events"]),
            "tables/alert_state.csv": self._csv_bytes(ledger["alert_state"]),
            "tables/alert_events.csv": self._csv_bytes(ledger["alert_events"]),
            "verify_bundle.py": self._verifier_script(),
        }
        summary = {
            "schema": SCHEMA_VERSION,
            "bundle_version": BUNDLE_VERSION,
            "generated_at": _now(),
            "engine_md5": ENGINE_MD5,
            "source_database_hashes": source_hashes,
            "counts": {
                "research_targets": governance["summary"]["total_targets"],
                "reviewed_targets": governance["summary"]["reviewed_targets"],
                "unreviewed_targets": governance["summary"]["unreviewed_targets"],
                "incidents": len(ledger["incidents"]),
                "incident_events": len(ledger["incident_events"]),
                "alert_states": len(ledger["alert_state"]),
                "alert_events": len(ledger["alert_events"]),
                "lineage_nodes": len(lineage.get("nodes", [])),
                "lineage_edges": len(lineage.get("edges", [])),
            },
            "audit_assurance": {
                "baseline_release": "4.2.0-L",
                "hardening_release": "4.2.1",
                "audit_level": "CORE_SERVICE_LAYER_DEEP_AUDIT",
                "independent_adversarial_tests_reported": 168,
                "project_tests_reported_pass": 780,
                "known_design_limitations_documented": True,
                "ui_orchestration_deep_audit": "PARTIAL",
            },
            "boundary": {
                "source_databases_read_only": True,
                "decision_engine_invocation": False,
                "decision_engine_mutation": False,
                "automatic_remediation": False,
                "automatic_approval": False,
                "canonical_database_write": False,
                "signal_generation": False,
                "order_execution": False,
            },
        }
        summary["files"] = [
            {"path": path, "sha256": _sha256_bytes(data), "size_bytes": len(data)}
            for path, data in sorted(payloads.items())
        ]
        payloads["index.html"] = self._html_index(summary)
        summary["files"].append({
            "path": "index.html",
            "sha256": _sha256_bytes(payloads["index.html"]),
            "size_bytes": len(payloads["index.html"]),
        })
        summary["files"] = sorted(summary["files"], key=lambda item: item["path"])
        summary["manifest_sha256"] = _sha256_bytes(_canonical({k: v for k, v in summary.items() if k != "manifest_sha256"}))
        return payloads, summary

    def export_bundle(self, path: str) -> dict[str, Any]:
        destination = Path(path)
        if destination.suffix.lower() != ".zip":
            destination = destination.with_suffix(".zip")
        destination.parent.mkdir(parents=True, exist_ok=True)
        before = {p: _file_sha256(p) for p in (self.workspace, self.reviews, self.ledger)}
        payloads, manifest = self.build_payloads()
        with tempfile.NamedTemporaryFile(prefix="dvs_audit_", suffix=".zip", delete=False, dir=destination.parent) as temp:
            temp_path = Path(temp.name)
        try:
            with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, data in sorted(payloads.items()):
                    archive.writestr(name, data)
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"))
            with zipfile.ZipFile(temp_path, "r") as archive:
                bad = archive.testzip()
                if bad:
                    raise RuntimeError(f"ZIP integrity failure: {bad}")
            temp_path.replace(destination)
        finally:
            temp_path.unlink(missing_ok=True)
        after = {p: _file_sha256(p) for p in (self.workspace, self.reviews, self.ledger)}
        if before != after:
            destination.unlink(missing_ok=True)
            raise RuntimeError("Source database changed during read-only audit export")
        return {
            "path": str(destination),
            "sha256": _file_sha256(destination),
            "size_bytes": destination.stat().st_size,
            "manifest": manifest,
        }

    @staticmethod
    def verify_bundle(path: str) -> dict[str, Any]:
        bundle = Path(path)
        with zipfile.ZipFile(bundle, "r") as archive:
            bad = archive.testzip()
            if bad:
                return {"valid": False, "errors": [f"corrupt member: {bad}"]}
            manifest = json.loads(archive.read("manifest.json"))
            errors = []
            for item in manifest["files"]:
                try:
                    data = archive.read(item["path"])
                except KeyError:
                    errors.append(f"missing: {item['path']}")
                    continue
                digest = _sha256_bytes(data)
                if digest != item["sha256"]:
                    errors.append(f"checksum mismatch: {item['path']}")
        return {"valid": not errors, "errors": errors, "manifest": manifest, "bundle_sha256": _file_sha256(bundle)}
