"""Bounded streams and OS-owned process trees, including owner interruption."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import threading
import time

from .errors import AcceptorError
from .backend import require_backend

# Only the POSIX guardian inherits this lock descriptor; application code does not.
IDENTITY_LEASE = ContextVar("acceptor_identity_lease", default=None)


@dataclass
class BoundedResult:
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    stdout_truncated: bool
    stderr_truncated: bool
    timed_out: bool
    duration_ms: int


class _Owner:
    def __init__(self, argv, input_bytes, env, cwd, deadline):
        self.proc = None
        self.job = None
        self.linux_control = None
        self.linux_status = None
        self.application_returncode = None
        self.closed = False
        kwargs = dict(stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=str(cwd), bufsize=0)
        ready_read = status_write = None
        try:
            if os.name == "nt":
                from .windows_job import Job
                self.job = Job()
                self.proc = self.job.spawn(argv, input_bytes, env, cwd)
            elif sys.platform == "linux":
                ready_read, self.linux_control = os.pipe()
                status_read, status_write = os.pipe()
                self.linux_status = os.fdopen(status_read, "rb", buffering=0)
                lease = IDENTITY_LEASE.get()
                fds = (ready_read, status_write) + (() if lease is None else (lease,))
                self.proc = subprocess.Popen([sys.executable, "-I", str(Path(__file__).with_name("_linux_guard.py")), str(ready_read), str(status_write), json.dumps(argv)],
                    start_new_session=True, pass_fds=fds, **kwargs)
                os.close(ready_read); ready_read = None
                os.close(status_write); status_write = None
                with selectors.DefaultSelector() as selector:
                    selector.register(self.linux_status, selectors.EVENT_READ)
                    if not selector.select(5) or self.linux_status.readline(128) != b"READY\n":
                        raise OSError("subreaper unavailable")
            else:
                raise AcceptorError('EXECUTION_CONTAINMENT_UNAVAILABLE')
        except BaseException:
            try:
                self.stop()
            finally:
                if self.proc is not None:
                    for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
                        if stream is not None:
                            stream.close()
            raise
        finally:
            for fd in (ready_read, status_write):
                if fd is not None:
                    os.close(fd)

    def poll(self):
        if self.linux_status is not None:
            with selectors.DefaultSelector() as selector:
                selector.register(self.linux_status, selectors.EVENT_READ)
                if selector.select(0):
                    line = self.linux_status.readline(128)
                    if line.startswith(b"EXIT "):
                        self.application_returncode = int(line[5:])
            return self.application_returncode
        return self.proc.poll()

    def stop(self):
        if self.closed:
            return
        self.closed = True
        failure = False
        if self.linux_control is not None:
            os.close(self.linux_control); self.linux_control = None
            try:
                if self.proc is None:
                    failure = True
                else:
                    if self.proc.wait(timeout=4) != 0:
                        failure = True
                    lines = self.linux_status.read(256).splitlines()
                    if not lines or lines[-1] != b"CLEAN":
                        failure = True
            except (OSError, subprocess.TimeoutExpired):
                failure = True
            finally:
                self.linux_status.close()
        if self.job is not None:
            try:
                self.job.terminate()
            except OSError:
                failure = True
            finally:
                self.job.close()
        if self.proc is not None:
            # Failed supervisor setup is an error, never a successful cleanup.
            try:
                if os.name == "posix" and self.proc.poll() is None:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                elif os.name == "nt" and self.proc.poll() is None:
                    self.proc.kill()
            except ProcessLookupError:
                pass
            except OSError:
                failure = True
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                failure = True
            finally:
                if self.job is not None:
                    self.proc.close()
        if failure:
            raise AcceptorError("CLEANUP_FAILED")


def run_bounded(argv, *, input_bytes, timeout_seconds, max_stdout, max_stderr, env, cwd):
    require_backend()
    start = time.monotonic()
    deadline = start + timeout_seconds
    owner = _Owner(argv, input_bytes, env, cwd, deadline)
    proc = owner.proc
    buffers = [bytearray(), bytearray()]
    limits = [max_stdout, max_stderr]
    overflow = [False, False]
    readers = []
    feeder = None
    timed_out = False
    result_code = None

    def read(stream, index):
        try:
            while True:
                data = os.read(stream.fileno(), min(65536, max(1, limits[index] + 1 - len(buffers[index]))))
                if not data:
                    break
                buffers[index].extend(data)
                if len(buffers[index]) > limits[index]:
                    overflow[index] = True
                    break
        except (OSError, ValueError):
            pass

    def feed():
        try:
            view = memoryview(input_bytes)
            while view:
                count = os.write(proc.stdin.fileno(), view)
                view = view[count:]
        except (BrokenPipeError, OSError, ValueError):
            pass
        finally:
            proc.stdin.close()

    try:
        for index, stream in enumerate((proc.stdout, proc.stderr)):
            thread = threading.Thread(target=read, args=(stream, index), daemon=True)
            readers.append(thread); thread.start()
        if input_bytes is not None:
            feeder = threading.Thread(target=feed, daemon=True); feeder.start()
        while True:
            if any(overflow):
                break
            result_code = owner.poll()
            if result_code is not None and not any(t.is_alive() for t in readers):
                break
            if time.monotonic() >= deadline:
                timed_out = True
                break
            time.sleep(min(0.005, max(0, deadline - time.monotonic())))
    finally:
        # Always terminate residual descendants, even after a successful parent
        # with redirected pipes. The guardian keeps the identity lock on owner death.
        try:
            owner.stop()
        finally:
            for thread in readers:
                thread.join(timeout=1)
            if feeder is not None:
                feeder.join(timeout=1)
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()  # unbuffered FileIO: no buffered-reader lock
            if any(t.is_alive() for t in readers) or (feeder is not None and feeder.is_alive()):
                raise AcceptorError("CLEANUP_FAILED")
    if result_code is None:
        result_code = proc.returncode
    return BoundedResult(None if timed_out else result_code, bytes(buffers[0]), bytes(buffers[1]),
                         overflow[0], overflow[1], timed_out, int((time.monotonic() - start) * 1000))


def scrubbed_env(extra: dict[str, str]) -> dict[str, str]:
    """Build scrubbed child environment with only minimal platform facts."""
    env: dict[str, str] = {}
    # Minimal PATH.
    if os.name == "nt":
        # Inherit minimal Windows bootstrap facts.
        for key in ("PATH", "SystemRoot", "windir", "TMP", "TEMP"):
            if key in os.environ:
                env[key] = os.environ[key]
        # Ensure PATH exists.
        if "PATH" not in env:
            env["PATH"] = os.environ.get("PATH", "")
        if "SystemRoot" not in env:
            env["SystemRoot"] = os.environ.get("SystemRoot", r"C:\Windows")
    else:
        env["PATH"] = os.environ.get("PATH", "/usr/bin:/bin")
        env["LANG"] = "C.UTF-8"
    # Fixed acceptance facts.
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PIP_NO_INDEX"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    if os.name == "nt":
        env["GIT_CONFIG_GLOBAL"] = "NUL"
    else:
        env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    env.update(extra)
    # Defensive: never propagate credentials or repo roots.
    for key in list(env.keys()):
        upper = key.upper()
        if any(token in upper for token in ("AWS_", "GITHUB_", "GITLAB_", "AZURE_", "GOOGLE_", "OPENAI_", "ANTHROPIC_")):
            # Only remove known credential prefixes if they were inherited;
            # explicit `extra` keys are controlled by us (CAPY_*, HOME, etc.).
            if key not in extra:
                del env[key]
    for key in ("CAPY_RUNTIME_ROOT", "DEVELOPER_ROOT", "CAPY_ROOT", "GITHUB_TOKEN", "GH_TOKEN"):
        if key in env and key not in extra:
            del env[key]
    return env
