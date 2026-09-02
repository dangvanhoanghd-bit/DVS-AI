from pathlib import Path


def test_scheduler_source_has_dedup_and_budget():
    source = Path("dvs_ai/ui/frame_paint_scheduler.py").read_text(encoding="utf-8")
    assert "if current is not None" in source
    assert "self._metrics.deduplicated += 1" in source
    assert "elapsed_ms >= self.frame_budget_ms" in source
    assert "self._timer.start(self.frame_interval_ms)" in source


def test_market_chart_uses_scheduler():
    source = Path("dvs_ai/ui/market_chart.py").read_text(encoding="utf-8")
    assert "def request_repaint" in source
    assert source.count("self.request_repaint(priority=10)") >= 3


def test_main_window_routes_heavy_viewports():
    source = Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")
    assert "self.paint_scheduler.request(self.table.viewport(), priority=20)" in source
    assert "self.paint_scheduler.request(self.error_table.viewport(), priority=15)" in source
    assert "def paint_scheduler_diagnostics" in source
