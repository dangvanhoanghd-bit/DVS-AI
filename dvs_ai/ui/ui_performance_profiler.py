from __future__ import annotations

from contextlib import contextmanager
from PySide6.QtCore import QObject


class UIPerformanceProfiler(QObject):
    """Production-clean profiler facade.

    Keeps the UI/API contract used by MainWindow and RuntimeTelemetryExporter,
    but performs no watchdog polling, per-callback timing, JSONL writes, sorting,
    percentile computation, or report logging on the GUI thread.
    """

    def __init__(self, parent=None, **_kwargs):
        super().__init__(parent)
        self.current_section = "DISABLED_PRODUCTION_CLEAN"
        self.last_event_loop_lag_ms = 0.0
        self.max_event_loop_lag_ms = 0.0
        self.event_loop_stall_count = 0
        self.last_burn_in_summary = {}

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    @contextmanager
    def section(self, _name: str):
        yield

    def record(self, _name: str, _elapsed_ms: float) -> None:
        return None

    def record_commit_metrics(self, metrics: dict, *, rolling_window: int = 100) -> dict:
        del rolling_window
        summary = {
            "commit_count": 0,
            "rolling_window": 0,
            "avg_commit_ms": 0.0,
            "p50_commit_ms": 0.0,
            "p90_commit_ms": 0.0,
            "p99_commit_ms": 0.0,
            "max_commit_ms": 0.0,
            "variance_commit_ms2": 0.0,
            "slope_ms_per_commit": 0.0,
            "rows_updated_ratio": 0.0,
            "fingerprint_hit_ratio": 0.0,
            "production_clean": True,
            "source_rows_considered": int(metrics.get("rows_considered", 0)),
        }
        self.last_burn_in_summary = summary
        return summary

    def build_report(self, recent: int = 80) -> dict:
        del recent
        return {
            "sections": {},
            "recent_sample_count": 0,
            "current_section": self.current_section,
            "last_event_loop_lag_ms": 0.0,
            "max_event_loop_lag_ms": 0.0,
            "event_loop_stall_count": 0,
            "production_clean": True,
        }

    def log_report(self, reason: str = "manual") -> dict:
        del reason
        return self.build_report()
