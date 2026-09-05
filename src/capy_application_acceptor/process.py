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
        self.guard = None
        self.job = None
        self.closed = False
        kwargs = dict(stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=str(cwd), bufsize=0)
        ready_read = ready_write = None
        try:
            if os.name == "nt":
                from .windows_job import Job
                self.job = Job()
                # CREATE_SUSPENDED: no application instructions before job assignment.
                self.proc = subprocess.Popen(argv, creationflags=0x4 | 0x200, **kwargs)
                self.job.attach_and_resume(self.proc)
            else:
                ready_read, ready_write = os.pipe()
                launcher = str(Path(__file__).with_name("_process_launch.py"))
                self.proc = subprocess.Popen([sys.executable, "-I", launcher, str(ready_read), json.dumps(argv)],
                                             start_new_session=True, pass_fds=(ready_read,), **kwargs)
                os.close(ready_read); ready_read = None
                lease = IDENTITY_LEASE.get()
                fds = () if lease is None else (lease,)
                self.guard = subprocess.Popen([sys.executable, "-I", str(Path(__file__).with_name("_process_guard.py")), str(self.proc.pid)],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    env=env, cwd=str(cwd), bufsize=0, start_new_session=True, pass_fds=fds)
                with selectors.DefaultSelector() as selector:
                    selector.register(self.guard.stdout, selectors.EVENT_READ)
                    if not selector.select(max(0, min(5, deadline - time.monotonic()))) or self.guard.stdout.readline() != b"READY\n":
                        raise OSError("process guardian unavailable")
                os.write(ready_write, b"1")
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
            for fd in (ready_read, ready_write):
                if fd is not None:
                    os.close(fd)

    def stop(self):
        if self.closed:
            return
        self.closed = True
        failure = False
        if self.job is not None:
            try:
                self.job.terminate()
            except OSError:
                failure = True
            finally:
                self.job.close()
        if self.guard is not None:
            try:
                self.guard.stdin.close()
                if self.guard.wait(timeout=4) != 0:
                    failure = True
            except (OSError, subprocess.TimeoutExpired):
                failure = True
                self.guard.kill()
                self.guard.wait(timeout=2)
            finally:
                self.guard.stdout.close()
        if self.proc is not None:
            # Also closes the unstarted launch gate case if guard creation failed.
            try:
                if os.name == "posix" and (self.guard is None or failure) and self.proc.poll() is None:
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
        if failure:
            raise AcceptorError("CLEANUP_FAILED")


def run_bounded(argv, *, input_bytes, timeout_seconds, max_stdout, max_stderr, env, cwd):
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
            result_code = proc.poll()
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
