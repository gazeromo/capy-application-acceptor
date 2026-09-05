"""Linux subreaper owns even double-forked or detached descendants.

Only the owner control/status descriptors and optional identity lease reach
this trusted helper. The application inherits only its three standard streams.
"""
import ctypes
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time


def cleanup(child):
    deadline=time.monotonic()+2
    child.poll()
    children=Path('/proc/self/task')/str(os.getpid())/'children'
    while True:
        # Only this single-threaded helper reaps, so an unreaped child's PID
        # cannot be reused between listing it and sending its termination signal.
        for pid in map(int,children.read_text().split()):
            try:os.kill(pid,signal.SIGKILL)
            except ProcessLookupError:pass
        while True:
            try:pid,status=os.waitpid(-1,os.WNOHANG)
            except ChildProcessError:
                if child.returncode is None:child.returncode=125
                return True
            if not pid:break
            if pid==child.pid:child.returncode=os.waitstatus_to_exitcode(status)
        if time.monotonic()>=deadline:return False
        time.sleep(.005)


def main():
    control,status=int(sys.argv[1]),int(sys.argv[2])
    libc=ctypes.CDLL(None,use_errno=True)
    libc.prctl.argtypes=[ctypes.c_int,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_ulong]
    libc.prctl.restype=ctypes.c_int
    if libc.prctl(36,1,0,0,0)!=0:raise OSError(ctypes.get_errno(),'subreaper unavailable')
    child=subprocess.Popen(json.loads(sys.argv[3]),stdin=0,stdout=1,stderr=2,close_fds=True,start_new_session=True)
    os.write(status,b'READY\n')
    reported=False
    with selectors.DefaultSelector() as selector:
        selector.register(control,selectors.EVENT_READ)
        try:
            while True:
                if selector.select(.005) and not os.read(control,1):break
                code=child.poll()
                if code is not None and not reported:
                    os.write(status,('EXIT '+str(code)+'\n').encode())
                    # Actual descendants determine whether streams remain open.
                    for fd in (0,1,2):os.close(fd)
                    reported=True
        finally:
            clean=cleanup(child)
            os.write(status,b'CLEAN\n' if clean else b'FAILED\n')
    return 0 if clean else 125


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,subprocess.SubprocessError):raise SystemExit(125)
