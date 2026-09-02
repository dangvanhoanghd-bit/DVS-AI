from __future__ import annotations
import threading
from dataclasses import asdict, dataclass

@dataclass(frozen=True)
class ThreadIdentity:
    measurement_thread_id: int
    gui_thread_id: int | None
    thread_name: str
    is_gui_thread: bool | None

def capture_thread_identity(gui_thread_id: int | None) -> dict:
    current=threading.get_ident()
    return asdict(ThreadIdentity(current, gui_thread_id, threading.current_thread().name, None if gui_thread_id is None else current==gui_thread_id))
