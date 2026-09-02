from pathlib import Path

REQUIRED = [
    Path('dvs_ai/engines/evidence_fusion_engine.py'),
    Path('tests/test_v2266_evidence_fusion_v3.py'),
    Path('EVIDENCE_FUSION_V3_TRUTH_MANIFEST.json'),
]
for path in REQUIRED:
    assert path.exists(), path
text = REQUIRED[0].read_text(encoding='utf-8')
for token in ('reliability', 'source_multipliers', 'contradiction_strength', 'family_details'):
    assert token in text, token
config = Path('config.json').read_text(encoding='utf-8')
assert 'evidence_fusion_family_weights' in config
assert 'evidence_fusion_source_multipliers' in config
print('Evidence Fusion V3 verifier: PASS')
