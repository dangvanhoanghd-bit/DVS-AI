from pathlib import Path
import ast


def _main_window_source():
    path = Path(__file__).parents[1] / "dvs_ai" / "ui" / "main_window.py"
    return path.read_text(encoding="utf-8")


def test_metric_card_uses_subtitle_attribute():
    source = _main_window_source()
    assert "self.sub.setText" not in source
    assert "self.subtitle.setText" in source


def test_learning_center_uses_existing_metric_card_api():
    source = _main_window_source()
    assert "self.learn_total.set_data(" in source
    assert "self.learn_wr.set_data(" in source
    assert "self.learn_avg_r.set_data(" in source
    assert "self.learn_pf.set_data(" in source
    assert "self.learn_long_short.set_data(" in source
