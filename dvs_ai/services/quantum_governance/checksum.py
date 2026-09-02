from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_self_hash(manifest: Mapping[str, Any]) -> bool:
    recorded = manifest.get("self_sha256")
    if not isinstance(recorded, str) or not recorded:
        return False
    body = dict(manifest)
    body.pop("self_sha256", None)
    return recorded == canonical_sha256(body)
