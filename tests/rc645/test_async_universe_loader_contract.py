from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "dvs_ai" / "ui" / "main_window.py"


def _tree():
    return ast.parse(MAIN.read_text(encoding="utf-8"))


def _method(name: str):
    for node in ast.walk(_tree()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"missing method: {name}")


def test_gui_load_method_does_not_call_refresh_universe_directly():
    node = _method("load_market_universe")
    calls = [
        n for n in ast.walk(node)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "refresh_universe"
    ]
    assert calls == []


def test_worker_owns_refresh_universe_call():
    node = _method("load")
    assert any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "refresh_universe"
        for n in ast.walk(node)
    )


def test_start_scan_returns_after_async_universe_request():
    text = MAIN.read_text(encoding="utf-8")
    expected = "self.load_market_universe(\n                    show_message=False,\n                    continue_scan=True,\n                )\n                return"
    assert expected in text


def test_identity_cleanup_and_terminal_paths_present():
    text = MAIN.read_text(encoding="utf-8")
    for token in (
        "_active_universe_load_id",
        "_universe_load_registry",
        "universe_loader_finalized",
        '"COMPLETED"',
        '"FAILED"',
        '"CANCELLED"',
        '"SUPERSEDED"',
        "universe_loader_late_result_discarded",
        "universe_loader_single_flight_rejected",
    ):
        assert token in text
