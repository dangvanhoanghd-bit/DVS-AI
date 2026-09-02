from __future__ import annotations
import ast, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from dvs_ai.version import APP_VERSION, BUILD_ID

IDENTITY_NAMES={"APP_VERSION","BUILD_ID"}

def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""): h.update(chunk)
    return h.hexdigest()

def find_identity_assignments(root: Path) -> dict[str,list[str]]:
    found={name:[] for name in IDENTITY_NAMES}
    for path in (root/"dvs_ai").rglob("*.py"):
        try: tree=ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError,UnicodeDecodeError): continue
        for node in ast.walk(tree):
            targets=[]
            if isinstance(node,(ast.Assign,ast.AnnAssign)):
                targets=node.targets if isinstance(node,ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target,ast.Name) and target.id in IDENTITY_NAMES:
                    found[target.id].append(f"{path.relative_to(root).as_posix()}:{getattr(node,'lineno',0)}")
    return found

def build_identity(root: str | Path) -> dict:
    root=Path(root)
    critical=["dvs_ai/version.py","dvs_ai/ui/main_window.py","dvs_ai/ui/retention_owner_telemetry.py","dvs_ai/engines/decision_engine.py"]
    files={rel:sha256_file(root/rel) for rel in critical if (root/rel).is_file()}
    assignments=find_identity_assignments(root)
    return {"schema_version":"1.0","generated_at_utc":datetime.now(timezone.utc).isoformat(),"app_version":APP_VERSION,"build_id":BUILD_ID,"identity_assignments":assignments,"single_source_ok":all(len(v)==1 for v in assignments.values()),"critical_files":files}

def write_identity(root: str | Path, path: str | Path) -> dict:
    payload=build_identity(root); p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return payload
