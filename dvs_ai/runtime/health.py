from __future__ import annotations
from collections.abc import Callable
from datetime import datetime, timezone
from .models import ComponentHealth, HealthReport, HealthStatus

HealthCheck = Callable[[], ComponentHealth]

class RuntimeHealthMonitor:
    def __init__(self) -> None:
        self._checks: dict[str, HealthCheck] = {}
        self._heartbeats: dict[str, datetime] = {}

    def register_check(self, name: str, check: HealthCheck) -> None:
        if not name or name in self._checks:
            raise ValueError("health check name must be unique and non-empty")
        self._checks[name] = check

    def heartbeat(self, component: str, *, at: datetime | None = None) -> None:
        if not component:
            raise ValueError("component is required")
        self._heartbeats[component] = at or datetime.now(timezone.utc)

    def check_heartbeat(self, component: str, *, max_age_seconds: float,
                        now: datetime | None = None) -> ComponentHealth:
        now = now or datetime.now(timezone.utc)
        last = self._heartbeats.get(component)
        if last is None:
            return ComponentHealth(component, HealthStatus.UNHEALTHY, "heartbeat missing")
        age = max(0.0, (now - last).total_seconds())
        status = HealthStatus.HEALTHY if age <= max_age_seconds else HealthStatus.UNHEALTHY
        return ComponentHealth(component, status, "heartbeat current" if status is HealthStatus.HEALTHY else "heartbeat stale", {"age_seconds": age})

    def run(self) -> HealthReport:
        results: list[ComponentHealth] = []
        for name, check in self._checks.items():
            try:
                result = check()
                if result.name != name:
                    result = ComponentHealth(name, result.status, result.message, result.metrics, result.checked_at)
            except Exception as exc:
                result = ComponentHealth(name, HealthStatus.UNHEALTHY, f"check exception: {type(exc).__name__}")
            results.append(result)
        statuses = {item.status for item in results}
        overall = (HealthStatus.UNHEALTHY if HealthStatus.UNHEALTHY in statuses else
                   HealthStatus.DEGRADED if HealthStatus.DEGRADED in statuses else HealthStatus.HEALTHY)
        return HealthReport(overall, tuple(results))
