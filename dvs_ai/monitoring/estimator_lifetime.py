from __future__ import annotations
from contextlib import AbstractContextManager
from datetime import datetime, timezone
import time
from typing import Callable, Any
from .thread_identity import capture_thread_identity

class EstimatorLifetime(AbstractContextManager):
    """Lexical measurement scope; stores metadata only and never payload references."""
    def __init__(self, *, budget_name:str, owner_path:str, emit:Callable[[dict],Any]|None=None, gui_thread_id:int|None=None):
        self.budget_name=budget_name; self.owner_path=owner_path; self.emit=emit; self.gui_thread_id=gui_thread_id; self.started_ns=0
    def _record(self,event:str,**extra):
        record={"schema_version":"1.0","event":event,"timestamp_utc":datetime.now(timezone.utc).isoformat(),"budget_name":self.budget_name,"owner_path":self.owner_path,**capture_thread_identity(self.gui_thread_id),**extra}
        if self.emit:
            try:self.emit(record)
            except Exception:pass
        return record
    def __enter__(self):
        self.started_ns=time.perf_counter_ns(); self._record("measurement_begin"); return self
    def __exit__(self, exc_type, exc, tb):
        duration=(time.perf_counter_ns()-self.started_ns)/1_000_000 if self.started_ns else 0.0
        self._record("measurement_end",measurement_duration_ms=round(duration,6),measurement_ok=exc_type is None)
        return False
