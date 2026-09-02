from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path
from .requirement_registry import REQUIREMENTS

_VALID_LEVELS={"A","B","C"}; _VALID_SOURCES={"SOURCE","RUNTIME","SOURCE+RUNTIME"}

def evaluate_readiness() -> dict:
    missing=[]; duplicate=[]; invalid=[]; seen=set()
    for r in REQUIREMENTS:
        if r.requirement_id in seen: duplicate.append(r.requirement_id)
        seen.add(r.requirement_id)
        if not all((r.requirement_id,r.normative,r.verification_method,r.verification_source,r.required_evidence_level)):
            missing.append(r.requirement_id or "<missing-id>")
        if r.required_evidence_level not in _VALID_LEVELS or r.verification_source not in _VALID_SOURCES:
            invalid.append(r.requirement_id)
    gaps=sorted(set(missing+duplicate+invalid))
    return {
      "schema_version":"1.0", "generated_at_utc":datetime.now(timezone.utc).isoformat(),
      "technical_standard_status":"DRAFT_READY_FOR_VALIDATION",
      "draft_ready":not gaps, "requirement_count":len(REQUIREMENTS),
      "missing_verification_methods":sorted(set(missing)),
      "duplicate_requirement_ids":sorted(set(duplicate)),
      "invalid_requirement_metadata":sorted(set(invalid)),
      "unverifiable_must":gaps,
    }

def write_readiness(path: str | Path) -> dict:
    payload=evaluate_readiness(); p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return payload
