from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .checksum import canonical_sha256, file_sha256


class AuditBundleBuilder:
    """Builds a read-only, checksum-sealed directory for independent audit."""

    def build(
        self,
        output_dir: str | Path,
        *,
        study_id: str,
        manifests: Mapping[str, Mapping[str, Any]],
        governance_manifest: Mapping[str, Any],
        attempt_ledger_path: str | Path,
        holdout_ledger_path: str | Path,
    ) -> Path:
        target = Path(output_dir)
        if target.exists() and any(target.iterdir()):
            raise FileExistsError("audit bundle target must be empty")
        target.mkdir(parents=True, exist_ok=True)

        files: dict[str, str] = {}
        for name, manifest in sorted(manifests.items()):
            path = target / f"{name}.manifest.json"
            path.write_text(json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False), encoding="utf-8")
            files[path.name] = file_sha256(path)

        governance_path = target / "governance.manifest.json"
        governance_path.write_text(
            json.dumps(governance_manifest, sort_keys=True, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        files[governance_path.name] = file_sha256(governance_path)

        for source, filename in (
            (Path(attempt_ledger_path), "attempt_ledger.jsonl"),
            (Path(holdout_ledger_path), "holdout_ledger.jsonl"),
        ):
            if not source.is_file():
                raise FileNotFoundError(source)
            destination = target / filename
            shutil.copyfile(source, destination)
            files[filename] = file_sha256(destination)

        index: dict[str, Any] = {
            "schema_version": "dvs-quantum-audit-bundle-v1",
            "release": "4.3.0E-3",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "study_id": study_id,
            "governance_state": governance_manifest.get("state"),
            "files": files,
            "immutable_intent": True,
        }
        index["self_sha256"] = canonical_sha256(index)
        (target / "audit_bundle.index.json").write_text(
            json.dumps(index, sort_keys=True, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return target
