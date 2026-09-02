from pathlib import Path
ROOT = Path(__file__).resolve().parent
MW = (ROOT / 'dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
LS = (ROOT / 'dvs_ai/services/learning_service.py').read_text(encoding='utf-8')
TELE = (ROOT / 'dvs_ai/ui/retention_owner_telemetry.py').read_text(encoding='utf-8')
assert 'retention_policy="whole_container_replaced_per_finalization"' in MW
assert 'container_name="scan_result_side_effect_queue"' in MW
assert 'container_name="auto_paper_queue"' in MW
assert 'container_name="coin_analysis_graph"' not in MW
assert 'container_name="decision_candidates"' not in MW
assert 'operation="append"' in MW and 'operation="pop"' in MW
assert 'replacement_reason="finalization_payload_commit"' in MW
assert 'flatten_groups=True' in MW
assert 'account_payload_delta=False' in MW
assert 'callback(old_cache, new_cache, "db_snapshot_refresh")' in LS
assert 'callback(old_cache, None, "explicit_invalidate")' in LS
assert 'import gc' not in TELE
assert 'repr(' not in TELE
print('RC6.4.7F-r1 telemetry contract checks: PASS')
