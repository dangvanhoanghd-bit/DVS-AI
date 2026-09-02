from __future__ import annotations
import hashlib, json, os, shutil
from datetime import datetime, timezone
from pathlib import Path
from .observable_thresholds import ALLOWED_KEYS, PROTOCOL_VERSION, ThresholdProfileLoader

CONFIRMATION_PHRASE = "CONFIRM EVIDENCE PROTOCOL THRESHOLD CHANGE"
class ThresholdGovernanceError(RuntimeError): pass

class ObservableThresholdGovernanceService:
    def __init__(self, profile_path, manifest_path, audit_path, backup_dir):
        self.profile_path=Path(profile_path); self.manifest_path=Path(manifest_path); self.audit_path=Path(audit_path); self.backup_dir=Path(backup_dir)
    def propose_and_apply(self, changes: dict[str,int], *, confirmation: str, actor: str, reason: str)->dict:
        if confirmation != CONFIRMATION_PHRASE: raise ThresholdGovernanceError("exact confirmation phrase required")
        if not changes or not set(changes).issubset(ALLOWED_KEYS): raise ThresholdGovernanceError("change contains non-allowlisted key")
        before=ThresholdProfileLoader(self.profile_path,self.manifest_path).load(); current=dict(before.thresholds)
        for k,v in changes.items():
            if isinstance(v,bool) or not isinstance(v,int) or not 1 <= v <= 100000: raise ThresholdGovernanceError(f"invalid threshold {k}")
            current[k]=v
        if current["powered_samples"] < current["regime_observable"] or current["paired_powered"] < current["paired_observable"]: raise ThresholdGovernanceError("powered threshold below observable threshold")
        stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"); self.backup_dir.mkdir(parents=True,exist_ok=True); self.audit_path.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(self.profile_path,self.backup_dir/f"observable_thresholds_{stamp}.json"); shutil.copy2(self.manifest_path,self.backup_dir/f"observable_thresholds_{stamp}.manifest.json")
        payload={"protocol_version":PROTOCOL_VERSION,"profile_version":f"1.0.{stamp}","thresholds":current}
        raw=(json.dumps(payload,indent=2,sort_keys=True)+"\n").encode(); digest=hashlib.sha256(raw).hexdigest(); manifest={"protocol_version":PROTOCOL_VERSION,"profile_version":payload["profile_version"],"file_sha256":digest,"allowed_keys":sorted(ALLOWED_KEYS),"updated_at":datetime.now(timezone.utc).isoformat()}
        tmp=self.profile_path.with_suffix(".tmp"); tmp.write_bytes(raw); os.replace(tmp,self.profile_path)
        tmpm=self.manifest_path.with_suffix(".tmp"); tmpm.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n",encoding="utf-8"); os.replace(tmpm,self.manifest_path)
        after=ThresholdProfileLoader(self.profile_path,self.manifest_path).load()
        event={"timestamp":datetime.now(timezone.utc).isoformat(),"actor":actor,"reason":reason,"before_hash":before.sha256,"after_hash":after.sha256,"changes":changes}
        with self.audit_path.open("a",encoding="utf-8") as f: f.write(json.dumps(event,sort_keys=True)+"\n")
        return event
