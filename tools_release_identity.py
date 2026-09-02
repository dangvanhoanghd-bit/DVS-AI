from __future__ import annotations
import argparse, hashlib, json, re, sys
from datetime import datetime, timezone
from pathlib import Path

CRITICAL_FILES = (
    'dvs_ai/app.py',
    'dvs_ai/ui/main_window.py',
    'dvs_ai/runtime/gui_event_loop_forensics.py',
    'dvs_ai/services/shadow_observation_service.py',
    'dvs_ai/ui/truth_dashboard.py',
    'dvs_ai/engines/decision_engine.py',
    'dvs_ai/version.py',
)

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def read_app_version(root: Path) -> str:
    text=(root/'dvs_ai/version.py').read_text(encoding='utf-8')
    m=re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', text, re.M)
    if not m: raise RuntimeError('APP_VERSION not found')
    return m.group(1)

def generate(root: Path) -> dict:
    build_id=(root/'BUILD_ID.txt').read_text(encoding='utf-8').strip()
    app_version=read_app_version(root)
    if build_id != app_version:
        raise RuntimeError(f'build_id/app_version mismatch: {build_id!r} != {app_version!r}')
    missing=[rel for rel in CRITICAL_FILES if not (root/rel).is_file()]
    if missing: raise RuntimeError(f'missing critical files: {missing}')
    files={rel:sha256(root/rel) for rel in CRITICAL_FILES}
    manifest={
        'schema_version':'2.0',
        'build_id':build_id,
        'app_version':app_version,
        'generated_at_utc':datetime.now(timezone.utc).isoformat(),
        'files':files,
        'decision_engine_sha256':files['dvs_ai/engines/decision_engine.py'],
        'notes':[
            'Sprint A2 V2.3.1: Paper Trade table commit decongestion',
            'Paper Trade header uses stable Interactive widths; ResizeToContents removed',
            'Paper table updates reuse existing items and skip unchanged cells',
            'Paper commit uses an adaptive 10 ms turn budget and yields between rows',
            'Manifest regenerated from source bytes and verified fail-closed before packaging',
        ],
    }
    return manifest

def verify(root: Path, manifest_path: Path|None=None) -> list[str]:
    manifest_path=manifest_path or root/'code_identity.json'
    errors=[]
    try: manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    except Exception as exc: return [f'manifest unreadable: {exc}']
    build_id=(root/'BUILD_ID.txt').read_text(encoding='utf-8').strip()
    try: app_version=read_app_version(root)
    except Exception as exc: return [str(exc)]
    if manifest.get('build_id') != build_id: errors.append('stale build_id')
    if manifest.get('app_version') != app_version: errors.append('wrong app_version')
    if build_id != app_version: errors.append('BUILD_ID.txt and APP_VERSION disagree')
    files=manifest.get('files') or {}
    for rel in CRITICAL_FILES:
        if rel not in files:
            errors.append(f'missing manifest entry: {rel}')
            continue
        path=root/rel
        if not path.is_file(): errors.append(f'missing source file: {rel}'); continue
        actual=sha256(path)
        if files[rel] != actual: errors.append(f'hash mismatch: {rel}')
    extra_critical=[rel for rel in CRITICAL_FILES if (root/rel).is_file() and rel not in files]
    if extra_critical: errors.append(f'untracked critical files: {extra_critical}')
    if manifest.get('decision_engine_sha256') != files.get('dvs_ai/engines/decision_engine.py'):
        errors.append('decision_engine_sha256 mismatch')
    return errors

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('command', choices=['generate','verify'])
    ap.add_argument('--root', default='.')
    args=ap.parse_args(); root=Path(args.root).resolve()
    if args.command=='generate':
        manifest=generate(root)
        (root/'code_identity.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    errors=verify(root)
    if errors:
        print(json.dumps({'status':'FAIL','errors':errors},indent=2)); return 2
    print(json.dumps({'status':'PASS','build_id':(root/'BUILD_ID.txt').read_text().strip()},indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
