from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Iterable
import zipfile

from dvs_ai.diagnostics.jsonl_validator import validate_jsonl
from dvs_ai.governance.release_identity import build_identity
from dvs_ai.governance.readiness import evaluate_readiness
from dvs_ai.governance.verification_matrix import build_matrix
from dvs_ai.version import APP_VERSION, BUILD_ID


@dataclass(frozen=True)
class BurnInBundleResult:
    bundle_dir: str
    zip_path: str
    file_count: int
    runtime_file_count: int
    jsonl_file_count: int
    malformed_total: int
    writer_errors: int
    shutdown_truncation: int
    external_corruption: int
    manifest_sha256: str

    def to_dict(self) -> dict:
        return asdict(self)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _copy_if_exists(root: Path, out: Path, rel_paths: Iterable[str]) -> list[str]:
    copied: list[str] = []
    for rel in rel_paths:
        src = root / rel
        if not src.is_file():
            continue
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(rel)
    return copied


def _runtime_candidates(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for base_rel in ("artifacts/runtime", "runtime", "artifacts"):
        base = root / base_rel
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() in {".json", ".jsonl", ".log", ".txt", ".csv"}:
                candidates.append(path)
    # De-duplicate because artifacts/runtime may also be discovered under artifacts.
    return sorted(set(candidates), key=lambda p: p.as_posix())


def build_burnin_validation_bundle(
    project_root: str | Path,
    output_dir: str | Path,
    *,
    shutdown_marked: bool = False,
    zip_output: bool = True,
) -> BurnInBundleResult:
    """Create an auditor-facing RC6.4.7H burn-in evidence bundle.

    This function packages evidence only. It does not declare PASS/FAIL for the
    build and it does not upgrade the Technical Standard from DRAFT.
    """
    root = Path(project_root).resolve()
    out = Path(output_dir).resolve()
    if out.exists():
        shutil.rmtree(out)
    (out / "source").mkdir(parents=True)
    (out / "runtime").mkdir(parents=True)
    (out / "diagnostics").mkdir(parents=True)

    source_files = _copy_if_exists(
        root,
        out / "source",
        (
            "dvs_ai/version.py",
            "dvs_ai/engines/decision_engine.py",
            "dvs_ai/ui/main_window.py",
            "dvs_ai/ui/retention_owner_telemetry.py",
            "dvs_ai/governance/requirement_registry.py",
            "dvs_ai/governance/verification_matrix.py",
            "dvs_ai/governance/readiness.py",
            "dvs_ai/governance/release_identity.py",
            "dvs_ai/governance/burnin_bundle.py",
            "dvs_ai/monitoring/thread_identity.py",
            "dvs_ai/monitoring/estimator_lifetime.py",
            "dvs_ai/diagnostics/jsonl_validator.py",
        ),
    )

    runtime_files = _runtime_candidates(root)
    runtime_copied: list[str] = []
    jsonl_results: list[dict] = []
    for src in runtime_files:
        rel = src.relative_to(root)
        dst = out / "runtime" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        runtime_copied.append(rel.as_posix())
        if src.suffix.lower() == ".jsonl":
            result = validate_jsonl(src, shutdown_marked=shutdown_marked)
            item = result.to_dict()
            item["relative_path"] = rel.as_posix()
            jsonl_results.append(item)

    identity = build_identity(root)
    readiness = evaluate_readiness()
    matrix = build_matrix()
    _write_json(out / "build_identity.json", identity)
    _write_json(out / "technical_standard_readiness.json", readiness)
    _write_json(out / "technical_standard_matrix.json", matrix)
    _write_json(out / "diagnostics" / "jsonl_validation.json", {
        "schema_version": "1.0",
        "shutdown_marked": shutdown_marked,
        "files": jsonl_results,
        "totals": {
            "jsonl_file_count": len(jsonl_results),
            "malformed_total": sum(x["malformed_total"] for x in jsonl_results),
            "writer_errors": sum(x["writer_errors"] for x in jsonl_results),
            "shutdown_truncation": sum(x["shutdown_truncation"] for x in jsonl_results),
            "external_corruption": sum(x["external_corruption"] for x in jsonl_results),
        },
    })

    summary = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "app_version": APP_VERSION,
        "build_id": BUILD_ID,
        "document_role": "EVIDENCE_PACKAGE_NOT_AUDIT_RESULT",
        "technical_standard_status": "DRAFT_READY_FOR_VALIDATION",
        "audit_contract_version": "1.0",
        "source_files_included": source_files,
        "runtime_files_included": runtime_copied,
        "runtime_domains_expected": ["runtime", "rss", "allocator", "gc", "callback", "memory_budget"],
        "runtime_file_count": len(runtime_copied),
        "jsonl_file_count": len(jsonl_results),
        "identity_single_source_ok": identity["single_source_ok"],
        "technical_standard_draft_ready": readiness["draft_ready"],
        "audit_status": "NOT_AUDITED",
        "regression_status": "PENDING_INDEPENDENT_REVIEW",
        "root_cause_status": "PENDING_INDEPENDENT_REVIEW",
    }
    _write_json(out / "burnin_summary.json", summary)

    manifest_entries: list[dict] = []
    for path in sorted(p for p in out.rglob("*") if p.is_file() and p.name != "MANIFEST_SHA256.json"):
        manifest_entries.append({
            "path": path.relative_to(out).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        })
    manifest = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "file_count": len(manifest_entries),
        "files": manifest_entries,
    }
    manifest_path = out / "MANIFEST_SHA256.json"
    _write_json(manifest_path, manifest)
    manifest_sha = _sha256(manifest_path)

    verify_script = '''from __future__ import annotations\nimport hashlib, json, pathlib, sys\nroot=pathlib.Path(__file__).resolve().parent\nmanifest=json.loads((root/"MANIFEST_SHA256.json").read_text(encoding="utf-8"))\ndef sha(p):\n h=hashlib.sha256()\n with p.open("rb") as f:\n  for c in iter(lambda:f.read(1024*1024),b""): h.update(c)\n return h.hexdigest()\nerrors=[]\nfor item in manifest["files"]:\n p=root/item["path"]\n if not p.is_file(): errors.append({"path":item["path"],"error":"missing"}); continue\n actual=sha(p)\n if actual!=item["sha256"]: errors.append({"path":item["path"],"error":"sha256_mismatch","actual":actual,"expected":item["sha256"]})\nprint(json.dumps({"valid":not errors,"checked":len(manifest["files"]),"errors":errors},indent=2))\nsys.exit(0 if not errors else 2)\n'''
    (out / "verify_bundle.py").write_text(verify_script, encoding="utf-8")

    zip_path = out.with_suffix(".zip")
    if zip_output:
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for path in sorted(p for p in out.rglob("*") if p.is_file()):
                zf.write(path, path.relative_to(out.parent).as_posix())

    totals = {
        "malformed_total": sum(x["malformed_total"] for x in jsonl_results),
        "writer_errors": sum(x["writer_errors"] for x in jsonl_results),
        "shutdown_truncation": sum(x["shutdown_truncation"] for x in jsonl_results),
        "external_corruption": sum(x["external_corruption"] for x in jsonl_results),
    }
    return BurnInBundleResult(
        bundle_dir=str(out),
        zip_path=str(zip_path) if zip_output else "",
        file_count=len(manifest_entries) + 2,
        runtime_file_count=len(runtime_copied),
        jsonl_file_count=len(jsonl_results),
        manifest_sha256=manifest_sha,
        **totals,
    )
