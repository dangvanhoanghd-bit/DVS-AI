from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parent
engine = ROOT / "dvs_ai/engines/composite_exhaustion_engine.py"
ui = ROOT / "dvs_ai/ui/main_window.py"
models = ROOT / "dvs_ai/domain/models.py"
scanner = ROOT / "dvs_ai/services/scanner.py"
for path in (engine, ui, models, scanner):
    assert path.exists(), path
ast.parse(engine.read_text(encoding="utf-8"))
source = engine.read_text(encoding="utf-8").lower()
for forbidden in ("order_router", "send_order", "trade_intent_builder", "apply_shadow"):
    assert forbidden not in source, forbidden
ui_source = ui.read_text(encoding="utf-8")
for token in ("Composite Exhaustion", "Bottom %", "Bottom State", "OBSERVE ONLY"):
    assert token.lower() in ui_source.lower(), token
print("Composite Exhaustion verifier: PASS")
