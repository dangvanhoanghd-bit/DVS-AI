from pathlib import Path

from dvs_ai.services.outcome_analytics import OutcomeAnalyticsService
from dvs_ai.services.outcome_infrastructure import OutcomeInfrastructureStore


def test_reliability_exposes_cluster_distribution(tmp_path):
    store = OutcomeInfrastructureStore(tmp_path / "paper.db")
    result = OutcomeAnalyticsService(store).reliability(bootstrap_iterations=0)
    assert result["cluster_size_distribution"] == []


def test_dashboard_is_wired_read_only():
    source = Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")
    dashboard = Path("dvs_ai/ui/statistical_diagnostics_dashboard.py").read_text(encoding="utf-8")
    assert "_build_statistical_diagnostics_tab" in source
    assert '"Statistical Diagnostics"' in source
    assert "OutcomeAnalyticsService" in dashboard
    assert "automatic tuning disabled" in dashboard
    assert "refresh_requested" in dashboard
