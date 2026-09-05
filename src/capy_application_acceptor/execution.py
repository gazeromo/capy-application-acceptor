"""Bounded offline case execution with fresh venv per case."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

from . import codec
from .comparison import parse_failure_stderr, parse_success_envelope
from .constants import ENV_SETUP_TIMEOUT
from .errors import AcceptorError
from .process import run_bounded, scrubbed_env
from .scan import contains_secret


def _env_unavailable(msg: str = "") -> AcceptorError:
    return AcceptorError("EXECUTION_ENVIRONMENT_UNAVAILABLE", "environment")


def write_app_copy(application_members: dict[str, bytes], app_dir: Path):
    app_dir.mkdir(parents=True, exist_ok=False)
    for name, data in application_members.items():
        # Names already validated; still guard traversal.
        if ".." in Path(name).parts or name.startswith("/") or "\\" in name:
            raise _env_unavailable()
        dest = app_dir / name
        # Ensure parent within app_dir.
        try:
            dest.relative_to(app_dir)
        except ValueError:
            raise _env_unavailable()
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Refuse to overwrite (unique names).
        if dest.exists():
            raise _env_unavailable()
        dest.write_bytes(data)


def project_resources(*, descriptor: dict, case: dict, profile_members: dict, resources_dir: Path):
    resources_dir.mkdir(parents=True, exist_ok=False)
    rules = {item["name"]: item for item in descriptor.get("resources", [])}
    projected: list[dict] = []
    for index, entry in enumerate(case.get("resources", [])):
        slot = entry["slot"]
        filename = entry["filename"]
        member = entry["member"]
        expected_sha = entry["sha256"]
        data = profile_members.get(member)
        if data is None:
            raise AcceptorError("ACCEPTANCE_PROFILE_INTEGRITY_FAILED", "profile")
        if hashlib.sha256(data).hexdigest() != expected_sha:
            raise AcceptorError("ACCEPTANCE_PROFILE_INTEGRITY_FAILED", "profile")
        # Safe copied file.
        if not codec.is_safe_basename(filename):
            raise AcceptorError("ACCEPTANCE_PROFILE_INTEGRITY_FAILED", "profile")
        dest = resources_dir / f"resource-{index}-{filename}"
        dest.write_bytes(data)
        # Verify digest after copy.
        if hashlib.sha256(dest.read_bytes()).hexdigest() != expected_sha:
            raise _env_unavailable()
        projected.append({"slot": slot, "filename": filename, "digest": expected_sha, "path": str(dest)})
    slots_sorted = sorted(rules.keys())
    return projected, slots_sorted


def ensure_venv(venv_dir: Path, *, setup_env: dict) -> Path:
    # Create venv with bundled ensurepip (offline).
    res = run_bounded(
        [sys.executable, "-m", "venv", str(venv_dir)],
        input_bytes=None,
        timeout_seconds=ENV_SETUP_TIMEOUT,
        max_stdout=1024 * 1024,
        max_stderr=1024 * 1024,
        env=setup_env,
        cwd=venv_dir.parent,
    )
    if res.timed_out or res.exit_code != 0:
        raise _env_unavailable()
    if os.name == "nt":
        py = venv_dir / "Scripts" / "python.exe"
    else:
        py = venv_dir / "bin" / "python"
    if not py.is_file():
        raise _env_unavailable()
    return py


def pip_install_wheel(*, venv_python: Path, wheel_path: Path, setup_env: dict):
    res = run_bounded(
        [str(venv_python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel_path)],
        input_bytes=None,
        timeout_seconds=ENV_SETUP_TIMEOUT,
        max_stdout=1024 * 1024,
        max_stderr=1024 * 1024,
        env=setup_env,
        cwd=wheel_path.parent,
    )
    if res.timed_out or res.exit_code != 0:
        raise _env_unavailable()


def collect_artifacts(output_dir: Path, max_total_bytes: int | None = None):
    """Collect output files safely. Returns (artifacts list, anomaly flag).

    Every extra/undeclared output, dotfile, unsafe name, directory, or
    symlink is reported via a non-None anomaly so callers reject. Unsafe
    names are never returned in the artifact list (not projected). Reads
    are incremental and bounded by the aggregate limit (+1 to detect
    overflow) without ever retaining unbounded files.
    """
    from .constants import LIMIT_CEILINGS

    artifacts: list[tuple[str, bytes]] = []
    anomaly = None
    try:
        entries = list(output_dir.iterdir())
    except OSError:
        return [], "missing-output"
    budget = (max_total_bytes if max_total_bytes is not None else LIMIT_CEILINGS["max_total_artifact_bytes"]) + 1
    if budget < 0:
        budget = 0
    total = 0
    for entry in sorted(entries, key=lambda e: e.name):
        # Dotfiles are extra/undeclared outputs and must be rejected;
        # they are never projected.
        if entry.name.startswith("."):
            try:
                # Record anomaly even if it is a symlink/dir; do not expose.
                anomaly = "dotfile"
            except OSError:
                anomaly = "dotfile"
            continue
        try:
            if entry.is_symlink():
                anomaly = "symlink"
                continue
            if not entry.is_file():
                anomaly = "non-file"
                continue
            # Unsafe names are not projected (spec) but must be rejected.
            if not codec.is_safe_basename(entry.name):
                anomaly = "unsafe-name"
                continue
            # Path escaping already prevented (we only list direct children).
            # Incremental bounded read enforcing the aggregate budget.
            if total >= budget:
                # Budget already exhausted: further safe files are beyond the
                # retained prefix and only extend the overflow. Skip retention
                # while still reporting anomalies for non-safe names above.
                continue
            chunks: list[bytes] = []
            try:
                with open(entry, "rb") as f:
                    while True:
                        remaining = budget - total
                        if remaining <= 0:
                            break
                        part = f.read(min(65536, remaining))
                        if not part:
                            break
                        chunks.append(part)
                        total += len(part)
                        if total >= budget:
                            # Budget exhausted (limit+1 retained); discard
                            # the remainder without further allocation.
                            break
            except OSError:
                anomaly = "read-error"
                continue
            data = b"".join(chunks)
            artifacts.append((entry.name, data))
        except OSError:
            anomaly = "read-error"
            continue
    # Duplicate check: names unique by construction (filesystem).
    return artifacts, anomaly


def run_one_case(
    *,
    candidate,
    profile,
    case: dict,
    case_order: int,
    work_case: Path,
    wheel_path: Path,
    per_case_timeout: float,
    max_stdout: int,
    max_stderr: int,
    max_total_artifacts: int,
) -> dict:
    """Execute one case in fresh dirs under work_case. Returns raw facts."""
    app_dir = work_case / "app"
    resources_dir = work_case / "resources"
    output_dir = work_case / "output"
    home_dir = work_case / "home"
    tmp_dir = work_case / "tmp"
    venv_dir = work_case / "venv"
    for d in (work_case,):
        d.mkdir(parents=True, exist_ok=True)
    # Fresh owned empty subdirs.
    for d in (home_dir, tmp_dir, output_dir):
        d.mkdir(parents=True, exist_ok=True)
    descriptor = candidate.descriptor
    # 1. App copy.
    write_app_copy(candidate.application_members, app_dir)
    # 2. Resources.
    projected, slots_sorted = project_resources(
        descriptor=descriptor, case=case, profile_members=profile.members, resources_dir=resources_dir
    )
    # 3. Venv setup (separate hard timeout, bounded output) with owned HOME/TMP.
    setup_home = work_case / "setup-home"
    setup_tmp = work_case / "setup-tmp"
    setup_home.mkdir(parents=True, exist_ok=True)
    setup_tmp.mkdir(parents=True, exist_ok=True)
    setup_env = scrubbed_env(
        {"HOME": str(setup_home), "USERPROFILE": str(setup_home), "TMPDIR": str(setup_tmp), "TMP": str(setup_tmp), "TEMP": str(setup_tmp)}
    )
    setup_env["HOME"] = str(setup_home)
    setup_env["USERPROFILE"] = str(setup_home)
    setup_env["TMPDIR"] = str(setup_tmp)
    setup_env["TMP"] = str(setup_tmp)
    setup_env["TEMP"] = str(setup_tmp)
    # Ensure work_case exists for venv parent.
    venv_python = ensure_venv(venv_dir, setup_env=setup_env)
    pip_install_wheel(venv_python=venv_python, wheel_path=wheel_path, setup_env=setup_env)
    # 4. Build child env.
    connection_manifest = {"schema": "capy.connection-manifest/v0", "invocation_id": "acceptance-case", "connections": []}
    child_extra = {
        "CAPY_RESOURCE_MANIFEST": json.dumps(projected, separators=(",", ":")),
        "CAPY_RESOURCE_SLOTS": json.dumps(slots_sorted, separators=(",", ":")),
        "CAPY_CONNECTION_MANIFEST": json.dumps(connection_manifest, separators=(",", ":")),
        "CAPY_OUTPUT_DIR": str(output_dir),
        "HOME": str(home_dir),
        "USERPROFILE": str(home_dir),
        "TMPDIR": str(tmp_dir),
        "TMP": str(tmp_dir),
        "TEMP": str(tmp_dir),
    }
    # On posix, also set XDG? Not needed.
    child_env = scrubbed_env(child_extra)
    # Re-assert scrubbed values that must not be inherited.
    # Ensure HOME/TMP point to our owned dirs.
    child_env["HOME"] = str(home_dir)
    child_env["USERPROFILE"] = str(home_dir)
    child_env["TMPDIR"] = str(tmp_dir)
    child_env["TMP"] = str(tmp_dir)
    child_env["TEMP"] = str(tmp_dir)
    # 5. Request bytes canonical.
    request_bytes = codec.canonical_bytes(case["request"])
    # 6. Entrypoint.
    entrypoint = descriptor["entrypoint"]
    entry_path = app_dir / entrypoint
    if not entry_path.is_file() or entry_path.is_symlink():
        # Treat as application exit error (not env).
        return {
            "case_id": case["case_id"],
            "order": case_order,
            "timed_out": False,
            "output_limited": False,
            "exit_code": 99,
            "stdout": b"",
            "stderr": b"ENTRYPOINT_MISSING\n",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "duration_ms": 0,
            "projected": projected,
            "artifacts": [],
            "artifact_anomaly": "missing-entrypoint",
            "envelope_error": "entrypoint",
            "observed_result": None,
            "observed_failure_code": None,
            "observed_status": "error",
            "secret_hit": False,
        }
    res = run_bounded(
        [str(venv_python), str(entry_path)],
        input_bytes=request_bytes,
        timeout_seconds=per_case_timeout,
        max_stdout=max_stdout,
        max_stderr=max_stderr,
        env=child_env,
        cwd=app_dir,
    )
    timed_out = res.timed_out
    output_limited = res.stdout_truncated or res.stderr_truncated
    # Truncate flags: if timed_out, exit_code None.
    exit_code = res.exit_code
    stdout = res.stdout
    stderr = res.stderr
    # If output limited, we killed; keep bounded prefix for scanning (bounded).
    # Collect artifacts (before cleanup) even on failure? Spec says every declared
    # artifact collected before cleanup; for failures, no artifacts expected.
    # Bounded collection enforces the aggregate limit during reads (+1 to
    # detect overflow) with causal evidence via total_bytes.
    artifacts, anomaly = collect_artifacts(output_dir, max_total_artifacts)
    # Check total artifact bytes vs max_total.
    total_bytes = sum(len(b) for _, b in artifacts)
    if total_bytes > max_total_artifacts:
        output_limited = True
    # Secret scan of bounded outputs/artifacts (defense in depth).
    # Scan all permitted artifact bytes (retained prefix is already bounded
    # to limit+1 total, up to 8 MiB).
    secret_hit = False
    scan_blobs: list[bytes] = [stdout[: max_stdout + 1], stderr[: max_stderr + 1]]
    for _, data in artifacts:
        scan_blobs.append(data)
    from .scan import scan_many

    if scan_many(scan_blobs):
        secret_hit = True
    # Parse envelope based on exit code.
    envelope_error = None
    observed_result = None
    observed_failure_code = None
    observed_status = "error"
    if not timed_out and not output_limited:
        if exit_code == 0:
            parsed, err = parse_success_envelope(stdout)
            if err is not None:
                envelope_error = err
            else:
                # Validate declared vs actual files.
                declared = parsed.pop("artifacts", None) if isinstance(parsed, dict) else None
                # parsed is result without artifacts; declared is list from envelope.
                # Need to re-parse to get declared: parse_success_envelope already popped?
                # Actually it returns result without artifacts; we lost declared.
                # Re-extract declared from stdout strictly (duplicates/
                # nonfinite already rejected by parse_success_envelope).
                try:
                    env_full = codec.parse_strict_json(stdout[:-1])
                    declared_list = env_full.get("artifacts", []) if isinstance(env_full, dict) else None
                except Exception:
                    declared_list = None
                    envelope_error = "envelope"
                if envelope_error is None:
                    if not isinstance(declared_list, list):
                        envelope_error = "artifacts-type"
                    else:
                        actual_names = sorted(n for n, _ in artifacts)
                        # Declared must match actual files exactly (DevKit rule).
                        if sorted(declared_list) != actual_names:
                            envelope_error = "declaration-mismatch"
                        elif anomaly is not None and anomaly in ("symlink", "non-file", "unsafe-name"):
                            # Filesystem anomaly with otherwise matching set still rejected.
                            # Treat unsafe/symlink as envelope error (exit path).
                            # For unsafe-name, spec says not projected; but if declared
                            # matches actual (excluding unsafe), anomaly indicates extra
                            # unsafe file present -> set mismatch handled later. Keep
                            # envelope valid and let comparison handle set mismatch.
                            # Only symlink/non-file cause exit error.
                            if anomaly in ("symlink", "non-file"):
                                envelope_error = "artifact-anomaly"
                            else:
                                observed_result = parsed
                                observed_status = "ok"
                        else:
                            observed_result = parsed
                            observed_status = "ok"
                        # Side-effect check: read_only must have no artifacts (descriptor).
                        if envelope_error is None and descriptor.get("side_effect") == "read_only" and declared_list:
                            envelope_error = "side-effect"
                # Store declared for later? Not needed; comparison uses actual_artifacts.
                # But need to handle case where envelope valid but side-effect violated.
        elif exit_code == 2:
            # Stable failure requires empty stdout and exactly one stderr line.
            if stdout != b"":
                envelope_error = "failure-stdout"
            else:
                code, err = parse_failure_stderr(stderr)
                if err is not None:
                    envelope_error = err
                else:
                    observed_failure_code = code
                    observed_status = "failed"
                    # Failed must have no artifacts? If artifacts present with failed, that's extra.
                    # DevKit runner would have declared () for failed; but our app with fail()
                    # should not create artifacts. If artifacts non-empty on failed, treat as
                    # declaration mismatch -> envelope error? Spec says failed cases have none.
                    # We'll allow comparison to handle: if artifacts non-empty, set mismatch will
                    # trigger, but envelope remains valid. Keep valid and let comparison decide.
                    # However if anomaly indicates files present, that's extra -> set mismatch.
                    pass
        else:
            envelope_error = f"exit-{exit_code}"
            observed_status = "error"
    else:
        observed_status = "error"
    return {
        "case_id": case["case_id"],
        "order": case_order,
        "timed_out": timed_out,
        "output_limited": output_limited,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": res.stdout_truncated,
        "stderr_truncated": res.stderr_truncated,
        "duration_ms": res.duration_ms,
        "projected": projected,
        "artifacts": artifacts,
        "artifact_anomaly": anomaly,
        "envelope_error": envelope_error,
        "observed_result": observed_result,
        "observed_failure_code": observed_failure_code,
        "observed_status": observed_status,
        "secret_hit": secret_hit,
    }
