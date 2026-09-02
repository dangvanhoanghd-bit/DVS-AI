from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "dvs_ai" / "ui" / "main_window.py").read_text(encoding="utf-8")
VERSION = (ROOT / "dvs_ai" / "version.py").read_text(encoding="utf-8")
LAUNCHER = (ROOT / "START_DVS_AI.bat").read_text(encoding="utf-8")

def test_qlabel_does_not_call_sethtml():
    assert "smart_trigger_text.setHtml" not in SOURCE
    assert "smart_trigger_text.setText" in SOURCE

def test_projection_failures_are_isolated():
    assert "UI_SELECTION_PROJECTION_FAILED:%s" in SOURCE
    assert "SMART_ENTRY" in SOURCE
    assert "DECISION_CORE" in SOURCE
    assert "LIQUIDITY_WYCKOFF" in SOURCE

def test_liquidity_projection_exists():
    assert "def _render_structure_for_analysis" in SOURCE
    assert "self._render_structure_for_analysis" in SOURCE

def test_version_matches_app_version():
    from dvs_ai import __version__
    from dvs_ai.version import APP_VERSION
    assert __version__ == APP_VERSION

