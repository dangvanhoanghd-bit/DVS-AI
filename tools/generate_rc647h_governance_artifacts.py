from __future__ import annotations
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
import argparse, json
from dvs_ai.governance.release_identity import write_identity
from dvs_ai.governance.verification_matrix import write_matrix
from dvs_ai.governance.readiness import write_readiness
from dvs_ai.version import APP_VERSION, BUILD_ID

def main():
 p=argparse.ArgumentParser(); p.add_argument("--root",default="."); args=p.parse_args(); root=Path(args.root).resolve()
 identity=write_identity(root,root/"build_identity.json"); write_matrix(root/"technical_standard_matrix.json"); ready=write_readiness(root/"technical_standard_readiness.json")
 (root/"BUILD_ID.txt").write_text(BUILD_ID+"\n",encoding="utf-8")
 (root/"RC6.4.7H_IMPLEMENTATION_STATUS.json").write_text(json.dumps({"app_version":APP_VERSION,"build_id":BUILD_ID,"identity_single_source_ok":identity["single_source_ok"],"technical_standard_draft_ready":ready["draft_ready"],"audit_status":"NOT_AUDITED","burn_in_status":"PENDING"},indent=2)+"\n",encoding="utf-8")
 if not identity["single_source_ok"] or not ready["draft_ready"]: raise SystemExit(2)
if __name__=="__main__": main()
