"""Atomic Windows Job assignment using documented STARTUPINFOEX Job/handle lists.
No application process exists outside its KILL_ON_JOB_CLOSE job (Windows 10+).
"""
import ctypes as c
from ctypes import wintypes as w
import os
import subprocess
import time

class BasicLimits(c.Structure):
    _fields_=[('PerProcessUserTimeLimit',c.c_int64),('PerJobUserTimeLimit',c.c_int64),('LimitFlags',w.DWORD),('MinimumWorkingSetSize',c.c_size_t),('MaximumWorkingSetSize',c.c_size_t),('ActiveProcessLimit',w.DWORD),('Affinity',c.c_size_t),('PriorityClass',w.DWORD),('SchedulingClass',w.DWORD)]
class IOCounts(c.Structure):
    _fields_=[(n,c.c_uint64) for n in ('ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]
class ExtendedLimits(c.Structure):
    _fields_=[('BasicLimitInformation',BasicLimits),('IoInfo',IOCounts),*[(n,c.c_size_t) for n in ('ProcessMemoryLimit','JobMemoryLimit','PeakProcessMemoryUsed','PeakJobMemoryUsed')]]
class Accounting(c.Structure):
    _fields_=[(n,c.c_int64) for n in ('TotalUserTime','TotalKernelTime','ThisPeriodTotalUserTime','ThisPeriodTotalKernelTime')]+[(n,w.DWORD) for n in ('TotalPageFaultCount','TotalProcesses','ActiveProcesses','TotalTerminatedProcesses')]
class CompletionPort(c.Structure):
    _fields_=[('CompletionKey',c.c_void_p),('CompletionPort',w.HANDLE)]
class Startup(c.Structure):
    _fields_=[('cb',w.DWORD),('lpReserved',w.LPWSTR),('lpDesktop',w.LPWSTR),('lpTitle',w.LPWSTR),*[(n,w.DWORD) for n in ('dwX','dwY','dwXSize','dwYSize','dwXCountChars','dwYCountChars','dwFillAttribute','dwFlags')],('wShowWindow',w.WORD),('cbReserved2',w.WORD),('lpReserved2',c.c_void_p),('hStdInput',w.HANDLE),('hStdOutput',w.HANDLE),('hStdError',w.HANDLE)]
class StartupEx(c.Structure):
    _fields_=[('StartupInfo',Startup),('lpAttributeList',c.c_void_p)]
class ProcessInfo(c.Structure):
    _fields_=[('hProcess',w.HANDLE),('hThread',w.HANDLE),('dwProcessId',w.DWORD),('dwThreadId',w.DWORD)]

class NativeProcess:
    def __init__(self,k,info,stdin,stdout,stderr):
        self.k=k;self.handle=info.hProcess;self.pid=info.dwProcessId
        self.stdin=stdin;self.stdout=stdout;self.stderr=stderr;self.returncode=None
    def poll(self):
        if self.returncode is not None:return self.returncode
        result=self.k.WaitForSingleObject(self.handle,0)
        if result==258:return None
        if result!=0:raise c.WinError(c.get_last_error())
        code=w.DWORD()
        if not self.k.GetExitCodeProcess(self.handle,c.byref(code)):raise c.WinError(c.get_last_error())
        self.returncode=int(code.value);return self.returncode
    def wait(self,timeout=None):
        if self.returncode is not None:return self.returncode
        result=self.k.WaitForSingleObject(self.handle,0xFFFFFFFF if timeout is None else max(0,int(timeout*1000)))
        if result==258:raise subprocess.TimeoutExpired('owned-child',timeout)
        return self.poll()
    def kill(self):
        if self.poll() is None and not self.k.TerminateProcess(self.handle,125):raise c.WinError(c.get_last_error())
    def close(self):
        if self.handle:self.k.CloseHandle(self.handle);self.handle=None

class Job:
    def __init__(self):
        self.k=c.WinDLL('kernel32',use_last_error=True)
        declarations={
            'CreateJobObjectW':([c.c_void_p,w.LPCWSTR],w.HANDLE),
            'SetInformationJobObject':([w.HANDLE,c.c_int,c.c_void_p,w.DWORD],w.BOOL),
            'QueryInformationJobObject':([w.HANDLE,c.c_int,c.c_void_p,w.DWORD,c.c_void_p],w.BOOL),
            'TerminateJobObject':([w.HANDLE,w.UINT],w.BOOL),'CloseHandle':([w.HANDLE],w.BOOL),
            'InitializeProcThreadAttributeList':([c.c_void_p,w.DWORD,w.DWORD,c.POINTER(c.c_size_t)],w.BOOL),
            'UpdateProcThreadAttribute':([c.c_void_p,w.DWORD,c.c_size_t,c.c_void_p,c.c_size_t,c.c_void_p,c.c_void_p],w.BOOL),
            'DeleteProcThreadAttributeList':([c.c_void_p],None),
            'CreateProcessW':([w.LPCWSTR,w.LPWSTR,c.c_void_p,c.c_void_p,w.BOOL,w.DWORD,c.c_void_p,w.LPCWSTR,c.POINTER(StartupEx),c.POINTER(ProcessInfo)],w.BOOL),
            'WaitForSingleObject':([w.HANDLE,w.DWORD],w.DWORD),'GetExitCodeProcess':([w.HANDLE,c.POINTER(w.DWORD)],w.BOOL),
            'TerminateProcess':([w.HANDLE,w.UINT],w.BOOL)}
        declarations.update({
            'CreateIoCompletionPort':([w.HANDLE,w.HANDLE,c.c_size_t,w.DWORD],w.HANDLE),
            'GetQueuedCompletionStatus':([w.HANDLE,c.POINTER(w.DWORD),c.POINTER(c.c_size_t),c.POINTER(c.c_void_p),w.DWORD],w.BOOL),
            'OpenProcess':([w.DWORD,w.BOOL,w.DWORD],w.HANDLE),
            'IsProcessInJob':([w.HANDLE,w.HANDLE,c.POINTER(w.BOOL)],w.BOOL)})
        for name,(args,result) in declarations.items():
            f=getattr(self.k,name);f.argtypes=args;f.restype=result
        self.handle=self.k.CreateJobObjectW(None,None)
        if not self.handle:raise c.WinError(c.get_last_error())
        self.port=None;self.process_handles=[];self.process_notifications=0
        limits=ExtendedLimits();limits.BasicLimitInformation.LimitFlags=0x2000
        if not self.k.SetInformationJobObject(self.handle,9,c.byref(limits),c.sizeof(limits)):
            error=c.WinError(c.get_last_error());self.close();raise error
        # Associate while inactive, before even the first application can start.
        self.port=self.k.CreateIoCompletionPort(w.HANDLE(-1),None,0,1)
        if not self.port:
            error=c.WinError(c.get_last_error());self.close();raise error
        association=CompletionPort(1,self.port)
        if not self.k.SetInformationJobObject(self.handle,7,c.byref(association),c.sizeof(association)):
            error=c.WinError(c.get_last_error());self.close();raise error
    def spawn(self,argv,input_bytes,env,cwd):
        import msvcrt
        fds=[];initialized=False;info=ProcessInfo()
        try:
            if input_bytes is None:
                child_in=os.open(os.devnull,os.O_RDONLY);parent_in=None;fds.append(child_in)
            else:
                child_in,parent_in=os.pipe();fds.extend((child_in,parent_in))
            parent_out,child_out=os.pipe();parent_err,child_err=os.pipe();fds.extend((parent_out,child_out,parent_err,child_err))
            for fd in (child_in,child_out,child_err):os.set_inheritable(fd,True)
            handles=(w.HANDLE*3)(*(msvcrt.get_osfhandle(fd) for fd in (child_in,child_out,child_err)))
            jobs=(w.HANDLE*1)(self.handle)
            size=c.c_size_t();self.k.InitializeProcThreadAttributeList(None,2,0,c.byref(size))
            attribute=c.create_string_buffer(size.value)
            if not self.k.InitializeProcThreadAttributeList(attribute,2,0,c.byref(size)):raise c.WinError(c.get_last_error())
            initialized=True
            for key,value in ((0x20002,handles),(0x2000D,jobs)):
                if not self.k.UpdateProcThreadAttribute(attribute,0,key,c.byref(value),c.sizeof(value),None,None):raise c.WinError(c.get_last_error())
            startup=StartupEx();startup.StartupInfo.cb=c.sizeof(startup);startup.lpAttributeList=c.cast(attribute,c.c_void_p)
            startup.StartupInfo.dwFlags=0x100
            startup.StartupInfo.hStdInput,startup.StartupInfo.hStdOutput,startup.StartupInfo.hStdError=handles
            command=c.create_unicode_buffer(subprocess.list2cmdline(argv))
            environment=c.create_unicode_buffer('\0'.join(k+'='+v for k,v in sorted(env.items(),key=lambda p:p[0].upper()))+'\0\0')
            # Job membership is assigned atomically inside CreateProcessW.
            if not self.k.CreateProcessW(str(argv[0]),command,None,None,True,0x80000|0x400|0x200,environment,str(cwd),c.byref(startup),c.byref(info)):
                raise c.WinError(c.get_last_error())
            self.k.CloseHandle(info.hThread);info.hThread=None
            for fd in (child_in,child_out,child_err):os.close(fd);fds.remove(fd)
            stdin=os.fdopen(parent_in,'wb',buffering=0) if parent_in is not None else None
            stdout=os.fdopen(parent_out,'rb',buffering=0);stderr=os.fdopen(parent_err,'rb',buffering=0)
            fds.clear()
            return NativeProcess(self.k,info,stdin,stdout,stderr)
        except BaseException:
            if info.hProcess:
                self.k.TerminateProcess(info.hProcess,125);self.k.CloseHandle(info.hProcess)
            if info.hThread:self.k.CloseHandle(info.hThread)
            raise
        finally:
            if initialized:self.k.DeleteProcThreadAttributeList(attribute)
            for fd in fds:os.close(fd)
    def collect_process(self,timeout_ms):
        message=w.DWORD();key=c.c_size_t();pid=c.c_void_p()
        if not self.k.GetQueuedCompletionStatus(self.port,c.byref(message),c.byref(key),c.byref(pid),timeout_ms):
            error=c.get_last_error()
            if error==258:return False
            raise c.WinError(error)
        if key.value!=1:raise OSError('unexpected job notification')
        if message.value==6:  # JOB_OBJECT_MSG_NEW_PROCESS
            if not pid.value:raise OSError('invalid job process identifier')
            self.process_notifications+=1
            handle=self.k.OpenProcess(0x100000|0x1000,False,pid.value)
            if not handle:
                error=c.get_last_error()
                if error==87:return True  # PID no longer exists: process object gone.
                raise c.WinError(error)
            owned=w.BOOL()
            if not self.k.IsProcessInJob(handle,self.handle,c.byref(owned)):
                error=c.WinError(c.get_last_error());self.k.CloseHandle(handle);raise error
            if owned.value:self.process_handles.append(handle)
            else:self.k.CloseHandle(handle)  # Recycled PID; original is already gone.
        return True

    def terminate(self):
        if not self.handle:return
        deadline=time.monotonic()+2
        if self.port:
            while self.collect_process(0):
                if time.monotonic()>=deadline:raise OSError('job notification deadline')
        if not self.k.TerminateJobObject(self.handle,125):raise c.WinError(c.get_last_error())
        while True:
            facts=Accounting()
            if not self.k.QueryInformationJobObject(self.handle,1,c.byref(facts),c.sizeof(facts),None):raise c.WinError(c.get_last_error())
            # Accounting can reach zero before process objects are signaled.
            # Notifications may be lost: missing any start withholds cleanup.
            if facts.ActiveProcesses==0 and self.process_notifications==facts.TotalProcesses:
                for handle in self.process_handles:
                    remaining=max(0,int((deadline-time.monotonic())*1000))
                    if self.k.WaitForSingleObject(handle,remaining)!=0:raise OSError('process cleanup unconfirmed')
                return
            if time.monotonic()>=deadline:raise OSError('job cleanup deadline')
            if not self.port:raise OSError('job notifications unavailable')
            self.collect_process(10)
    def close(self):
        if self.handle:self.k.CloseHandle(self.handle);self.handle=None
        if self.port:self.k.CloseHandle(self.port);self.port=None
        for handle in self.process_handles:self.k.CloseHandle(handle)
        self.process_handles.clear()
