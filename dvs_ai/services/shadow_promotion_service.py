from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


class ShadowPromotionService:
    """Human-gated SHADOW-only config writer with backup, audit, and rollback."""

    ALLOWED_KEYS = {"shadow_confidence", "shadow_entry", "shadow_risk_max", "shadow_rr_min"}
    FAMILY_KEYS = {"TIMING", "ENTRY", "ORDER_FLOW", "DIRECTION", "MARKET"}

    def __init__(self, config_path: str = "config.json", audit_dir: str = "data/shadow_promotions") -> None:
        self.config_path = Path(config_path)
        self.audit_dir = Path(audit_dir)

    @staticmethod
    def _digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def apply(self, candidate: dict, backtest: dict, *, human_confirmation: str) -> dict:
        if human_confirmation != "APPLY TO SHADOW":
            raise PermissionError("Cần xác nhận chính xác: APPLY TO SHADOW")
        if backtest.get("state") != "PASS" or not backtest.get("approved_for_human_review"):
            raise ValueError("Backtest chưa PASS; không được apply SHADOW.")
        proposal = dict(candidate.get("candidate", {}) or {})
        forbidden = sorted(k for k in proposal if k not in self.ALLOWED_KEYS)
        if forbidden:
            raise ValueError(f"Candidate chứa key ngoài SHADOW allowlist: {forbidden}")
        forbidden_top = sorted(
            k for k in candidate
            if str(k).startswith("main_")
            and k not in {"main_config_mutated", "main_optimization_blocked"}
        )
        if forbidden_top:
            raise ValueError(f"Top-level MAIN parameter bị cấm: {forbidden_top}")
        if candidate.get("main_config_mutated") is not False:
            raise ValueError("Candidate không chứng minh MAIN immutable.")
        weights = dict(candidate.get("evidence_fusion_family_weights", {}) or {})
        if set(weights) != self.FAMILY_KEYS:
            raise ValueError("Evidence weights thiếu hoặc thừa family.")
        total = sum(float(v) for v in weights.values())
        if abs(total - 1.0) > 1e-4 or float(weights["ORDER_FLOW"]) > 0.400001:
            raise ValueError("Evidence weights không đạt guardrail.")

        raw = json.loads(self.config_path.read_text(encoding="utf-8"))
        main_before = {k: raw.get(k) for k in raw if str(k).startswith("main_")}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        backup = self.audit_dir / f"config_before_shadow_{stamp}.json"
        shutil.copy2(self.config_path, backup)
        before_hash = self._digest(self.config_path)
        for key, value in proposal.items():
            raw[key] = float(value)
        raw["evidence_fusion_family_weights"] = {k: float(v) for k, v in weights.items()}
        main_after = {k: raw.get(k) for k in raw if str(k).startswith("main_")}
        if main_before != main_after:
            raise RuntimeError("MAIN immutability violation detected.")
        temp = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
        temp.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.config_path)
        after_hash = self._digest(self.config_path)
        audit = {
            "schema": "DVS_SHADOW_PROMOTION_AUDIT_V1",
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "scope": "SHADOW_ONLY",
            "human_confirmation": True,
            "candidate_schema": candidate.get("schema"),
            "backtest_state": backtest.get("state"),
            "backup_path": str(backup),
            "config_hash_before": before_hash,
            "config_hash_after": after_hash,
            "main_unchanged": main_before == main_after,
            "applied": proposal,
            "evidence_fusion_family_weights": weights,
            "live_execution_enabled": False,
        }
        audit_path = self.audit_dir / f"promotion_{stamp}.json"
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        audit["audit_path"] = str(audit_path)
        return audit

    def rollback(self, backup_path: str, *, human_confirmation: str) -> dict:
        if human_confirmation != "ROLLBACK SHADOW":
            raise PermissionError("Cần xác nhận chính xác: ROLLBACK SHADOW")
        backup = Path(backup_path)
        if not backup.exists():
            raise FileNotFoundError(backup)
        current = json.loads(self.config_path.read_text(encoding="utf-8"))
        prior = json.loads(backup.read_text(encoding="utf-8"))
        current_main = {k: v for k, v in current.items() if str(k).startswith("main_")}
        prior_main = {k: v for k, v in prior.items() if str(k).startswith("main_")}
        if current_main != prior_main:
            raise RuntimeError("Rollback bị chặn vì MAIN baseline không khớp.")
        shutil.copy2(backup, self.config_path)
        return {"state": "ROLLED_BACK", "backup_path": str(backup), "main_unchanged": True}
