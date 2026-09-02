from pathlib import Path
from types import SimpleNamespace

from dvs_ai.services.shadow_observation_service import ShadowObservationRuntime, ShadowObservationStore


def analysis():
    return SimpleNamespace(
        symbol='BTC/USDT:USDT', direction='LONG', generated_at='2026-07-16T10:00:00+00:00',
        confidence_score=72.0, smart_entry=SimpleNamespace(entry_score=65.0),
        regime=SimpleNamespace(regime='BULL'), probability_calibration_state='VALIDATED',
        calibration_drift_state='STABLE', evidence_reliability_summary=('ENTRY:VALIDATED:70.0%:20.0',),
    )


def test_runtime_records_binds_and_closes_by_trade_id(tmp_path):
    store=ShadowObservationStore(str(tmp_path/'paper.db'))
    runtime=ShadowObservationRuntime(store, data_dir=str(tmp_path), promotion_dir=str(tmp_path/'promotions'))
    oid=runtime.record_pair(analysis(), direction='LONG', main_ok=False, shadow_ok=True,
                            main_reasons=('MAIN_THRESHOLD',), shadow_reasons=())
    assert oid
    assert runtime.bind_trade(oid, 77)
    assert not runtime.bind_trade(oid, 88)
    assert runtime.close_trade(77, 1.25, result='TP2', closed_at='2026-07-16T11:00:00+00:00')
    assert not runtime.close_trade(77, -1.0, result='STOP')
    rows=store.rows('CURRENT_SHADOW_BASELINE')
    assert rows[0]['paper_trade_id']==77
    assert rows[0]['outcome_r']==1.25
    assert rows[0]['outcome_result']=='TP2'
    assert runtime.diagnostics()['closed']==1


def test_runtime_fail_safe_does_not_raise_on_bad_analysis(tmp_path):
    runtime=ShadowObservationRuntime(ShadowObservationStore(str(tmp_path/'paper.db')), data_dir=str(tmp_path))
    oid=runtime.record_pair(SimpleNamespace(), direction='LONG', main_ok=False, shadow_ok=False)
    assert oid is not None
    assert runtime.diagnostics()['errors']==0


def test_runtime_module_has_no_execution_dependency():
    source=Path('dvs_ai/services/shadow_observation_service.py').read_text(encoding='utf-8')
    assert 'send_order' not in source
    assert 'TradeIntent' not in source
    assert 'PositionSizer' not in source


def test_app_wires_shared_observation_runtime():
    source=Path('dvs_ai/app.py').read_text(encoding='utf-8')
    assert 'ShadowObservationRuntime' in source
    assert 'observation_runtime=shadow_observation_runtime' in source
    assert 'shadow_observation_runtime=shadow_observation_runtime' in source
