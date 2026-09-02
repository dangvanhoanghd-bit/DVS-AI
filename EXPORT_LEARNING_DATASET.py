from pathlib import Path

from dvs_ai.services.outcome_intelligence import NoLearningSamplesError, OutcomeIntelligenceService

service = OutcomeIntelligenceService("data/dvs_paper_trades.db")
summary = service.maturity_summary()
print(summary.to_dict())

try:
    rows = service.build_dataset()
    if not rows:
        raise NoLearningSamplesError(
            "No learning-ready samples: resolved outcomes and immutable feature snapshots are both required."
        )
    out = Path("exports")
    jsonl = service.export_jsonl(out / "outcome_learning_dataset.jsonl")
    csv = service.export_csv(out / "outcome_learning_dataset.csv")
except NoLearningSamplesError as exc:
    print("LEARNING_DATASET_NOT_GENERATED")
    print(f"Reason: {exc}")
    print(f"Resolved outcomes: {summary.resolved}")
    print(f"Feature snapshots: {summary.feature_snapshots}")
    print(f"Learning-ready samples: {summary.learning_ready}")
else:
    print(f"Exported samples: {len(rows)}")
    print(f"JSONL: {jsonl}")
    print(f"CSV:   {csv}")
