from __future__ import annotations
import json, shutil
from pathlib import Path
from .release_identity import write_identity
from .verification_matrix import write_matrix
from .readiness import write_readiness

def prepare_validation_bundle(project_root: str|Path, bundle_root: str|Path) -> Path:
    root=Path(project_root); out=Path(bundle_root); (out/"source").mkdir(parents=True,exist_ok=True); (out/"runtime").mkdir(exist_ok=True); (out/"diagnostics").mkdir(exist_ok=True)
    for rel in ["dvs_ai/version.py","dvs_ai/engines/decision_engine.py","dvs_ai/ui/main_window.py","dvs_ai/ui/retention_owner_telemetry.py"]:
        src=root/rel
        if src.exists():
            dst=out/"source"/rel; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
    write_identity(root,out/"build_identity.json"); write_matrix(out/"technical_standard_matrix.json"); write_readiness(out/"technical_standard_readiness.json")
    summary={"schema_version":"1.0","status":"AWAITING_BURN_IN","required_runtime_domains":["runtime","rss","allocator","gc","callback","memory_budget"]}
    (out/"burnin_summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    return out
