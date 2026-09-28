"""Windows resource ownership without a Python extension dependency.

Imported only on Windows. The harness waits for its JSON payload until the
parent attaches it to this job, so user code cannot run before limits apply.
A job is resource containment for local learner code, not a hostile-code fence.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import math


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IOCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IOCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class Job:
    """Own the process tree, its memory and CPU budget, until close.

    Failure to create/configure/assign is fatal. Falling back to a naked
    subprocess would silently remove the Windows resource limits.
    """

    def __init__(self, process, *, mem_limit_mb: int, timeout: float) -> None:
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        api.CreateJobObjectW.restype = wintypes.HANDLE
        api.SetInformationJobObject.argtypes = (
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        )
        api.SetInformationJobObject.restype = wintypes.BOOL
        api.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        api.AssignProcessToJobObject.restype = wintypes.BOOL
        api.CloseHandle.argtypes = (wintypes.HANDLE,)
        api.CloseHandle.restype = wintypes.BOOL
        self._api = api
        self._handle = api.CreateJobObjectW(None, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _ExtendedLimits()
        # JOB_TIME | ACTIVE_PROCESS | JOB_MEMORY | KILL_ON_JOB_CLOSE.
        limits.BasicLimitInformation.LimitFlags = 0x4 | 0x8 | 0x200 | 0x2000
        limits.BasicLimitInformation.PerJobUserTimeLimit = (
            math.ceil(timeout + 1) * 10_000_000
        )
        limits.BasicLimitInformation.ActiveProcessLimit = 64
        limits.JobMemoryLimit = mem_limit_mb * 1024 * 1024
        try:
            if not api.SetInformationJobObject(
                self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            # CPython exposes the Windows process HANDLE on Popen. Using the
            # handle avoids a pid lookup race and requesting new privileges.
            if not api.AssignProcessToJobObject(self._handle, int(process._handle)):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        """Closing the sole noninherited handle terminates every job member."""
        if self._handle:
            self._api.CloseHandle(self._handle)
            self._handle = None
