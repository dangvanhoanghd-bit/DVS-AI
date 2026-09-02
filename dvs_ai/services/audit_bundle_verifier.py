from __future__ import annotations

import hashlib
import html
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from dvs_ai.services.research_governance_dashboard import ENGINE_MD5

VERIFIER_SCHEMA = "independent-audit-bundle-verification-v1"
SUPPORTED_AUDIT_SCHEMAS = {"research-governance-audit-bundle-v1"}
REQUIRED_MANIFEST_FIELDS = {
    "schema", "bundle_version", "generated_at", "engine_md5", "files",
    "source_database_hashes", "counts", "boundary", "manifest_sha256",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class IndependentAuditBundleVerifier:
    """Verify a transferred audit ZIP without importing or mutating DVS AI data."""

    def __init__(self, expected_engine_md5: str = ENGINE_MD5, strict: bool = False) -> None:
        self.expected_engine_md5 = expected_engine_md5
        self.strict = bool(strict)

    @staticmethod
    def _safe_member(name: str) -> bool:
        path = PurePosixPath(name)
        return bool(name) and not path.is_absolute() and ".." not in path.parts and "\\" not in name

    @staticmethod
    def _manifest_integrity(manifest: dict[str, Any]) -> tuple[bool, str | None, str | None]:
        expected = manifest.get("manifest_sha256")
        if not isinstance(expected, str) or len(expected) != 64:
            return False, expected if isinstance(expected, str) else None, None
        material = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        actual = _sha256_bytes(_canonical(material))
        return expected == actual, expected, actual

    def verify(self, path: str) -> dict[str, Any]:
        bundle = Path(path)
        report: dict[str, Any] = {
            "schema": VERIFIER_SCHEMA,
            "verified_at": _now(),
            "bundle_path": str(bundle),
            "bundle_sha256": _file_sha256(bundle),
            "status": "FAILED",
            "valid": False,
            "manifest_status": "NOT_CHECKED",
            "engine_status": "NOT_CHECKED",
            "payload_status": "NOT_CHECKED",
            "expected_engine_md5": self.expected_engine_md5,
            "bundle_engine_md5": None,
            "verification_mode": "STRICT" if self.strict else "NORMAL",
            "manifest": None,
            "summary": {},
            "payloads": [],
            "errors": [],
            "warnings": [],
            "boundary": {
                "read_only_verification": True,
                "data_import": False,
                "database_write": False,
                "decision_engine_execution": False,
                "decision_engine_mutation": False,
            },
        }
        if not bundle.is_file():
            report["errors"].append("Bundle file does not exist")
            return report
        if not zipfile.is_zipfile(bundle):
            report["errors"].append("Selected file is not a valid ZIP archive")
            return report

        try:
            with zipfile.ZipFile(bundle, "r") as archive:
                corrupt = archive.testzip()
                if corrupt:
                    report["errors"].append(f"Corrupt ZIP member: {corrupt}")
                    return report
                names = archive.namelist()
                unsafe = [name for name in names if not self._safe_member(name)]
                if unsafe:
                    report["errors"].append(f"Unsafe archive path(s): {', '.join(unsafe[:5])}")
                    return report
                if names.count("manifest.json") != 1:
                    report["errors"].append("Bundle must contain exactly one manifest.json")
                    return report
                try:
                    manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    report["errors"].append(f"Invalid manifest.json: {exc}")
                    return report
                if not isinstance(manifest, dict):
                    report["errors"].append("Manifest root must be an object")
                    return report
                report["manifest"] = manifest
                missing_fields = sorted(REQUIRED_MANIFEST_FIELDS - set(manifest))
                if missing_fields:
                    report["errors"].append("Missing manifest field(s): " + ", ".join(missing_fields))
                schema = manifest.get("schema")
                if schema not in SUPPORTED_AUDIT_SCHEMAS:
                    report["errors"].append(f"Unsupported audit schema: {schema!r}")
                manifest_ok, manifest_expected, manifest_actual = self._manifest_integrity(manifest)
                report["manifest_sha256_expected"] = manifest_expected
                report["manifest_sha256_actual"] = manifest_actual
                if not manifest_ok:
                    report["errors"].append("Manifest SHA-256 mismatch or invalid manifest_sha256")
                report["manifest_status"] = "PASS" if not missing_fields and schema in SUPPORTED_AUDIT_SCHEMAS and manifest_ok else "FAIL"

                bundle_engine = manifest.get("engine_md5")
                report["bundle_engine_md5"] = bundle_engine
                if bundle_engine == self.expected_engine_md5:
                    report["engine_status"] = "PASS"
                else:
                    report["engine_status"] = "FAIL"
                    report["errors"].append(
                        f"Frozen Decision Engine MD5 mismatch: expected={self.expected_engine_md5} actual={bundle_engine}"
                    )

                entries = manifest.get("files")
                if not isinstance(entries, list):
                    report["errors"].append("Manifest files must be a list")
                    entries = []
                seen: set[str] = set()
                for raw in entries:
                    item: dict[str, Any] = {
                        "path": None, "expected_sha256": None, "actual_sha256": None,
                        "expected_size_bytes": None, "actual_size_bytes": None, "status": "FAIL",
                    }
                    if not isinstance(raw, dict):
                        item["error"] = "Invalid payload descriptor"
                        report["payloads"].append(item)
                        continue
                    name = raw.get("path")
                    item["path"] = name
                    item["expected_sha256"] = raw.get("sha256")
                    item["expected_size_bytes"] = raw.get("size_bytes")
                    if not isinstance(name, str) or not self._safe_member(name) or name == "manifest.json":
                        item["error"] = "Invalid payload path"
                    elif name in seen:
                        item["error"] = "Duplicate payload path in manifest"
                    else:
                        seen.add(name)
                        try:
                            data = archive.read(name)
                        except KeyError:
                            item["error"] = "Missing payload"
                        else:
                            item["actual_sha256"] = _sha256_bytes(data)
                            item["actual_size_bytes"] = len(data)
                            checksum_ok = item["actual_sha256"] == item["expected_sha256"]
                            size_expected = item["expected_size_bytes"]
                            size_ok = isinstance(size_expected, int) and size_expected == len(data)
                            if checksum_ok and size_ok:
                                item["status"] = "PASS"
                            else:
                                item["error"] = "Checksum mismatch" if not checksum_ok else "Size mismatch"
                    report["payloads"].append(item)
                payload_failures = [item for item in report["payloads"] if item["status"] != "PASS"]
                if payload_failures:
                    report["errors"].extend(
                        f"Payload verification failed: {item.get('path') or '<invalid>'} ({item.get('error', 'invalid')})"
                        for item in payload_failures
                    )
                report["payload_status"] = "PASS" if entries and not payload_failures else "FAIL"
                unlisted = sorted(set(names) - seen - {"manifest.json"})
                if unlisted:
                    message = "Unlisted archive member(s): " + ", ".join(unlisted[:20])
                    if self.strict:
                        report["errors"].append(message + " [strict mode]")
                    else:
                        report["warnings"].append(message)
                report["summary"] = {
                    "bundle_version": manifest.get("bundle_version"),
                    "created_utc": manifest.get("generated_at"),
                    "source_database_hashes": manifest.get("source_database_hashes", {}),
                    "counts": manifest.get("counts", {}),
                    "payload_count": len(report["payloads"]),
                    "payload_pass_count": sum(item["status"] == "PASS" for item in report["payloads"]),
                }
        except (OSError, zipfile.BadZipFile) as exc:
            report["errors"].append(f"Unable to read bundle: {exc}")
            return report

        report["valid"] = not report["errors"] and all(
            report[key] == "PASS" for key in ("manifest_status", "engine_status", "payload_status")
        )
        report["status"] = "VERIFIED" if report["valid"] else "FAILED"
        return report

    @staticmethod
    def export_json(report: dict[str, Any], path: str) -> str:
        destination = Path(path)
        if destination.suffix.lower() != ".json":
            destination = destination.with_suffix(".json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return str(destination)

    @staticmethod
    def export_html(report: dict[str, Any], path: str) -> str:
        destination = Path(path)
        if destination.suffix.lower() not in {".html", ".htm"}:
            destination = destination.with_suffix(".html")
        rows = "".join(
            "<tr><td>{}</td><td><code>{}</code></td><td><code>{}</code></td><td>{}</td></tr>".format(
                html.escape(str(item.get("path"))),
                html.escape(str(item.get("expected_sha256"))),
                html.escape(str(item.get("actual_sha256"))),
                html.escape(str(item.get("status"))),
            )
            for item in report.get("payloads", [])
        )
        errors = "".join(f"<li>{html.escape(str(error))}</li>" for error in report.get("errors", [])) or "<li>None</li>"
        document = f"""<!doctype html><html><head><meta charset='utf-8'><title>DVS AI Audit Verification</title>
<style>body{{font-family:Arial,sans-serif;max-width:1200px;margin:30px auto;padding:0 18px}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #bbb;padding:6px;text-align:left}}code{{word-break:break-all}}</style></head><body>
<h1>DVS AI Independent Audit Bundle Verification</h1>
<p><strong>Status:</strong> {html.escape(str(report.get('status')))} · <strong>Mode:</strong> {html.escape(str(report.get('verification_mode', 'NORMAL')))}</p>
<p><strong>Bundle:</strong> {html.escape(str(report.get('bundle_path')))}</p>
<p><strong>Manifest:</strong> {html.escape(str(report.get('manifest_status')))} · <strong>Engine:</strong> {html.escape(str(report.get('engine_status')))} · <strong>Payloads:</strong> {html.escape(str(report.get('payload_status')))}</p>
<p><strong>Expected frozen engine MD5:</strong> <code>{html.escape(str(report.get('expected_engine_md5')))}</code><br>
<strong>Bundle engine MD5:</strong> <code>{html.escape(str(report.get('bundle_engine_md5')))}</code></p>
<h2>Payload verification</h2><table><tr><th>Payload</th><th>Expected SHA-256</th><th>Actual SHA-256</th><th>Status</th></tr>{rows}</table>
<h2>Errors</h2><ul>{errors}</ul>
<h2>Boundary</h2><p>Read-only verification only. No import, no database write, no Decision Engine execution or mutation.</p>
</body></html>"""
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(document, encoding="utf-8")
        return str(destination)
