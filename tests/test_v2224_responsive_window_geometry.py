from pathlib import Path


def main_source():
    return Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")


def app_source():
    return Path("dvs_ai/app.py").read_text(encoding="utf-8")


def test_no_hard_main_window_startup_resize():
    source = main_source()
    title = source.index("self.setWindowTitle(WINDOW_TITLE)")
    root = source.index("root = QWidget()", title)
    startup = source[title:root]
    assert "self.resize(" not in startup
    assert "self.setGeometry(" not in startup
    assert "self.adjustSize(" not in startup


def test_platform_manages_maximized_geometry():
    source = app_source()
    assert "window.showMaximized()" in source
    assert "window.show()" not in source


def test_toolbar_is_two_row_responsive():
    source = main_source()
    assert "header_container = QVBoxLayout()" in source
    assert "header_identity = QHBoxLayout()" in source
    assert "header_actions = QHBoxLayout()" in source


def test_result_rail_is_responsive():
    source = main_source()
    assert "right.setMinimumWidth(300)" in source
    assert "right.setMaximumWidth(460)" in source
    assert "right.setFixedWidth(" not in source


def test_scan_does_not_change_main_geometry():
    source = main_source()
    scan = source[source.index("def start_scan"):]
    for forbidden in ("self.resize(", "self.setGeometry(", "self.adjustSize(", "self.restoreGeometry("):
        assert forbidden not in scan


def test_geometry_diagnostics_exist():
    source = main_source()
    manager = Path("dvs_ai/ui/ui_geometry_manager.py").read_text(encoding="utf-8")
    assert "def ui_geometry_diagnostics" in source
    assert "last_diagnostic" in source
    assert "def log_diagnostic" in manager


def test_execution_safety_unchanged():
    import json
    raw = json.loads(Path("config.json").read_text(encoding="utf-8"))
    assert raw["execution_mode"] == "PAPER"
    assert raw["execution_live_enabled"] is False
