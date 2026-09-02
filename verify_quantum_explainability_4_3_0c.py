from __future__ import annotations

import argparse
import json
from pathlib import Path

from dvs_ai.services.quantum_explainability import (
    QuantumExplainabilityFoundation,
    verify_explanation_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and independently verify Quantum decision explanations")
    parser.add_argument("--dataset", default="artifacts/quantum_dataset/quantum_research_dataset.jsonl")
    parser.add_argument("--dataset-manifest", default="artifacts/quantum_dataset/quantum_research_dataset.manifest.json")
    parser.add_argument("--output", default="artifacts/quantum_explainability")
    args = parser.parse_args()

    result = QuantumExplainabilityFoundation(args.dataset, args.dataset_manifest).build()
    records, manifest = result.export(args.output)
    verified, detail = verify_explanation_bundle(records, manifest)
    print(json.dumps({
        "state": result.state.value,
        "dataset_integrity_verified": result.dataset_integrity_verified,
        "explanation_count": result.explanation_count,
        "verified_count": result.verified_count,
        "incomplete_count": result.incomplete_count,
        "optimizer_allowed": result.optimizer_allowed,
        "recommendation_allowed": result.recommendation_allowed,
        "shadow_apply_allowed": result.shadow_apply_allowed,
        "main_write_authority": result.main_write_authority,
        "bundle_verified": verified,
        "verification_detail": detail,
        "records": str(records),
        "manifest": str(manifest),
    }, indent=2))
    return 0 if verified and result.dataset_integrity_verified else 2


if __name__ == "__main__":
    raise SystemExit(main())
