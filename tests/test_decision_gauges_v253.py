from pathlib import Path
import ast


def _source():
    path = Path(__file__).parents[1] / "dvs_ai" / "ui" / "main_window.py"
    return path.read_text(encoding="utf-8")


def test_gauge_widget_api_is_set_value():
    source = _source()
    tree = ast.parse(source)
    gauge = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "GaugeWidget"
    )
    methods = {
        node.name for node in gauge.body
        if isinstance(node, ast.FunctionDef)
    }
    assert "set_value" in methods


def test_pro_panels_do_not_call_missing_set_data_on_gauges():
    source = _source()
    for name in (
        "decision_gauge",
        "entry_gauge",
        "smart_gauge",
        "wyckoff_gauge",
        "risk_gauge",
    ):
        assert f"self.{name}.set_data(" not in source
        assert f"self.{name}.set_value(" in source
