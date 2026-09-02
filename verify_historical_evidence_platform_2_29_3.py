from __future__ import annotations

from pathlib import Path


def main() -> int:
    required = [
        Path("dvs_ai/services/historical_evidence_repository.py"),
        Path("dvs_ai/services/candidate_lifecycle_store.py"),
        Path("dvs_ai/services/historical_candidate_store.py"),
        Path("dvs_ai/services/historical_readiness_trend.py"),
        Path("dvs_ai/ui/truth_dashboard.py"),
        Path("tests/test_v2293_historical_evidence_platform_completion.py"),
        Path("HISTORICAL_EVIDENCE_PLATFORM_TRUTH_AUDIT_2.29.3.md"),
        Path("HISTORICAL_EVIDENCE_PLATFORM_TRUTH_MANIFEST.json"),
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("Missing release files: " + ", ".join(missing))
    repo = required[0].read_text(encoding="utf-8")
    ui = Path("dvs_ai/ui/truth_dashboard.py").read_text(encoding="utf-8")
    version = Path("dvs_ai/__init__.py").read_text(encoding="utf-8")
    assert "class HistoricalEvidenceRepository" in repo
    assert "def audit_integrity" in repo
    assert "def dossier" in repo
    assert "def comparison" in repo
    assert "Historical Evidence Integrity" in ui
    assert "history_comparison_table" in ui
    assert "candidate_lifecycle_detail" in ui
    assert "2.29.3-alpha" in version
    forbidden = ("send_order", "PositionSizer", "TradeIntent", "promote_to_main")
    assert not any(token in repo for token in forbidden)
    print("Historical Evidence Platform 2.29.3 verifier: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
