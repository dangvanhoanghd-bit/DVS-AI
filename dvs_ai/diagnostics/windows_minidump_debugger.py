"""Windows native crash capture used by the external PLF supervisor.

The child process is launched under the Windows Debug API. On a second-chance
native exception, the supervisor writes a MiniDump while the faulting process
is still suspended at the exception. This module is supervisor-side only and
never imports Qt or modifies the child application runtime.
"""
from __future__ import annotations

import ctypes
import json
import os
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA = "dvs.native_crash_capture.v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n")
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass


if os.name == "nt":
    ULONG_PTR = wintypes.WPARAM
    SIZE_T = ctypes.c_size_t

    class EXCEPTION_RECORD(ctypes.Structure):
        _fields_ = [
            ("ExceptionCode", wintypes.DWORD),
            ("ExceptionFlags", wintypes.DWORD),
            ("ExceptionRecord", ctypes.c_void_p),
            ("ExceptionAddress", ctypes.c_void_p),
            ("NumberParameters", wintypes.DWORD),
            ("ExceptionInformation", ULONG_PTR * 15),
        ]

    class EXCEPTION_DEBUG_INFO(ctypes.Structure):
        _fields_ = [("ExceptionRecord", EXCEPTION_RECORD), ("dwFirstChance", wintypes.DWORD)]

    class CREATE_THREAD_DEBUG_INFO(ctypes.Structure):
        _fields_ = [("hThread", wintypes.HANDLE), ("lpThreadLocalBase", ctypes.c_void_p), ("lpStartAddress", ctypes.c_void_p)]

    class CREATE_PROCESS_DEBUG_INFO(ctypes.Structure):
        _fields_ = [
            ("hFile", wintypes.HANDLE), ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
            ("lpBaseOfImage", ctypes.c_void_p), ("dwDebugInfoFileOffset", wintypes.DWORD),
            ("nDebugInfoSize", wintypes.DWORD), ("lpThreadLocalBase", ctypes.c_void_p),
            ("lpStartAddress", ctypes.c_void_p), ("lpImageName", ctypes.c_void_p), ("fUnicode", wintypes.WORD),
        ]

    class EXIT_THREAD_DEBUG_INFO(ctypes.Structure):
        _fields_ = [("dwExitCode", wintypes.DWORD)]

    class EXIT_PROCESS_DEBUG_INFO(ctypes.Structure):
        _fields_ = [("dwExitCode", wintypes.DWORD)]

    class LOAD_DLL_DEBUG_INFO(ctypes.Structure):
        _fields_ = [
            ("hFile", wintypes.HANDLE), ("lpBaseOfDll", ctypes.c_void_p),
            ("dwDebugInfoFileOffset", wintypes.DWORD), ("nDebugInfoSize", wintypes.DWORD),
            ("lpImageName", ctypes.c_void_p), ("fUnicode", wintypes.WORD),
        ]

    class UNLOAD_DLL_DEBUG_INFO(ctypes.Structure):
        _fields_ = [("lpBaseOfDll", ctypes.c_void_p)]

    class OUTPUT_DEBUG_STRING_INFO(ctypes.Structure):
        _fields_ = [("lpDebugStringData", ctypes.c_void_p), ("fUnicode", wintypes.WORD), ("nDebugStringLength", wintypes.WORD)]

    class RIP_INFO(ctypes.Structure):
        _fields_ = [("dwError", wintypes.DWORD), ("dwType", wintypes.DWORD)]

    class DEBUG_EVENT_UNION(ctypes.Union):
        _fields_ = [
            ("Exception", EXCEPTION_DEBUG_INFO), ("CreateThread", CREATE_THREAD_DEBUG_INFO),
            ("CreateProcessInfo", CREATE_PROCESS_DEBUG_INFO), ("ExitThread", EXIT_THREAD_DEBUG_INFO),
            ("ExitProcess", EXIT_PROCESS_DEBUG_INFO), ("LoadDll", LOAD_DLL_DEBUG_INFO),
            ("UnloadDll", UNLOAD_DLL_DEBUG_INFO), ("DebugString", OUTPUT_DEBUG_STRING_INFO), ("RipInfo", RIP_INFO),
        ]

    class DEBUG_EVENT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("dwDebugEventCode", wintypes.DWORD), ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD), ("u", DEBUG_EVENT_UNION)]

    class MODULEENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("th32ModuleID", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
            ("GlblcntUsage", wintypes.DWORD), ("ProccntUsage", wintypes.DWORD), ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
            ("modBaseSize", wintypes.DWORD), ("hModule", wintypes.HMODULE), ("szModule", wintypes.WCHAR * 256),
            ("szExePath", wintypes.WCHAR * 260),
        ]


EXCEPTION_DEBUG_EVENT = 1
CREATE_PROCESS_DEBUG_EVENT = 3
EXIT_PROCESS_DEBUG_EVENT = 5
LOAD_DLL_DEBUG_EVENT = 6
DBG_CONTINUE = 0x00010002
DBG_EXCEPTION_NOT_HANDLED = 0x80010001
ERROR_SEM_TIMEOUT = 121
INFINITE = 0xFFFFFFFF
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
GENERIC_WRITE = 0x40000000
CREATE_ALWAYS = 2
FILE_ATTRIBUTE_NORMAL = 0x80

# Useful, bounded dump: native stacks, module list, unloaded modules, handles,
# thread/process data and memory referenced by stack/registers; not a full dump.
MINIDUMP_TYPE = (
    0x00000004  # MiniDumpWithHandleData
    | 0x00000020  # MiniDumpWithUnloadedModules
    | 0x00000040  # MiniDumpWithIndirectlyReferencedMemory
    | 0x00000100  # MiniDumpWithProcessThreadData
    | 0x00000800  # MiniDumpWithFullMemoryInfo
    | 0x00001000  # MiniDumpWithThreadInfo
    | 0x00020000  # MiniDumpIgnoreInaccessibleMemory
    | 0x00080000  # MiniDumpWithModuleHeaders
)


def _hex_ptr(value: Any) -> str | None:
    try:
        ptr = int(value or 0)
    except Exception:
        return None
    return f"0x{ptr:016X}" if ptr else None


def resolve_module_for_address(pid: int, address: int) -> dict[str, Any] | None:
    if os.name != "nt" or not address:
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap == INVALID_HANDLE_VALUE:
        return None
    try:
        entry = MODULEENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        if not kernel32.Module32FirstW(snap, ctypes.byref(entry)):
            return None
        while True:
            base = ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value or 0
            size = int(entry.modBaseSize)
            if base <= address < base + size:
                return {
                    "module_name": entry.szModule,
                    "module_path": entry.szExePath,
                    "module_base": _hex_ptr(base),
                    "module_size": size,
                    "module_offset": _hex_ptr(address - base),
                }
            if not kernel32.Module32NextW(snap, ctypes.byref(entry)):
                return None
    finally:
        kernel32.CloseHandle(snap)


def write_minidump(process_handle: int, pid: int, dump_path: Path) -> tuple[bool, int | None]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    dbghelp = ctypes.WinDLL("dbghelp", use_last_error=True)
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    file_handle = kernel32.CreateFileW(str(dump_path), GENERIC_WRITE, 0, None, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, None)
    if file_handle == INVALID_HANDLE_VALUE:
        return False, ctypes.get_last_error()
    try:
        dbghelp.MiniDumpWriteDump.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        dbghelp.MiniDumpWriteDump.restype = wintypes.BOOL
        ok = bool(dbghelp.MiniDumpWriteDump(process_handle, pid, file_handle, MINIDUMP_TYPE, None, None, None))
        return ok, None if ok else ctypes.get_last_error()
    finally:
        kernel32.CloseHandle(file_handle)


def debug_child(process: Any, session_id: str, artifacts: Path, build_id: str) -> dict[str, Any]:
    """Pump Windows debug events until the child exits and capture second-chance crashes."""
    if os.name != "nt":
        return {"enabled": False, "reason": "non_windows"}
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WaitForDebugEvent.argtypes = [ctypes.POINTER(DEBUG_EVENT), wintypes.DWORD]
    kernel32.WaitForDebugEvent.restype = wintypes.BOOL
    kernel32.ContinueDebugEvent.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
    kernel32.ContinueDebugEvent.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    journal = artifacts / "native_crash_capture.jsonl"
    summary_path = artifacts / f"native_crash_capture_{session_id}.json"
    process_handle = None
    captured: list[dict[str, Any]] = []
    exit_code = None
    event = DEBUG_EVENT()
    append_jsonl(journal, {"schema": SCHEMA, "event": "native_debug_loop_started", "timestamp_utc": utc_now(), "session_id": session_id, "child_pid": process.pid, "build_id": build_id})

    while True:
        if not kernel32.WaitForDebugEvent(ctypes.byref(event), INFINITE):
            error = ctypes.get_last_error()
            append_jsonl(journal, {"schema": SCHEMA, "event": "wait_for_debug_event_failed", "timestamp_utc": utc_now(), "session_id": session_id, "winerror": error})
            break
        code = int(event.dwDebugEventCode)
        continue_status = DBG_CONTINUE
        if code == CREATE_PROCESS_DEBUG_EVENT:
            info = event.CreateProcessInfo
            process_handle = info.hProcess
            if info.hFile:
                kernel32.CloseHandle(info.hFile)
            append_jsonl(journal, {"schema": SCHEMA, "event": "debug_create_process", "timestamp_utc": utc_now(), "session_id": session_id, "child_pid": int(event.dwProcessId), "initial_thread_id": int(event.dwThreadId), "image_base": _hex_ptr(info.lpBaseOfImage)})
        elif code == LOAD_DLL_DEBUG_EVENT:
            if event.LoadDll.hFile:
                kernel32.CloseHandle(event.LoadDll.hFile)
        elif code == EXCEPTION_DEBUG_EVENT:
            info = event.Exception
            rec = info.ExceptionRecord
            exception_code = int(rec.ExceptionCode)
            first_chance = bool(info.dwFirstChance)
            address = int(ctypes.cast(rec.ExceptionAddress, ctypes.c_void_p).value or 0)
            module = resolve_module_for_address(int(event.dwProcessId), address)
            row = {
                "schema": SCHEMA, "event": "native_exception", "timestamp_utc": utc_now(), "session_id": session_id,
                "child_pid": int(event.dwProcessId), "faulting_thread_id": int(event.dwThreadId),
                "exception_code": exception_code, "exception_code_hex": f"0x{exception_code:08X}",
                "first_chance": first_chance, "exception_flags": int(rec.ExceptionFlags),
                "faulting_address": _hex_ptr(address), "number_parameters": int(rec.NumberParameters),
                "exception_information": [int(rec.ExceptionInformation[i]) for i in range(min(int(rec.NumberParameters), 15))],
                "faulting_module": module,
            }
            append_jsonl(journal, row)
            if first_chance:
                continue_status = DBG_EXCEPTION_NOT_HANDLED
            else:
                dump_name = f"native_crash_{session_id}_pid{event.dwProcessId}_tid{event.dwThreadId}_{exception_code:08X}.dmp"
                dump_path = artifacts / dump_name
                ok, winerror = write_minidump(process_handle or process._handle, int(event.dwProcessId), dump_path)
                row.update({"dump_created": ok, "dump_path": str(dump_path), "dump_size_bytes": dump_path.stat().st_size if ok and dump_path.exists() else 0, "dump_winerror": winerror, "minidump_type": MINIDUMP_TYPE})
                captured.append(row)
                append_jsonl(journal, {**row, "event": "native_minidump_written"})
                continue_status = DBG_EXCEPTION_NOT_HANDLED
        elif code == EXIT_PROCESS_DEBUG_EVENT:
            exit_code = int(event.ExitProcess.dwExitCode)
            append_jsonl(journal, {"schema": SCHEMA, "event": "debug_exit_process", "timestamp_utc": utc_now(), "session_id": session_id, "child_pid": int(event.dwProcessId), "exit_code_unsigned_32": exit_code, "exit_code_hex": f"0x{exit_code:08X}"})

        kernel32.ContinueDebugEvent(event.dwProcessId, event.dwThreadId, continue_status)
        if code == EXIT_PROCESS_DEBUG_EVENT:
            break

    summary = {
        "schema": SCHEMA, "session_id": session_id, "build_id": build_id, "child_pid": process.pid,
        "debugger_enabled": True, "native_exceptions_captured": len(captured), "captures": captured,
        "debug_exit_code_unsigned_32": exit_code, "debug_exit_code_hex": f"0x{exit_code:08X}" if exit_code is not None else None,
        "native_stack_analysis_status": "DUMP_CAPTURED_REQUIRES_WINDBG_ANALYSIS" if any(x.get("dump_created") for x in captured) else "NO_DUMP_CAPTURED",
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    append_jsonl(journal, {"schema": SCHEMA, "event": "native_debug_loop_finished", "timestamp_utc": utc_now(), "session_id": session_id, "summary_path": str(summary_path), "captures": len(captured)})
    return summary
