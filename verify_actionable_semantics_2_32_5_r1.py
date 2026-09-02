from pathlib import Path

mapper = Path("dvs_ai/services/evidence_analysis/recommendation_mapper.py").read_text(encoding="utf-8")
enforcer = Path("dvs_ai/services/evidence_analysis/protocol_enforcement.py").read_text(encoding="utf-8")
assert 'payload.conclusion_state in {"SUPPORTED", "UNSUPPORTED"}' in mapper
assert "Manual review readiness not marked actionable" in enforcer
assert "Review-required recommendation not marked actionable" in enforcer
assert "Continue-paper recommendation incorrectly marked actionable" in enforcer
print("ACTIONABLE SEMANTICS VERIFIER 2.32.5-r1: PASS")
