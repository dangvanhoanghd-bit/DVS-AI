from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from dvs_ai.services.quantum_validation.attempt_ledger import AttemptLedger

from .checksum import file_sha256, verify_self_hash
from .ledger_verify import verify_holdout_ledger


@dataclass(frozen=True)
class AuditVerificationResult:
    valid: bool
    violations: Tuple[str, ...]


def verify_audit_bundle(bundle_dir: str | Path) -> AuditVerificationResult:
    root = Path(bundle_dir)
    violations: list[str] = []
    index_path = root / "audit_bundle.index.json"
    if not index_path.is_file():
        return AuditVerificationResult(False, ("INDEX_MISSING",))

    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AuditVerificationResult(False, ("INDEX_UNREADABLE",))

    if not verify_self_hash(index):
        violations.append("INDEX_SELF_HASH_INVALID")

    for filename, expected in index.get("files", {}).items():
        path = root / filename
        if not path.is_file():
            violations.append(f"FILE_MISSING:{filename}")
        elif file_sha256(path) != expected:
            violations.append(f"FILE_HASH_INVALID:{filename}")

    for path in root.glob("*.manifest.json"):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            violations.append(f"MANIFEST_UNREADABLE:{path.name}")
            continue
        if not verify_self_hash(manifest):
            violations.append(f"MANIFEST_SELF_HASH_INVALID:{path.name}")

    holdout_path = root / "holdout_ledger.jsonl"
    if holdout_path.is_file() and not verify_holdout_ledger(holdout_path):
        violations.append("HOLDOUT_LEDGER_INVALID")

    attempt_path = root / "attempt_ledger.jsonl"
    if attempt_path.is_file() and not AttemptLedger(attempt_path).verify():
        violations.append("ATTEMPT_LEDGER_INVALID")

    return AuditVerificationResult(not violations, tuple(violations))
