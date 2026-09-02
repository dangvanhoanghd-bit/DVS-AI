from __future__ import annotations
from ..decision import ScientificDecision
from ..explainability import ScientificExplainabilityEngine
from ..ledger import ScientificLedger
from .models import ScientificDecisionReport

class ScientificDecisionReportBuilder:
    def __init__(self, ledger: ScientificLedger) -> None:
        self._ledger = ledger
        self._explainability = ScientificExplainabilityEngine(ledger)
    def build(self, decision: ScientificDecision) -> ScientificDecisionReport:
        explanation = self._explainability.explain_run(decision.pipeline_run_id)
        codes = tuple(dict.fromkeys((*explanation.primary_reason_codes, *decision.reason_codes)))
        return ScientificDecisionReport(decision, explanation.integrity_verified,
                                        len(explanation.steps), explanation.summary, codes)
