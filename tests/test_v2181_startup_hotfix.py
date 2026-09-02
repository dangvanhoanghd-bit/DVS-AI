from __future__ import annotations

import ast
import os
from pathlib import Path


def test_main_window_structure_not_truncated():
    source = Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
    module = ast.parse(source)
    main = next(
        node for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == 'MainWindow'
    )
    methods = {
        node.name for node in main.body
        if isinstance(node, ast.FunctionDef)
    }
    assert 'refresh_microstructure_tab' in methods
    assert '_panel' in methods
    assert '_build_paper_trade_tab' in methods
    assert 'start_scan' in methods
    assert not any(
        isinstance(node, ast.FunctionDef)
        and node.name == 'refresh_microstructure_tab'
        for node in module.body
    )


def test_version_matches_app_version():
    from dvs_ai import __version__
    from dvs_ai.version import APP_VERSION
    assert __version__ == APP_VERSION

def test_main_window_constructor_calls_existing_helpers():
    source = Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    main = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "MainWindow")
    methods = {node.name for node in main.body if isinstance(node, ast.FunctionDef)}
    init = next(node for node in main.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
    called_self_methods = {
        node.func.attr
        for node in ast.walk(init)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
        and node.func.attr.startswith("_")
    }
    missing = sorted(name for name in called_self_methods if name not in methods)
    assert missing == []
