from __future__ import annotations
import hashlib, json
from .observable_models import *
from .observable_thresholds import ObservableThresholdProfile, PROTOCOL_VERSION

class ObservableUniverseEngine:
    def __init__(self, repository, profile: ObservableThresholdProfile): self.repository=repository; self.profile=profile
    @staticmethod
    def _hash(payload)->str: return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
    def build_context(self, filters: ObservableFilters, *, paired: bool=False)->FrozenObservableContext:
        f=filters.normalized(); observations=self.repository.fetch_intersection(f)
        ids=tuple(x.observation_id for x in observations)
        unique_ids=len(set(ids)); sample_count=len(observations) if f.variant else unique_ids
        paired_count=unique_ids if paired else 0
        observable_min=self.profile.get("paired_observable" if paired else "regime_observable")
        powered_min=self.profile.get("paired_powered" if paired else "powered_samples")
        count=paired_count if paired else sample_count
        state=ObservableState.UNOBSERVABLE if count < observable_min else ObservableState.OBSERVABLE_BUT_UNDERPOWERED if count < powered_min else ObservableState.OBSERVABLE
        power=PowerState.POWERED if count >= powered_min else PowerState.UNPOWERED
        filter_payload=f.__dict__; snapshot=self._hash([(o.observation_id,o.variant,o.selected,o.outcome_r) for o in observations])
        context_id=self._hash({"protocol":PROTOCOL_VERSION,"profile":self.profile.sha256,"filters":filter_payload,"snapshot":snapshot})[:24]
        artifact=self._hash({"context_id":context_id,"ids":ids,"state":state.value,"power":power.value,"count":count})
        return FrozenObservableContext(context_id,PROTOCOL_VERSION,self.profile.sha256,f,observations,ids,sample_count,paired_count,state,power,snapshot,artifact)
    @staticmethod
    def verify_context(ctx: FrozenObservableContext)->bool:
        artifact=ObservableUniverseEngine._hash({"context_id":ctx.context_id,"ids":ctx.observation_ids,"state":ctx.observability_state.value,"power":ctx.power_state.value,"count":ctx.paired_sample_count if ctx.paired_sample_count else ctx.sample_count})
        return artifact == ctx.artifact_hash
