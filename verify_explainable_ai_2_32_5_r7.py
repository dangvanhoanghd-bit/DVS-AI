from pathlib import Path
import ast

root=Path(__file__).resolve().parent
engine=root/'dvs_ai/engines/explainable_narrative_engine.py'
ui=root/'dvs_ai/ui/main_window.py'
scanner=root/'dvs_ai/services/scanner.py'
assert engine.exists()
source=engine.read_text(encoding='utf-8')
tree=ast.parse(source)
imports=[]; calls=[]
for node in ast.walk(tree):
    if isinstance(node, ast.Import): imports.extend(a.name.lower() for a in node.names)
    elif isinstance(node, ast.ImportFrom): imports.append((node.module or '').lower())
    elif isinstance(node, ast.Call):
        calls.append((node.func.id if isinstance(node.func,ast.Name) else getattr(node.func,'attr','')).lower())
joined=' '.join(imports+calls)
for term in ('execution','promotion','send_order','tradeintent'):
    assert term not in joined, term
ui_text=ui.read_text(encoding='utf-8')
for term in ('DECISION PATH · EXPLAINABLE AI','DECISION BLOCKERS','AI MARKET STORY · OBSERVE ONLY','SMART MONEY STORY','NEXT CONFIRMATION'):
    assert term in ui_text, term
scan=scanner.read_text(encoding='utf-8')
assert '_attach_explainable_narrative' in scan
print('Explainable AI verifier: PASS')
