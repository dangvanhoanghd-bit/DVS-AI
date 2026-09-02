from __future__ import annotations

"""Frozen governance contract for a future Paper authority handover.

The profile is intentionally defined before GUI shadow observations are used.
This module does not activate a handover and exposes no execution capability.
"""

from dataclasses import asdict, dataclass
from hashlib import sha256
import json


@dataclass(frozen=True, slots=True)
class PaperAuthorityHandoverProfile:
    profile_id: str = "paper-authority-handover-v2-actionable-evidence"
    minimum_parallel_cycles: int = 500
    minimum_full_agreement_ratio: float = 0.85
    minimum_actionable_count: int = 30
    minimum_actionable_ratio: float = 0.05
    maximum_unsafe_divergences: int = 0
    require_unified_not_more_aggressive: bool = True
    required_approvals: int = 2
    governance_phrase_hash: str = "UNSET_REQUIRES_FOUR_EYES"

    def canonical_payload(self) -> dict[str, object]:
        return asdict(self)

    @property
    def profile_hash(self) -> str:
        payload = json.dumps(
            self.canonical_payload(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return sha256(payload).hexdigest()


FROZEN_PAPER_AUTHORITY_HANDOVER_PROFILE = PaperAuthorityHandoverProfile()
