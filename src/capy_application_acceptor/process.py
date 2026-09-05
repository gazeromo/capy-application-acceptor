"""Bounded subprocess with wall-time and output limits, portable tree reaping."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass


@dataclass
class BoundedResult:
    exit_code: int | None  # None on timeout/kill
    stdout: bytes  # bounded prefix (up to limit+1 to detect overflow)
    stderr: bytes
    stdout_truncated: bool  # True when limit exceeded
    stderr_truncated: bool
    timed_out: bool
    duration_ms: int


def _kill_tree(proc: subprocess.Popen):
    try:
        if os.name == "posix":
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    proc.kill()
                except OSError:
                    pass
        else:
            proc.kill()
    except OSError:
        pass


def run_bounded(
    argv: list[str],
    *,
    input_bytes: bytes | None,
    timeout_seconds: float,
    max_stdout: int,
    max_stderr: int,
    env: dict[str, str],
    cwd,
) -> BoundedResult:
    """Run child with bounded wall time and bounded stdout/stderr while reading.

    Reads incrementally; terminates and reaps the child tree on timeout or
    when either stream exceeds its limit. Never captures unbounded output.
    """
    start = time.monotonic()
    # start_new_session detaches process group for portable tree kill on posix.
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE if input_bytes is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=str(cwd),
            start_new_session=(os.name == "posix"),
        )
    except OSError as e:
        raise e
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    stdout_len = 0
    stderr_len = 0
    stdout_over = False
    stderr_over = False
    timed_out = False
    # Feed stdin in a thread to avoid deadlock with large inputs (inputs are small).
    stdin_error = None

    def _feed():
        nonlocal stdin_error
        try:
            if input_bytes is not None and proc.stdin is not None:
                # Write in chunks; stdin sizes are bounded (request ≤64KiB).
                proc.stdin.write(input_bytes)
                proc.stdin.close()
            elif proc.stdin is not None:
                proc.stdin.close()
        except (BrokenPipeError, OSError) as e:
            stdin_error = e
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
            except OSError:
                pass

    feeder = threading.Thread(target=_feed, daemon=True)
    feeder.start()

    # Reader threads for stdout/stderr with bounds.
    def _read_stream(stream, chunks: list, kind: str):
        nonlocal stdout_len, stderr_len, stdout_over, stderr_over
        try:
            while True:
                part = stream.read(65536)
                if not part:
                    break
                if kind == "out":
                    if stdout_len + len(part) > max_stdout:
                        # Keep one byte over to signal overflow, then stop.
                        need = max_stdout + 1 - stdout_len
                        chunks.append(part[: max(need, 0)])
                        stdout_len += len(chunks[-1])
                        stdout_over = True
                        break
                    chunks.append(part)
                    stdout_len += len(part)
                else:
                    if stderr_len + len(part) > max_stderr:
                        need = max_stderr + 1 - stderr_len
                        chunks.append(part[: max(need, 0)])
                        stderr_len += len(chunks[-1])
                        stderr_over = True
                        break
                    chunks.append(part)
                    stderr_len += len(part)
        except OSError:
            pass
        finally:
            try:
                stream.close()
            except OSError:
                pass

    t_out = threading.Thread(target=_read_stream, args=(proc.stdout, stdout_chunks, "out"), daemon=True)
    t_err = threading.Thread(target=_read_stream, args=(proc.stderr, stderr_chunks, "err"), daemon=True)
    assert proc.stdout is not None and proc.stderr is not None
    t_out.start()
    t_err.start()

    deadline = start + timeout_seconds
    exit_code = None
    # Poll loop: enforce timeout and output limits.
    while True:
        now = time.monotonic()
        remaining = deadline - now
        rc = proc.poll()
        # If output overflow detected, kill promptly.
        if stdout_over or stderr_over:
            _kill_tree(proc)
            # Drain: wait briefly for readers to finish (they already broke).
            break
        if rc is not None:
            exit_code = rc
            break
        if remaining <= 0:
            timed_out = True
            _kill_tree(proc)
            break
        # Sleep briefly (bounded).
        time.sleep(min(0.02, max(remaining, 0.001)))
    # Ensure process reaped.
    try:
        # Give a short grace after kill, then wait.
        proc.wait(timeout=5)
        if timed_out and exit_code is None:
            exit_code = proc.returncode
        elif exit_code is None:
            exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        if timed_out:
            exit_code = None
        else:
            exit_code = proc.returncode if proc.returncode is not None else None
    # If we killed for overflow, mark timed_out False; exit_code is whatever reaped.
    # Join readers (bounded).
    t_out.join(timeout=5)
    t_err.join(timeout=5)
    feeder.join(timeout=5)
    # Close pipes defensively.
    for stream in (proc.stdout, proc.stderr):
        try:
            if stream is not None:
                stream.close()
        except OSError:
            pass
    try:
        if proc.stdin is not None:
            proc.stdin.close()
    except OSError:
        pass
    stdout_data = b"".join(stdout_chunks)
    stderr_data = b"".join(stderr_chunks)
    # If overflow killed, ensure flags set even if race.
    if len(stdout_data) > max_stdout:
        stdout_over = True
        stdout_data = stdout_data[: max_stdout + 1]
    if len(stderr_data) > max_stderr:
        stderr_over = True
        stderr_data = stderr_data[: max_stderr + 1]
    duration_ms = int((time.monotonic() - start) * 1000)
    if timed_out:
        exit_code = None
    return BoundedResult(
        exit_code=exit_code,
        stdout=stdout_data,
        stderr=stderr_data,
        stdout_truncated=stdout_over,
        stderr_truncated=stderr_over,
        timed_out=timed_out,
        duration_ms=duration_ms,
    )


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
