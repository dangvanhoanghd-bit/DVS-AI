from pathlib import Path


def _source():
    return (
        Path(__file__).parents[1]
        / "dvs_ai" / "ui" / "main_window.py"
    ).read_text(encoding="utf-8")


def test_gauges_have_fixed_heights():
    source = _source()
    assert "self.setFixedHeight(92 if compact else 150)" in source
    assert "self.engine_gauge_box.setFixedHeight(98)" in source


def test_chart_and_tf_table_are_protected():
    source = _source()
    assert "self.market_chart.setFixedHeight(350)" in source
    assert "self.tf_table.setFixedHeight(130)" in source
    assert "self.tf_table.verticalHeader().setDefaultSectionSize(21)" in source


def test_splitter_geometry_is_never_mutated_by_scan():
    source = _source()
    assert "self._scan_splitter_sizes" not in source
    assert "self._restore_detail_splitter_once" not in source
    start = source.index("def on_progress")
    end = source.index("def on_error", start)
    assert "detail_splitter.setSizes" not in source[start:end]


def test_multiframe_cmf_rsi_are_colored_and_selected():
    source = _source()
    assert 'if c == 1:' in source
    assert 'elif c == 2:' in source
    assert 'if tf == selected_tf:' in source
