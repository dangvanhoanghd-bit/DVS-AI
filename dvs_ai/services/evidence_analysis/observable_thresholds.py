from __future__ import annotations
import hashlib, json
from dataclasses import dataclass
from pathlib import Path

PROTOCOL_VERSION = "1.0"
ALLOWED_KEYS = frozenset({"regime_observable","direction_observable","order_flow_full_observable","candidate_eligibility","paired_observable","powered_samples","paired_powered"})
DEFAULTS = {"regime_observable":30,"direction_observable":30,"order_flow_full_observable":30,"candidate_eligibility":40,"paired_observable":30,"powered_samples":60,"paired_powered":60}

class ThresholdProfileError(RuntimeError): pass

@dataclass(frozen=True)
class ObservableThresholdProfile:
    protocol_version: str
    profile_version: str
    thresholds: tuple[tuple[str,int], ...]
    sha256: str
    def get(self, key: str) -> int: return dict(self.thresholds)[key]

class ThresholdProfileLoader:
    def __init__(self, profile_path, manifest_path):
        self.profile_path=Path(profile_path); self.manifest_path=Path(manifest_path)
    @staticmethod
    def digest_bytes(data: bytes)->str: return hashlib.sha256(data).hexdigest()
    def load(self)->ObservableThresholdProfile:
        raw=self.profile_path.read_bytes(); manifest=json.loads(self.manifest_path.read_text(encoding="utf-8")); payload=json.loads(raw.decode("utf-8"))
        if self.digest_bytes(raw) != manifest.get("file_sha256"): raise ThresholdProfileError("threshold profile hash mismatch")
        if payload.get("protocol_version") != PROTOCOL_VERSION or manifest.get("protocol_version") != PROTOCOL_VERSION: raise ThresholdProfileError("protocol version mismatch")
        thresholds=payload.get("thresholds")
        if not isinstance(thresholds,dict) or set(thresholds)!=ALLOWED_KEYS: raise ThresholdProfileError("threshold allowlist mismatch")
        normalized={}
        for k,v in thresholds.items():
            if isinstance(v,bool) or not isinstance(v,int) or not 1 <= v <= 100000: raise ThresholdProfileError(f"invalid threshold {k}")
            normalized[k]=v
        if normalized["powered_samples"] < normalized["regime_observable"] or normalized["paired_powered"] < normalized["paired_observable"]: raise ThresholdProfileError("powered threshold below observable threshold")
        return ObservableThresholdProfile(PROTOCOL_VERSION,str(payload.get("profile_version","1.0.0")),tuple(sorted(normalized.items())),self.digest_bytes(raw))
