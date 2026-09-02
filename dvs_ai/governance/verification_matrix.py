from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path
from .requirement_registry import REQUIREMENTS

def build_matrix() -> dict:
    return {
        "schema_version": "1.0",
        "document_role": "VERIFICATION_METHOD_ONLY_NOT_AUDIT_RESULT",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "requirements": {
            r.requirement_id: {
                "title": r.title,
                "normative": r.normative,
                "verification_method": r.verification_method,
                "verification_source": r.verification_source,
                "required_evidence_level": r.required_evidence_level,
            } for r in REQUIREMENTS
        },
    }

def write_matrix(path: str | Path) -> dict:
    payload=build_matrix(); p=Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    return payload
