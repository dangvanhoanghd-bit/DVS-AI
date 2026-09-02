from pathlib import Path
import json
from dvs_ai.services.evidence_analysis.observable_thresholds import ThresholdProfileLoader

ROOT=Path(__file__).resolve().parent
profile=ThresholdProfileLoader(ROOT/'config/evidence_analysis/observable_thresholds.json',ROOT/'config/evidence_analysis/observable_thresholds.manifest.json').load()
assert profile.protocol_version == '1.0'
assert profile.get('regime_observable') == 30
assert profile.get('candidate_eligibility') == 40
assert profile.get('paired_observable') == 30
assert profile.get('powered_samples') == 60
assert profile.get('paired_powered') == 60
for name in ('protocol_gate.py',):
    text=(ROOT/'dvs_ai/services/evidence_analysis'/name).read_text(encoding='utf-8').lower()
    assert 'sqlite3' not in text
    assert 'observable_repository' not in text
assert 'execution' not in (ROOT/'dvs_ai/services/evidence_analysis/observable_universe.py').read_text(encoding='utf-8').lower()
print('Observable Universe verifier: PASS')
