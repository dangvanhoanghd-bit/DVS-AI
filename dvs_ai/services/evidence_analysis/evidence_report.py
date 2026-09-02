from __future__ import annotations
import hashlib, json
from .observable_models import FrozenObservableContext
from .report_models import EvidenceReport, IntegrityReport, StageState

class EvidenceReportEngine:
    @staticmethod
    def build(context: FrozenObservableContext, integrity: IntegrityReport) -> EvidenceReport:
        if integrity.state is not StageState.PASS:
            return EvidenceReport(StageState.SKIPPED,0,0,0,None,None,(),"integrity gate failed",(),"")
        rows=tuple(context.observations)
        selected=tuple(o for o in rows if o.selected)
        outcomes=tuple(float(o.outcome_r) for o in selected if o.outcome_r is not None)
        expectancy=sum(outcomes)/len(outcomes) if outcomes else None
        win_rate=sum(1 for x in outcomes if x>0)/len(outcomes) if outcomes else None
        blocks=[]
        if outcomes:
            block_size=max(1,len(outcomes)//4)
            for start in range(0,len(outcomes),block_size):
                block=outcomes[start:start+block_size]
                if block: blocks.append(sum(block)/len(block))
        
        artifact_hash=hashlib.sha256(json.dumps({
            "context_id": context.context_id,
            "context_artifact_hash": context.artifact_hash,
            "sample_count": len(rows),
            "selected_count": len(selected),
            "outcome_count": len(outcomes),
            "selected_outcomes": list(outcomes),
        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return EvidenceReport(StageState.PASS,len(rows),len(selected),len(outcomes),expectancy,win_rate,tuple(blocks),"",tuple(outcomes),artifact_hash)
