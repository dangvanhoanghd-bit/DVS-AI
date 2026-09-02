from pathlib import Path
base=Path('dvs_ai/services/evidence_analysis')
required=['confidence_engine.py','gap_planner.py','recommendation_mapper.py']
for name in required:
    assert (base/name).exists(), name
for name in required:
    text=(base/name).read_text(encoding='utf-8').lower()
    assert 'sqlite3' not in text
    assert 'observablerepository' not in text
    assert 'connect(' not in text
mapper=(base/'recommendation_mapper.py').read_text(encoding='utf-8').lower()
for forbidden in ('random','bootstrap','threshold','frozenobservablecontext'):
    assert forbidden not in mapper, forbidden
assert 'observable_but_underpowered' in (base/'confidence_engine.py').read_text(encoding='utf-8').lower()
print('CONFIDENCE & GAP FRAMEWORK VERIFIER 2.32.5: PASS')
