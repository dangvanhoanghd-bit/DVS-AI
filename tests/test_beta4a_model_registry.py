from __future__ import annotations

import pytest

from dvs_ai.beta4a.contracts import FeatureSchemaIdentity, ModelSlotManifest, ModelSlotState
from dvs_ai.beta4a.errors import Beta4AGateError
from dvs_ai.beta4a.model_registry import ModelRegistry


def slot(state=ModelSlotState.EMPTY):
    return ModelSlotManifest(
        model_slot_id='slot-1', state=state,
        policy_identity=('scope','scope-hash','engine'),
        extraction_identity=('extractor','v1'),
        feature_schema_identity=FeatureSchemaIdentity('fs-v1','features-hash'),
        source_bundle_sha256='bundle-1', source_split_sha256='split-1')


def test_registry_lifecycle_and_immutable_history(tmp_path):
    registry = ModelRegistry(state_db_path=tmp_path/'registry.sqlite3')
    registry.create_empty_slot(slot())
    assert registry.transition(model_slot_id='slot-1', target_state=ModelSlotState.RESERVED, reason='reserve').state is ModelSlotState.RESERVED
    assert registry.transition(model_slot_id='slot-1', target_state=ModelSlotState.TRAINING, reason='start').state is ModelSlotState.TRAINING
    assert registry.transition(model_slot_id='slot-1', target_state=ModelSlotState.TRAINED_UNVALIDATED, reason='trained').state is ModelSlotState.TRAINED_UNVALIDATED
    audit = registry.audit_snapshot('slot-1')
    assert len(audit['manifests']) == 4
    assert [r['target_state'] for r in audit['transitions']] == ['EMPTY','RESERVED','TRAINING','TRAINED_UNVALIDATED']


def test_validated_requires_lifecycle_gate(tmp_path):
    registry = ModelRegistry(state_db_path=tmp_path/'registry.sqlite3')
    registry.create_empty_slot(slot())
    with pytest.raises(Beta4AGateError) as exc:
        registry.transition(model_slot_id='slot-1', target_state=ModelSlotState.VALIDATED, reason='bypass')
    assert exc.value.code == 'MODEL_SLOT_VALIDATION_GATE_REQUIRED'


def test_illegal_transition_and_duplicate_creation_blocked(tmp_path):
    registry = ModelRegistry(state_db_path=tmp_path/'registry.sqlite3')
    registry.create_empty_slot(slot())
    with pytest.raises(Beta4AGateError) as exc:
        registry.create_empty_slot(slot())
    assert exc.value.code == 'MODEL_SLOT_ALREADY_EXISTS'
    with pytest.raises(Beta4AGateError) as exc:
        registry.transition(model_slot_id='slot-1', target_state=ModelSlotState.TRAINING, reason='skip')
    assert exc.value.code == 'MODEL_SLOT_TRANSITION_NOT_ALLOWED'


def test_rejected_is_terminal(tmp_path):
    registry = ModelRegistry(state_db_path=tmp_path/'registry.sqlite3')
    registry.create_empty_slot(slot())
    registry.transition(model_slot_id='slot-1', target_state=ModelSlotState.RESERVED, reason='reserve')
    registry.transition(model_slot_id='slot-1', target_state=ModelSlotState.REJECTED, reason='reject')
    with pytest.raises(Beta4AGateError):
        registry.transition(model_slot_id='slot-1', target_state=ModelSlotState.TRAINING, reason='retry')


def test_current_index_is_derived_and_rebuildable(tmp_path):
    registry = ModelRegistry(state_db_path=tmp_path/'registry.sqlite3')
    registry.create_empty_slot(slot())
    registry.transition(model_slot_id='slot-1', target_state=ModelSlotState.RESERVED, reason='reserve')
    registry.rebuild_current_index()
    assert registry.get_current('slot-1').state is ModelSlotState.RESERVED
