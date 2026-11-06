"""Elect and activate an overlay in the current Windows user session."""

from __future__ import annotations

import ctypes
import hashlib
import math
import mmap
import os
import struct
import time
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from functools import lru_cache


# Only the elected primary retains a mapping outside the short launch transaction.
# The OS removes it when its final handle closes, including after a hard exit.
_STATE = struct.Struct("<QI16sBB")  # receipt, PID, instance ID, reveal, closing
_RECEIPT = struct.Struct("<Q")
_REVEAL = _STATE.size - 2
_CLOSING = _STATE.size - 1


@dataclass
class InstanceLease:
    """Only the GUI thread consumes reveal requests or closes a primary lease."""

    primary: bool
    _state: mmap.mmap | None = None
    _mutex_name: str = ""

    def take_activation(self) -> bool:
        state = self._state
        if state is None or state[_CLOSING] or not state[_REVEAL]:
            return False
        # All launchers in this batch observe the same receipt. Never wait on
        # another process on the Tk thread: leave the request for the next tick.
        try:
            with _launch_transaction(_windows_api(), self._mutex_name, deadline=0):
                receipt, = _RECEIPT.unpack_from(state)
                _RECEIPT.pack_into(state, 0, receipt + 1)
                state[_REVEAL] = 0
        except TimeoutError:
            return False
        return True

    def begin_close(self) -> None:
        if self._state is not None:
            self._state[_CLOSING] = 1

    def close(self) -> None:
        if self._state is not None:
            self.begin_close()
            self._state.close()
            self._state = None


class _WindowsAPI:
    def __init__(self) -> None:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        security = ctypes.WinDLL("advapi32", use_last_error=True)
        user = ctypes.WinDLL("user32", use_last_error=True)
        handle, dword, boolean = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL
        pointer = ctypes.c_void_p

        def bind(library, name, result, *arguments):
            function = getattr(library, name)
            function.restype, function.argtypes = result, arguments
            return function

        self.create_mutex = bind(kernel, "CreateMutexW", handle, pointer, boolean, wintypes.LPCWSTR)
        self.wait = bind(kernel, "WaitForSingleObject", dword, handle, dword)
        self.release = bind(kernel, "ReleaseMutex", boolean, handle)
        self.close = bind(kernel, "CloseHandle", boolean, handle)
        self.allow_foreground = bind(user, "AllowSetForegroundWindow", boolean, dword)
        current_process = bind(kernel, "GetCurrentProcess", handle)
        open_token = bind(security, "OpenProcessToken", boolean, handle, dword, ctypes.POINTER(handle))
        token_info = bind(
            security, "GetTokenInformation", boolean, handle, ctypes.c_int,
            pointer, dword, ctypes.POINTER(dword),
        )
        sid_length = bind(security, "GetLengthSid", dword, pointer)
        token = handle()
        if not open_token(current_process(), 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            size = dword()
            token_info(token, 1, None, 0, ctypes.byref(size))  # TokenUser
            if not size.value:
                raise ctypes.WinError(ctypes.get_last_error())
            info = ctypes.create_string_buffer(size.value)
            if not token_info(token, 1, info, size, ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            # TOKEN_USER starts with the PSID in SID_AND_ATTRIBUTES.
            sid = ctypes.cast(info, ctypes.POINTER(pointer))[0]
            self.user_sid = ctypes.string_at(sid, sid_length(sid))
        finally:
            self.close(token)


@lru_cache(maxsize=1)
def _windows_api() -> _WindowsAPI:
    return _WindowsAPI()


@contextmanager
def _launch_transaction(api: _WindowsAPI, name: str, deadline: float):
    handle = api.create_mutex(None, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        milliseconds = min(0xFFFFFFFE, math.ceil(max(0.0, deadline - time.monotonic()) * 1000))
        status = api.wait(handle, milliseconds)
        if status == 258:  # WAIT_TIMEOUT
            raise TimeoutError("Timed out waiting for the previous subtitle launch.")
        if status not in (0, 0x80):  # WAIT_OBJECT_0 or WAIT_ABANDONED
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            api.release(handle)
    finally:
        api.close(handle)


def acquire_instance(name: str = "live-overlay", *, timeout: float = 45.0) -> InstanceLease:
    """Become primary, or request that the existing GUI reveal itself.

    A duplicate exits after the GUI accepts its request. Leave no mapping
    handle open between attempts so a crash or shutdown before acceptance
    lets a waiting launcher become the replacement. Only launchers wait.
    """
    if os.name != "nt":
        return InstanceLease(True)
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError("Instance launch timeout must be finite and nonnegative.")
    api = _windows_api()
    key = hashlib.sha256(api.user_sid + b"\0" + name.encode("utf-8")).hexdigest()
    prefix = f"Local\\RuZhLiveSubtitles.v1.{key}"
    mutex_name = prefix + ".Launch"
    deadline = time.monotonic() + timeout
    awaiting: tuple[bytes, int] | None = None
    while True:
        with _launch_transaction(api, mutex_name, deadline):
            state = mmap.mmap(-1, _STATE.size, tagname=prefix + ".State")
            retain = False
            try:
                receipt, pid, instance_id, _, closing = _STATE.unpack_from(state)
                if not pid:  # a new paging-file mapping starts with zero bytes
                    state[:] = _STATE.pack(0, os.getpid(), os.urandom(16), 0, 0)
                    lease = InstanceLease(True, state, mutex_name)
                    retain = True
                    return lease
                if awaiting is not None and awaiting[0] == instance_id:
                    if receipt != awaiting[1]:
                        return InstanceLease(False)
                elif not closing:
                    # Windows may deny foreground permission. Restoration and
                    # the taskbar attention fallback still run in the primary.
                    api.allow_foreground(pid)
                    awaiting = (instance_id, receipt)
                    state[_REVEAL] = 1
            finally:
                if not retain:
                    state.close()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if closing:
                raise TimeoutError("The previous subtitle window is still closing. Try opening it again.")
            raise TimeoutError("The previous subtitle window did not respond to the activation request.")
        time.sleep(min(0.05, remaining))
