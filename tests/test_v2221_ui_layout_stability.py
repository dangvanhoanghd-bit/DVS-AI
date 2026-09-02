from pathlib import Path


def source():
    return Path(
        "dvs_ai/ui/main_window.py"
    ).read_text(encoding="utf-8")


def test_progress_handler_does_not_call_splitter_set_sizes():
    text = source()
    start = text.index("def on_progress")
    end = text.index("def on_error", start)
    body = text[start:end]
    assert "detail_splitter.setSizes" not in body


def test_scan_never_restores_or_resets_splitter_geometry():
    text = source()
    assert "def _restore_detail_splitter_once" not in text
    assert "QTimer.singleShot(0, self._restore_detail_splitter_once)" not in text
    assert "_scan_splitter_sizes" not in text


def test_result_rail_width_is_responsive_and_bounded():
    text = source()
    assert "right.setMinimumWidth(300)" in text
    assert "right.setMaximumWidth(460)" in text
    assert "right.setFixedWidth(520)" not in text
    assert "splitter.setStretchFactor(1, 3)" in text


def test_dynamic_text_cannot_expand_layout():
    text = source()
    assert "self.final_result_title.setWordWrap(False)" in text
    assert "QSizePolicy.Policy.Ignored" in text


def test_execution_safety_unchanged():
    import json
    raw = json.loads(
        Path("config.json").read_text(encoding="utf-8")
    )
    assert raw["execution_mode"] == "PAPER"
    assert raw["execution_live_enabled"] is False
