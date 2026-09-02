from __future__ import annotations
import argparse
from dvs_ai.services.quantum_counterfactual import verify_replay_bundle

p = argparse.ArgumentParser(description="Verify a DVS AI 4.3.0D-1 replay bundle")
p.add_argument("records")
p.add_argument("manifest")
a = p.parse_args()
ok, detail = verify_replay_bundle(a.records, a.manifest)
print("PASS" if ok else "FAIL", detail)
raise SystemExit(0 if ok else 1)
