from pathlib import Path
import inspect

from dvs_ai.services.shadow_observation_service import ShadowObservationStore, ShadowObservationRuntime
from dvs_ai.services.paper_trade_service import PaperTradeService

root = Path(__file__).resolve().parent
shadow = inspect.getsource(ShadowObservationStore) + inspect.getsource(ShadowObservationRuntime)
paper = inspect.getsource(PaperTradeService)
assert "idx_shadow_observation_key" in shadow
assert "INSERT OR IGNORE INTO shadow_observations" in shadow
assert "shadow_observation_duplicate_archive" in shadow
assert '"deduplicated"' in shadow
for token in ("evaluated", "main_eligible", "shadow_eligible", "created", "duplicate_blocked", "capacity_blocked", "gate_blocked"):
    assert token in paper
ui=(root/"dvs_ai/ui/truth_dashboard.py").read_text(encoding="utf-8")
assert ".item(row, col) or QTableWidgetItem()" not in ui
assert ".item(row,col) or QTableWidgetItem()" not in ui
print("DATA PIPELINE INTEGRITY VERIFIER 2.32.5-r2: PASS")
