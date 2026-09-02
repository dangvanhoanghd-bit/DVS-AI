from __future__ import annotations

import os
import threading
import time
import weakref
from datetime import datetime, timezone
from pathlib import Path
import json

from PySide6 import QtCore

_ORIGINAL_QTHREAD = QtCore.QThread

class QThreadLifecycleRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[int, dict] = {}
        self._path = Path("artifacts/runtime/qthread_lifecycle.jsonl")

    def _write(self, event: str, **fields) -> None:
        payload={"schema_version":"dvs.qthread.lifecycle.v1","event":event,
                 "timestamp_utc":datetime.now(timezone.utc).isoformat(),
                 "monotonic_ns":time.monotonic_ns(),"pid":os.getpid(),**fields}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a",encoding="utf-8") as f:
                f.write(json.dumps(payload,ensure_ascii=False,sort_keys=True)+"\n")
        except Exception:
            pass

    def register(self, thread, creator: str = "") -> None:
        key=id(thread)
        try: name=thread.objectName()
        except Exception: name=""
        with self._lock:
            self._items[key]={"ref":weakref.ref(thread),"creator":creator,"registered_ns":time.monotonic_ns()}
        self._write("qthread_registered",object_id=hex(key),object_name=name,creator=creator)
        try:
            thread.started.connect(lambda k=key: self._state("qthread_started",k))
            thread.finished.connect(lambda k=key: self._state("qthread_finished",k))
            # RC6.11A (causal fix): thread.destroyed.connect(...) removed.
            # Native crash forensics (WinDbg stack: QObject::~QObject ->
            # qt_static_metacall -> PySide::SignalManager::callPythonMetaMethod
            # -> this lambda -> _destroyed() -> _describe() ->
            # shiboken6.getCppPointer() -> Shiboken::Object::cppPointers()
            # -> NULL dereference, 0xC0000005) proved that invoking any
            # Python callback from QObject.destroyed -- which fires from
            # inside the C++ destructor, while Shiboken's wrapper/pointer
            # table may already be invalidated -- is unsafe in general, and
            # specifically unsafe here because _describe() calls
            # shiboken6.getCppPointer() on the object being destroyed.
            # install_qthread_registry() replaces QtCore.QThread globally,
            # so this callback previously ran for every QThread in the
            # application, not just a specific worker.
            #
            # Losing the "qthread_destroyed" telemetry event is accepted;
            # this registry no longer learns the exact destruction instant.
            # No replacement callback is added in this patch. Existing reads
            # (snapshot()/shutdown_registered(), both already present and
            # unchanged) already resolve each entry's weakref via _get().
            # Note: weakref.ref(thread) only returns None once the Python
            # wrapper itself is garbage-collected -- it says nothing about
            # whether the underlying C++ QObject has already been
            # destroyed. If the C++ side is gone but a Python reference to
            # the wrapper still exists, _get() can return a "zombie"
            # wrapper, and subsequent calls in _describe() (objectName(),
            # isRunning(), getCppPointer()) may then fail or misbehave.
            # That risk is unchanged by this patch either way; the causal
            # fix here only removes the callback that ran unconditionally
            # from inside QObject.destroyed. Entries simply remain in
            # self._items until the process exits, instead of being
            # removed the instant destruction happens.
        except Exception:
            pass

    def _state(self,event,key):
        obj=self._get(key)
        self._write(event,**self._describe(key,obj))
    def _destroyed(self,key):
        obj=self._get(key)
        self._write("qthread_destroyed",**self._describe(key,obj))
        with self._lock: self._items.pop(key,None)
    def _get(self,key):
        with self._lock:
            item=self._items.get(key); return item["ref"]() if item else None
    def _describe(self,key,obj):
        with self._lock: creator=(self._items.get(key) or {}).get("creator","")
        if obj is None:
            return {"object_id":hex(key),"object_name":"","creator":creator,"object_alive":False,
                    "is_running":None,"is_finished":None}
        # RC6.14 (causal fix for Defect A2): weakref.ref(thread) returning a
        # non-None Python wrapper does NOT mean the underlying C++ QObject
        # is still alive -- see the RC6.11A note above. Once the destroyed
        # callback that used to auto-prune self._items was removed, stale
        # entries whose C++ side was destroyed elsewhere (deleteLater(),
        # normal thread teardown, etc.) persist in self._items for the
        # rest of the process lifetime. snapshot()/shutdown_registered()
        # then call _describe() on every entry, including these -- and the
        # shiboken6.getCppPointer() call further below reads the
        # now-invalid Shiboken pointer table for such a wrapper, causing
        # Shiboken::Object::cppPointers() to dereference NULL. WinDbg on
        # RC6.12E confirmed this exact crash (rax=0, rbx=0 at
        # cppPointers+0xea), reached via:
        #   MainWindow.closeEvent()
        #   -> QTHREAD_REGISTRY.snapshot("close_event_entered_before_shutdown")
        #   -> _describe() on a stale entry -> shiboken6.getCppPointer()
        #
        # shiboken6.isValid() is the documented, safe way to check wrapper
        # validity without touching the (possibly freed) C++ pointer
        # table. Checking it here -- at a normal read call site, never
        # from inside QObject.destroyed -- carries none of the risk that
        # made removing the destroyed-callback necessary in RC6.11A. If a
        # wrapper is found invalid, prune it from self._items immediately
        # so later snapshot()/shutdown_registered() calls never see it
        # again, restoring the cleanup the destroyed-callback used to do,
        # without ever running Python code from inside a C++ destructor.
        try:
            import shiboken6
            wrapper_valid = bool(shiboken6.isValid(obj))
        except Exception:
            wrapper_valid = None
        # RC6.14-r1: fail-closed. Only proceed to native Qt/Shiboken calls
        # (objectName(), isRunning(), getCppPointer(), parent()) when
        # wrapper_valid is explicitly True. If the isValid() check itself
        # raised (wrapper_valid is None), that is treated the same as
        # "invalid" -- prune and return safe metadata -- rather than
        # falling through to the exact dangerous calls this guard exists
        # to prevent.
        if wrapper_valid is not True:
            with self._lock:
                self._items.pop(key, None)
            return {"object_id":hex(key),"object_name":"","creator":creator,"object_alive":False,
                    "is_running":None,"is_finished":None,"pruned_stale_wrapper":True,
                    "wrapper_valid":wrapper_valid}
        try: name=obj.objectName()
        except Exception: name=""
        try: running=bool(obj.isRunning())
        except Exception: running=None
        try: finished=bool(obj.isFinished())
        except Exception: finished=None
        try:
            import shiboken6
            cpp_address = hex(int(shiboken6.getCppPointer(obj)[0]))
        except Exception:
            cpp_address = None
        try:
            parent = obj.parent()
        except Exception:
            parent = None
        return {"object_id":hex(key),"python_id":hex(key),"cpp_address":cpp_address,
                "object_name":name,"creator":creator,"object_alive":True,
                "is_running":running,"is_finished":finished,"class_name":type(obj).__name__,
                "parent_python_id":hex(id(parent)) if parent is not None else None}

    def snapshot(self, reason: str) -> list[dict]:
        with self._lock: keys=list(self._items)
        rows=[self._describe(k,self._get(k)) for k in keys]
        self._write("qthread_registry_snapshot",reason=reason,total=len(rows),running=sum(1 for r in rows if r.get("is_running")),threads=rows)
        return rows

    def shutdown_registered(self, timeout_ms: int = 5000) -> tuple[bool,list[dict]]:
        current=_ORIGINAL_QTHREAD.currentThread()
        with self._lock: keys=list(self._items)
        targets=[]
        for k in keys:
            obj=self._get(k)
            if obj is None or obj is current: continue
            # RC6.14-r1: fail-closed here too, same reasoning as
            # _describe() above. obj.isRunning() below is wrapped in
            # try/except, but that only catches ordinary Python
            # exceptions -- it does not protect against a native access
            # violation if obj is a zombie wrapper (C++ side already
            # destroyed). Checking shiboken6.isValid() first, and pruning
            # + skipping if it is not explicitly True, keeps every wrapper
            # that ever reaches obj.isRunning()/requestInterruption()/
            # quit()/wait() below confirmed valid at this point.
            try:
                import shiboken6
                wrapper_valid = bool(shiboken6.isValid(obj))
            except Exception:
                wrapper_valid = None
            if wrapper_valid is not True:
                with self._lock:
                    self._items.pop(k, None)
                continue
            try:
                if obj.isRunning(): targets.append((k,obj))
            except Exception: continue
        self._write("qthread_registry_shutdown_requested",timeout_ms=timeout_ms,target_count=len(targets),targets=[self._describe(k,o) for k,o in targets])
        for _,obj in targets:
            try: obj.requestInterruption()
            except Exception: pass
            try: obj.quit()
            except Exception: pass
        deadline=time.monotonic()+max(0,timeout_ms)/1000.0
        for _,obj in targets:
            remaining=max(0,int((deadline-time.monotonic())*1000))
            if remaining<=0: break
            try: obj.wait(remaining)
            except Exception: pass
        survivors=[]
        for k,obj in targets:
            try:
                if obj.isRunning(): survivors.append(self._describe(k,obj))
            except Exception: pass
        self._write("qthread_registry_shutdown_completed" if not survivors else "qthread_registry_shutdown_timeout",
                    timeout_ms=timeout_ms,survivor_count=len(survivors),survivors=survivors)
        return (not survivors,survivors)

REGISTRY=QThreadLifecycleRegistry()

class ManagedQThread(_ORIGINAL_QTHREAD):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        creator=""
        try:
            import inspect
            frame=inspect.stack()[1]
            creator=f"{frame.filename}:{frame.lineno}:{frame.function}"
        except Exception:
            pass
        REGISTRY.register(self,creator)

    def requestInterruption(self):
        try:
            from dvs_ai.runtime.qt_shutdown_forensics import record_thread_operation
            record_thread_operation("managed_qthread_request_interruption", self)
        except Exception:
            pass
        return super().requestInterruption()

    def quit(self):
        try:
            from dvs_ai.runtime.qt_shutdown_forensics import record_thread_operation
            record_thread_operation("managed_qthread_quit_begin", self)
        except Exception:
            pass
        result = super().quit()
        try:
            record_thread_operation("managed_qthread_quit_end", self)
        except Exception:
            pass
        return result

    def wait(self, *args, **kwargs):
        timeout = args[0] if args else kwargs.get("time", kwargs.get("deadline"))
        try:
            from dvs_ai.runtime.qt_shutdown_forensics import record_thread_operation
            record_thread_operation(
                "managed_qthread_wait_begin",
                self,
                timeout=repr(timeout),
            )
        except Exception:
            pass
        result = super().wait(*args, **kwargs)
        try:
            record_thread_operation(
                "managed_qthread_wait_end",
                self,
                timeout=repr(timeout),
                result=bool(result),
            )
        except Exception:
            pass
        return result

    def deleteLater(self):
        try:
            from dvs_ai.runtime.qt_shutdown_forensics import record_thread_operation
            record_thread_operation("managed_qthread_delete_later_called", self)
        except Exception:
            pass
        return super().deleteLater()

def install_qthread_registry() -> None:
    if QtCore.QThread is not ManagedQThread:
        QtCore.QThread=ManagedQThread
        REGISTRY._write("qthread_registry_installed",coverage="QThread objects constructed after installation through PySide6.QtCore.QThread; QObject-tree discovery is supplemental, opaque third-party native threads are outside guarantee")
