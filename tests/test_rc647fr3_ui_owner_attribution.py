from pathlib import Path

def test_rc647fr3_contract():
    root = Path(__file__).resolve().parents[1]
    mw = (root / "dvs_ai/ui/main_window.py").read_text(encoding="utf-8")
    tr = (root / "dvs_ai/runtime/coin_analysis_token_tracker.py").read_text(encoding="utf-8")
    assert "MainWindow.current_analysis" in mw
    assert "MainWindow._truth_dashboard_pending_analysis" in mw
    assert "TruthDashboard._last_analysis" in mw
    assert "QTimer.singleShot.truth_dashboard_seed_closure" in mw
    assert "qobject_owner_snapshot" in tr
    assert "os.write(fd, encoded)" in tr
    assert "gc.get_objects" not in tr


def test_truth_pending_setter_assigns_without_self_recursion():
    import ast
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "dvs_ai/ui/main_window.py").read_text(encoding="utf-8"))
    fn = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_set_truth_pending_reference")
    recursive_calls = [node for node in ast.walk(fn) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_set_truth_pending_reference"]
    assignments = [node for node in ast.walk(fn) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Attribute) and target.attr == "_truth_dashboard_pending_analysis" for target in node.targets)]
    assert not recursive_calls
    assert assignments
