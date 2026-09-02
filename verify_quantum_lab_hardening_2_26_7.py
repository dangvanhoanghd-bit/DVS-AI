from pathlib import Path
import inspect
from dvs_ai.services.quantum_optimizer import QuantumOptimizer

source = inspect.getsource(QuantumOptimizer)
assert 'DVS_QUANTUM_TRAINING_V1' in source
assert 'INSUFFICIENT_QUALITY_DATA' in source
assert 'create_shadow_candidate' in source
assert 'Direct config mutation is disabled' in source
assert 'raw["main_' not in source and "raw['main_" not in source
paper = Path('dvs_ai/services/paper_trade_service.py').read_text(encoding='utf-8')
assert 'calibration_state' in paper
assert 'drift_state' in paper
assert 'order_flow_quality' in paper
print('QUANTUM LAB HARDENING 2.26.7: PASS')
