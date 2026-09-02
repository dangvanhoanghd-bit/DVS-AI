from __future__ import annotations

import ast
from pathlib import Path


def test_runtime_session_id_assigned_before_first_read() -> None:
    source_path = Path(__file__).resolve().parents[1] / "dvs_ai" / "ui" / "main_window.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    main_window = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MainWindow")
    init = next(node for node in main_window.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")

    assignment_lines: list[int] = []
    read_lines: list[int] = []
    for node in ast.walk(init):
        if not isinstance(node, ast.Attribute):
            continue
        if not isinstance(node.value, ast.Name) or node.value.id != "self":
            continue
        if node.attr != "_runtime_session_id":
            continue
        if isinstance(node.ctx, ast.Store):
            assignment_lines.append(node.lineno)
        elif isinstance(node.ctx, ast.Load):
            read_lines.append(node.lineno)

    assert len(assignment_lines) == 1
    assert read_lines
    assert assignment_lines[0] < min(read_lines)
