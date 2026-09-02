from __future__ import annotations

import ast
from pathlib import Path


def test_every_worker_failed_show_error_connection_has_receiver_method() -> None:
    ui_root = Path(__file__).resolve().parents[1] / "dvs_ai" / "ui"
    checked = 0
    for path in ui_root.glob("*_widget.py"):
        source = path.read_text(encoding="utf-8")
        if "failed.connect(self._show_error)" not in source:
            continue
        checked += 1
        tree = ast.parse(source, filename=str(path))
        classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        assert any(
            any(
                isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                and member.name == "_show_error"
                for member in class_node.body
            )
            for class_node in classes
        ), f"{path.name} connects self._show_error but does not define it"
    assert checked >= 10
