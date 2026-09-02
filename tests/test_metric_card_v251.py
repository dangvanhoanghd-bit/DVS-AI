from pathlib import Path
import ast

def test_metric_card_has_set_value():
    path = Path(__file__).parents[1] / 'dvs_ai' / 'ui' / 'main_window.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MetricCard')
    methods = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    assert 'set_value' in methods
