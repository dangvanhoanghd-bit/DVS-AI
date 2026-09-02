from types import SimpleNamespace
from dvs_ai.engines.explainable_narrative_engine import ExplainableNarrativeEngine


def _analysis():
    tf=SimpleNamespace(cmf=-0.2,rsi=28,adx=32)
    return SimpleNamespace(
        symbol="HOME/USDT:USDT", timeframes={"15m":tf}, direction="SHORT", action="ĐỨNG NGOÀI",
        entry_status=SimpleNamespace(value="WAIT"),
        regime=SimpleNamespace(regime="MARKDOWN",direction="SHORT",strength=75),
        alignment=SimpleNamespace(label="ĐỒNG PHA SHORT",long_score=5,short_score=80),
        risk=SimpleNamespace(risk_score=55),
        structure=SimpleNamespace(wyckoff_test="NONE",wyckoff_test_score=0),
        smart_entry=SimpleNamespace(state="NO EDGE",absorption_score=17,weak_hand_score=48,panic_flush_score=2,long_opportunity_index=14,short_opportunity_index=21),
        composite_exhaustion=SimpleNamespace(state="SELLING",selling_pressure=80,bottom_formation_probability=20,distribution_progress=85,exhaustion_score=25,absorption_score=17,passive_bid_score=5,bottom_state="BOTTOM_NOT_CONFIRMED"),
        microstructure=SimpleNamespace(ofi_score=-20,book_imbalance=-0.1),
        footprint_gate="BLOCKED",market_bias_gate="NOT_APPLIED",direction_confirmation_gate="NOT_APPLIED",
    )


def test_narrative_is_observe_only_and_explains_wait():
    out=ExplainableNarrativeEngine().evaluate(_analysis())
    assert out.observe_only is True
    assert out.decision_blockers
    assert any("Structure" in x for x in out.decision_blockers)
    assert any("Smart Entry" in x for x in out.decision_path)


def test_narrative_never_mutates_analysis():
    a=_analysis(); before=(a.action,a.direction,a.risk.risk_score)
    ExplainableNarrativeEngine().evaluate(a)
    assert before==(a.action,a.direction,a.risk.risk_score)


def test_source_has_no_execution_dependencies():
    import ast
    from pathlib import Path
    tree=ast.parse(Path("dvs_ai/engines/explainable_narrative_engine.py").read_text(encoding="utf-8"))
    imports=[]; calls=[]; assigned=[]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import): imports.extend(a.name.lower() for a in node.names)
        elif isinstance(node, ast.ImportFrom): imports.append((node.module or "").lower())
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name): calls.append(node.func.id.lower())
            elif isinstance(node.func, ast.Attribute): calls.append(node.func.attr.lower())
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets=node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute): assigned.append(target.attr.lower())
                elif isinstance(target, ast.Name): assigned.append(target.id.lower())
    joined=" ".join(imports+calls+assigned)
    for forbidden in ("execution", "tradeintent", "promotion", "send_order", "confidence_score"):
        assert forbidden not in joined
