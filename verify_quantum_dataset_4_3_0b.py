from __future__ import annotations
import argparse
import json
from pathlib import Path
from dvs_ai.services.quantum_dataset import QuantumDatasetFactory


def main() -> int:
    p=argparse.ArgumentParser(description="Build and verify governed Quantum research dataset")
    p.add_argument("--db", default="data/dvs_paper_trades.db")
    p.add_argument("--output", default="artifacts/quantum_dataset")
    p.add_argument("--engine-checksum", default=None)
    p.add_argument("--allow-list", default="governance/allowed_quantum_parameters.json")
    args=p.parse_args()
    result=QuantumDatasetFactory(args.db, allowed_parameters_path=args.allow_list,
        expected_decision_engine_checksum=args.engine_checksum).build()
    dataset, manifest=result.export(args.output)
    print(json.dumps({
        "state": result.state.value,
        "raw_episode_count": result.raw_episode_count,
        "decisive_count": result.decisive_count,
        "effective_n": result.effective_n,
        "optimizer_allowed": result.optimizer_allowed,
        "recommendation_allowed": result.recommendation_allowed,
        "shadow_apply_allowed": result.shadow_apply_allowed,
        "dataset": str(dataset), "manifest": str(manifest)
    }, indent=2))
    return 0 if all(x.passed for x in result.findings) else 2

if __name__ == "__main__": raise SystemExit(main())
