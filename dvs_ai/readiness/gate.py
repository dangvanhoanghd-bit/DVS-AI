from __future__ import annotations
from collections.abc import Mapping
from .models import DeploymentMode, ReadinessCheck, ReadinessReport

REQUIRED_CHECKS=("scientific_core","ledger_integrity","explainability","replay","risk_engine","monitoring","shadow_kpi","paper_kpi")

class ProductionReadinessGate:
    def evaluate(self, checks: Mapping[str, bool | ReadinessCheck]) -> ReadinessReport:
        result=[]; reasons=[]
        for name in REQUIRED_CHECKS:
            raw=checks.get(name, False)
            check=raw if isinstance(raw, ReadinessCheck) else ReadinessCheck(name, bool(raw), "")
            if check.name != name:
                check=ReadinessCheck(name, check.passed, check.detail)
            result.append(check)
            if not check.passed:
                reasons.append(f"READINESS_{name.upper()}_FAILED")
        mode=DeploymentMode.LIVE_ELIGIBLE if not reasons else DeploymentMode.SIMULATION_ONLY
        return ReadinessReport(mode, tuple(result), tuple(reasons))
