from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN_WINDOW = ROOT / "dvs_ai" / "ui" / "main_window.py"
VERSION = ROOT / "dvs_ai" / "version.py"


def test_rc7_version_marker():
    assert 'APP_VERSION = "4.3.0E-3-QBP-4-RC7"' in VERSION.read_text(encoding="utf-8")


def test_finalization_restores_confidence_sort_unconditionally():
    source = MAIN_WINDOW.read_text(encoding="utf-8")
    method = source.split("    def _commit_finalization_payload", 1)[1].split("\n    def ", 1)[0]
    assert "self.table.setSortingEnabled(True)" in method
    assert "self.table.sortItems(1, Qt.SortOrder.DescendingOrder)" in method
    sort_block = method.split("# RC7 invariant:", 1)[1].split('timing_ms["sort_ms"]', 1)[0]
    assert "if sorting_was_enabled" not in sort_block


def test_launch_failure_restores_sort():
    source = MAIN_WINDOW.read_text(encoding="utf-8")
    method = source.split("    def _launch_scan", 1)[1].split("\n    def ", 1)[0]
    failure = method.split('logger.error("Persistent scan runtime thread is not running")', 1)[1].split("return", 1)[0]
    assert "self.table.setSortingEnabled(True)" in failure
    assert "self.table.sortItems(1, Qt.SortOrder.DescendingOrder)" in failure
    assert "self._rebuild_row_index()" in failure
