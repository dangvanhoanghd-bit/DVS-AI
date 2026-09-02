from __future__ import annotations

from datetime import datetime
from pathlib import Path

from dvs_ai.services.outcome_analytics import OutcomeAnalyticsService
from dvs_ai.services.outcome_infrastructure import OutcomeInfrastructureStore


def main() -> int:
    root = Path(__file__).resolve().parent
    db = root / "data" / "dvs_paper_trades.db"
    out = root / "reports" / "outcome_analytics"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    service = OutcomeAnalyticsService(OutcomeInfrastructureStore(db))
    json_path = service.export_json(out / f"outcome_analytics_{stamp}.json")
    html_path = service.export_html(out / f"outcome_analytics_{stamp}.html")
    snapshot = service.snapshot()
    print("DVS AI Outcome Analytics exported")
    print(f"Episodes: {snapshot['episode_count']}")
    print(f"Evaluations: {snapshot['evaluation_count']}")
    print(f"JSON: {json_path}")
    print(f"HTML: {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
