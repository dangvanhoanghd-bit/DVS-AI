from pathlib import Path
ROOT = Path(__file__).parents[1]

def read(rel):
    return (ROOT/rel).read_text(encoding="utf-8")

def test_scanner_keeps_pinned_outside_universe():
    source=read("dvs_ai/services/scanner.py")
    assert "pinned_clean = list(dict.fromkeys(pinned))" in source
    assert "if symbol in unique" not in source[source.index("def deep_scan_batch"):source.index("@staticmethod",source.index("def deep_scan_batch"))]

def test_manager_search_and_immediate_scan():
    source=read("dvs_ai/ui/main_window.py")
    assert "def filter_coins" in source
    assert "setHidden(not matched)" in source
    assert "self._launch_scan(tuple(added), clear=False)" in source
    assert "self._refresh_symbol_controls()" in source

def test_header_search():
    source=read("dvs_ai/ui/main_window.py")
    assert "self.header_symbol.setEditable(True)" in source
    assert "Qt.MatchFlag.MatchContains" in source
