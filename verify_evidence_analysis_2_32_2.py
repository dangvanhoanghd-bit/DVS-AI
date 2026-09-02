from pathlib import Path
import inspect
from dvs_ai.services.evidence_analysis import EvidenceAnalysisPipeline, RecommendationEngine
ROOT=Path(__file__).parent
required=[
'dvs_ai/services/evidence_analysis/integrity_report.py',
'dvs_ai/services/evidence_analysis/evidence_report.py',
'dvs_ai/services/evidence_analysis/confidence_report.py',
'dvs_ai/services/evidence_analysis/actionable_gap_report.py',
'dvs_ai/services/evidence_analysis/recommendation_engine.py',
'dvs_ai/services/evidence_analysis/analysis_pipeline.py',
]
for name in required:
    assert (ROOT/name).exists(), name
for name in required:
    text=(ROOT/name).read_text(encoding='utf-8').lower()
    assert 'sqlite3' not in text, name
    assert 'observablerepository' not in text, name
    assert '.observable_repository' not in text, name
source=inspect.getsource(RecommendationEngine)
assert 'recommendation_gate' in source
assert 'integrity.state' in source
print('EVIDENCE ANALYSIS VERIFIER 2.32.2: PASS')
