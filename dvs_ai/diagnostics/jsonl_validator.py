from __future__ import annotations
from dataclasses import asdict, dataclass
import json
from pathlib import Path

@dataclass(frozen=True)
class JsonlValidationResult:
    path: str; total_lines:int; valid_records:int; writer_errors:int; shutdown_truncation:int; external_corruption:int; malformed_total:int
    def to_dict(self): return asdict(self)

def validate_jsonl(path: str | Path, *, shutdown_marked: bool=False) -> JsonlValidationResult:
    p=Path(path); lines=p.read_bytes().splitlines(keepends=True) if p.exists() else []
    valid=writer=shutdown=external=0
    for i,raw in enumerate(lines):
        try: json.loads(raw.decode("utf-8")); valid+=1; continue
        except Exception: pass
        is_tail=i==len(lines)-1
        if is_tail and shutdown_marked: shutdown+=1
        elif is_tail and not raw.endswith((b"\n",b"\r")): external+=1
        else: writer+=1
    malformed=writer+shutdown+external
    return JsonlValidationResult(str(p),len(lines),valid,writer,shutdown,external,malformed)
