from __future__ import annotations
import json, shutil, tempfile
from pathlib import Path
from tools_release_identity import verify

ROOT=Path(__file__).resolve().parent

def clone():
    td=Path(tempfile.mkdtemp(prefix='dvs_v23_identity_'))/'root'
    shutil.copytree(ROOT,td,ignore=shutil.ignore_patterns('__pycache__','artifacts','*.pyc'))
    return td

def expect_fail(name, mutator):
    root=clone()
    try:
        mutator(root)
        errors=verify(root)
        assert errors, f'{name}: verifier unexpectedly passed'
        return {'name':name,'status':'PASS','observed_errors':errors}
    finally:
        shutil.rmtree(root.parent,ignore_errors=True)

def main():
    tests=[]
    tests.append(expect_fail('tamper_one_source_byte', lambda r:(r/'dvs_ai/app.py').write_bytes((r/'dvs_ai/app.py').read_bytes()+b'\n# tamper\n')))
    def remove_entry(r):
        p=r/'code_identity.json'; d=json.loads(p.read_text()); d['files'].pop('dvs_ai/runtime/gui_event_loop_forensics.py'); p.write_text(json.dumps(d))
    tests.append(expect_fail('remove_manifest_entry',remove_entry))
    tests.append(expect_fail('stale_build_id', lambda r:(r/'BUILD_ID.txt').write_text('STALE-BUILD\n')))
    def wrong_version(r):
        p=r/'code_identity.json'; d=json.loads(p.read_text()); d['app_version']='WRONG'; p.write_text(json.dumps(d))
    tests.append(expect_fail('wrong_app_version',wrong_version))
    def untracked(r):
        p=r/'code_identity.json'; d=json.loads(p.read_text()); d['files'].pop('dvs_ai/ui/truth_dashboard.py'); p.write_text(json.dumps(d))
    tests.append(expect_fail('untracked_critical_file',untracked))
    report={'status':'PASS','tests':tests}
    (ROOT/'RELEASE_IDENTITY_NEGATIVE_TEST_REPORT.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
if __name__=='__main__': main()
