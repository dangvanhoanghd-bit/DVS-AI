from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "dvs_ai" / "ui" / "main_window.py"


def _text():
    return SOURCE.read_text(encoding="utf-8")


def test_sidebar_is_constrained_to_compact_operator_width():
    text = _text()
    assert "self.sidebar.setMinimumWidth(145)" in text
    assert "self.sidebar.setMaximumWidth(175)" in text
    assert 'getattr(self.workspace_splitter, "setSizes")([160, 1440])' in text
    assert "self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)" in text


def test_dashboard_table_uses_phase_as_flexible_column():
    text = _text()
    dashboard = text[text.index("def _build_dashboard"):text.index("def _build_truth_dashboard_tab")]
    assert "header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)" in dashboard
    assert "header.setSectionResizeMode(11, QHeaderView.ResizeMode.Stretch)" in dashboard
    assert "0: 96" in dashboard
    assert "16: 84" in dashboard


def test_dashboard_keeps_all_operator_columns():
    text = _text()
    dashboard = text[text.index("def _build_dashboard"):text.index("def _build_truth_dashboard_tab")]
    for label in [
        '"Coin"', '"Confidence"', '"Giá"', '"24h%"', '"OI15m%"',
        '"OI1h%"', '"Funding%"', '"CMF15m"', '"RSI15m"', '"ADX15m"',
        '"Vol15m"', '"Pha"', '"L.Trend"', '"L.Entry"', '"S.Trend"',
        '"S.Entry"', '"Trạng thái"',
    ]:
        assert label in dashboard
