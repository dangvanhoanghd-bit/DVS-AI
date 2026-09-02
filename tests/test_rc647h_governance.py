from pathlib import Path
import json, threading
from dvs_ai.governance.release_identity import find_identity_assignments
from dvs_ai.governance.readiness import evaluate_readiness
from dvs_ai.governance.verification_matrix import build_matrix
from dvs_ai.diagnostics.jsonl_validator import validate_jsonl
from dvs_ai.monitoring.thread_identity import capture_thread_identity

ROOT=Path(__file__).resolve().parents[1]
def test_single_source_identity():
 a=find_identity_assignments(ROOT); assert len(a["BUILD_ID"])==1, a; assert len(a["APP_VERSION"])==1, a
def test_no_unverifiable_must():
 r=evaluate_readiness(); assert r["draft_ready"], r; assert not r["unverifiable_must"]
def test_matrix_is_method_not_result():
 m=build_matrix(); assert m["document_role"]=="VERIFICATION_METHOD_ONLY_NOT_AUDIT_RESULT"; assert all("audit_result" not in v for v in m["requirements"].values())
def test_thread_identity_explicit():
 tid=threading.get_ident(); d=capture_thread_identity(tid); assert d["gui_thread_id"]==tid and d["measurement_thread_id"]==tid and d["is_gui_thread"] is True
def test_jsonl_classification(tmp_path):
 p=tmp_path/"x.jsonl"; p.write_bytes(b'{"a":1}\n{"broken":')
 r=validate_jsonl(p,shutdown_marked=True); assert r.valid_records==1 and r.shutdown_truncation==1 and r.writer_errors==0
