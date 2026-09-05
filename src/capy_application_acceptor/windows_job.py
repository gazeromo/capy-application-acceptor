"""Windows process tree ownership using documented Job/Thread APIs.

The initial process stays suspended until attached to a non-breakaway job.
Closing the last job handle kills its processes, including on owner death.
"""
import ctypes as c
from ctypes import wintypes as w


class BasicLimits(c.Structure):
    _fields_ = [("PerProcessUserTimeLimit", c.c_int64), ("PerJobUserTimeLimit", c.c_int64),
                ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", c.c_size_t),
                ("MaximumWorkingSetSize", c.c_size_t), ("ActiveProcessLimit", w.DWORD),
                ("Affinity", c.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]


class IOCounts(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class ExtendedLimits(c.Structure):
    _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IOCounts),
                ("ProcessMemoryLimit", c.c_size_t), ("JobMemoryLimit", c.c_size_t),
                ("PeakProcessMemoryUsed", c.c_size_t), ("PeakJobMemoryUsed", c.c_size_t)]


class ThreadEntry(c.Structure):
    _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ThreadID", w.DWORD),
                ("th32OwnerProcessID", w.DWORD), ("tpBasePri", w.LONG),
                ("tpDeltaPri", w.LONG), ("dwFlags", w.DWORD)]


class Job:
    def __init__(self):
        self.k = c.WinDLL("kernel32", use_last_error=True)
        declarations = {
            "CreateJobObjectW": ([c.c_void_p, w.LPCWSTR], w.HANDLE),
            "SetInformationJobObject": ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD], w.BOOL),
            "AssignProcessToJobObject": ([w.HANDLE, w.HANDLE], w.BOOL),
            "TerminateJobObject": ([w.HANDLE, w.UINT], w.BOOL),
            "CloseHandle": ([w.HANDLE], w.BOOL),
            "CreateToolhelp32Snapshot": ([w.DWORD, w.DWORD], w.HANDLE),
            "Thread32First": ([w.HANDLE, c.POINTER(ThreadEntry)], w.BOOL),
            "Thread32Next": ([w.HANDLE, c.POINTER(ThreadEntry)], w.BOOL),
            "OpenThread": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "ResumeThread": ([w.HANDLE], w.DWORD),
        }
        for name, (args, result) in declarations.items():
            function = getattr(self.k, name); function.argtypes = args; function.restype = result
        self.handle = self.k.CreateJobObjectW(None, None)
        if not self.handle:
            raise c.WinError(c.get_last_error())
        limits = ExtendedLimits(); limits.BasicLimitInformation.LimitFlags = 0x2000
        if not self.k.SetInformationJobObject(self.handle, 9, c.byref(limits), c.sizeof(limits)):
            self.close(); raise c.WinError(c.get_last_error())

    def attach_and_resume(self, process):
        if not self.k.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise c.WinError(c.get_last_error())
        snapshot = self.k.CreateToolhelp32Snapshot(4, 0)
        if snapshot == c.c_void_p(-1).value:
            raise c.WinError(c.get_last_error())
        resumed = 0
        try:
            entry = ThreadEntry(); entry.dwSize = c.sizeof(entry)
            present = self.k.Thread32First(snapshot, c.byref(entry))
            while present:
                if entry.th32OwnerProcessID == process.pid:
                    thread = self.k.OpenThread(2, False, entry.th32ThreadID)
                    if not thread:
                        raise c.WinError(c.get_last_error())
                    try:
                        if self.k.ResumeThread(thread) == 0xFFFFFFFF:
                            raise c.WinError(c.get_last_error())
                        resumed += 1
                    finally:
                        self.k.CloseHandle(thread)
                present = self.k.Thread32Next(snapshot, c.byref(entry))
        finally:
            self.k.CloseHandle(snapshot)
        if not resumed:
            raise OSError("suspended process thread unavailable")

    def terminate(self):
        if self.handle and not self.k.TerminateJobObject(self.handle, 125):
            raise c.WinError(c.get_last_error())

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None
