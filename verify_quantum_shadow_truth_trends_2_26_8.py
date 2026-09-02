from pathlib import Path
import inspect
from dvs_ai.services.quantum_optimizer import QuantumOptimizer
from dvs_ai.services.truth_trend_store import TruthTrendStore
s=inspect.getsource(QuantumOptimizer)
assert "main_optimization_blocked" in s and "rejected_main_keys" in s
assert "weight_order_flow" in s and "evidence_fusion_family_weights" in s
assert "Direct config mutation is disabled" in s
ui=Path('dvs_ai/ui/truth_dashboard.py').read_text()
assert 'TruthTrendChart' in ui and 'TruthTrendStore' in ui
assert 'send_order' not in ui and 'PositionSizer' not in ui
print('QUANTUM SHADOW/TRUTH TRENDS 2.26.8: PASS')
